from odoo import models, fields, api

class WorkGroup(models.Model):
    _name = 'portal.work.group'
    _description = 'Grupos de Trabajo'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(string='Código', required=True)
    user_ids = fields.Many2many(
        'res.users',
        'work_group_users_rel',
        'group_id',
        'user_id',
        string='Usuarios'
    )

    equip_boss_domain = fields.Many2many('res.users', compute='_compute_equip_boss_domain')


    @api.depends('user_ids')
    def _compute_equip_boss_domain(self):
        for record in self:
            if record.user_ids:
                # Usar has_group para detectar correctamente usuarios portal/internos
                # ya que group_ids no incluye grupos implícitos/heredados
                domain_user = record.user_ids.filtered(
                    lambda u: u.has_group('portal_requests.group_equip_boss')
                )
                record.equip_boss_domain = domain_user.ids
            else:
                record.equip_boss_domain = []

    equip_boss = fields.Many2one(
        'res.users',
        string='Jefe de Equipo'
    )

    administrative_domain = fields.Many2many('res.users', compute='_compute_administrative_domain')

    @api.depends('user_ids')
    def _compute_administrative_domain(self):
        for record in self:
            if record.user_ids:
                # Usar has_group para detectar correctamente usuarios portal/internos
                # ya que group_ids no incluye grupos implícitos/heredados. Se filtra
                # específicamente por group_administrative (no por group_equip_boss)
                # para que solo aparezcan usuarios con el rol Administrativo.
                domain_user = record.user_ids.filtered(
                    lambda u: u.has_group('portal_requests.group_administrative')
                )
                record.administrative_domain = domain_user.ids
            else:
                record.administrative_domain = []

    administrative_id = fields.Many2one(
        'res.users',
        string='Administrativo'
    )

    def _is_boss_or_administrative(self, user):
        """True si `user` es el Jefe de Equipo o el Administrativo de este
        grupo de trabajo. Ambos roles ven los mismos proyectos y solicitudes
        del equipo; el Administrativo solo se diferencia en que no ve la
        información económica (ver _hide_project_financials en el portal)."""
        if not self:
            return False
        self.ensure_one()
        return self.equip_boss == user or self.administrative_id == user

    @api.model
    def _boss_or_administrative_domain(self, user):
        """Dominio ir.rule-friendly: grupos de trabajo donde `user` es Jefe
        de Equipo o Administrativo."""
        return ['|', ('equip_boss', '=', user.id), ('administrative_id', '=', user.id)]
