# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Rol del usuario -> clave del artículo de Knowledge con su manual
# (data/knowledge_manuals.xml: portal_requests.manual_article_<clave>).
# El orden importa: el Administrativo implica el grupo de Jefe de Equipo.
MANUAL_ROLES = [
    ('portal_requests.group_administrative', 'administrativo'),
    ('portal_requests.group_equip_boss', 'jefe_de_equipo'),
    ('portal_requests.group_project_boss', 'jefe_de_proyecto'),
    ('portal_requests.group_director_investigation_and_development', 'director_i_d'),
    ('portal_requests.group_director_manager', 'director_gerente'),
    ('portal_requests.group_personnel_purchase_responsible', 'responsable_personal_y_compras'),
    ('portal_requests.group_intern_partner_responsible', 'responsable_clientes_y_becarios'),
    ('portal_requests.group_financial_director', 'director_financiero'),
]
DEFAULT_MANUAL = 'solicitante'
# Perfil que puede leer en Knowledge los manuales de todos los roles
MANUAL_ALL_ROLES_GROUP = 'portal_requests.group_director_manager'


class KnowledgeArticle(models.Model):
    _inherit = 'knowledge.article'

    # Carpeta y manuales de data/knowledge_manuals.xml. Una regla global
    # (rule_portal_manual_by_role) limita su lectura a sus miembros, también
    # para los administradores de Odoo.
    is_portal_manual = fields.Boolean(readonly=True, copy=False)

    @api.model
    def _sync_portal_manual_members(self):
        """En Knowledge cada usuario interno lee solo el manual de su rol, aunque
        sea administrador de Odoo; el Director Gerente los lee todos. Knowledge
        da acceso por persona, no por grupo, así que los miembros de lectura se
        recalculan desde los grupos al actualizar el módulo y al cambiar los
        grupos de un usuario. Los editores (el Administrador) no se tocan. Los
        usuarios de portal no entran en Knowledge: ven su manual en /my/manual."""
        root = self.env.ref('portal_requests.manual_article_root', raise_if_not_found=False)
        if not root:
            return
        all_roles = self._portal_manual_group_partners(MANUAL_ALL_ROLES_GROUP)
        root_readers = all_roles
        for key in [key for _group, key in MANUAL_ROLES] + [DEFAULT_MANUAL]:
            article = self.env.ref(f'portal_requests.manual_article_{key}', raise_if_not_found=False)
            if not article:
                continue
            group = next((group for group, role_key in MANUAL_ROLES if role_key == key), False)
            readers = all_roles | self._portal_manual_group_partners(group)
            article.sudo()._set_portal_manual_readers(readers)
            root_readers |= readers
        # La carpeta padre la lee cualquiera con manual: sin ella Knowledge no
        # muestra el manual en el lateral.
        root.sudo()._set_portal_manual_readers(root_readers)

    @api.model
    def _portal_manual_group_partners(self, group_xmlid):
        group = group_xmlid and self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return self.env['res.partner']
        users = group.sudo().all_user_ids.filtered(lambda user: user.active and not user.share)
        return users.partner_id

    def _set_portal_manual_readers(self, partners):
        self.ensure_one()
        if self.parent_id and not self.is_desynchronized:
            # Deja de heredar los permisos de la carpeta padre (conserva sus editores)
            self.write(self._desync_access_from_parents_values(force_internal_permission='none'))
        members = self.article_member_ids
        commands = [(2, member.id) for member in members
                    if member.permission == 'read' and member.partner_id not in partners]
        commands += [(0, 0, {'partner_id': partner.id, 'permission': 'read'})
                     for partner in partners - members.partner_id]
        vals = {}
        if not self.is_portal_manual:
            vals['is_portal_manual'] = True
        if commands:
            vals['article_member_ids'] = commands
        if self.internal_permission != 'none':
            vals['internal_permission'] = 'none'
        if self.is_article_visible_by_everyone:
            vals['is_article_visible_by_everyone'] = False
        if vals:
            self.write(vals)
