from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class DocumentApproval(models.Model):
    _name = 'document.approval'
    _rec_name = 'computed_name'
    _description = 'Solicitud Documentos'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin', 'portal.request.notify.mixin']

    _notify_state_field = 'status'
    _notify_portal_route = '/my/documents'


    type_id = fields.Many2one('type.approval', string='Tipo', required=True, tracking=True)
    computed_name = fields.Char('Computed Name', compute='_compute_name')
    description = fields.Text(string='Descripción', tracking=True)
    company_id = fields.Many2one('res.company', string='Grupo de trabajo', tracking=True)

    def _get_work_group_id(self):
        for record in self:
            work_group = self.env['portal.work.group'].search([
                ('user_ids', 'in', record.user_id.id)
            ], limit=1)
            record.work_group_id = work_group.id if work_group else False

    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', store=True)
    user_id = fields.Many2one('res.users', string='Solicitante', tracking=True)
    status = fields.Selection([
        ('approved_by_equip_boss', 'Aprobación del Jefe de Equipo'),
        ('approved_by_director_i_d', 'Aprobación del Director I+D'),
        ('approved_by_director_gerente', 'Aprobación del Director Gerente'),
        ('sign_company', 'Esperando firma de empresa'),
        ('final_revision', 'Revisión final'),
        ('approve', 'Aprobada'),
        ('rejected', 'Rechazada'),
    ], string='Estado', default='approved_by_equip_boss', tracking=True)

    is_company_signed = fields.Boolean(string='Firmado por la empresa', default=False, tracking=True)

    # Plantilla efímera de Sign: se crea al pulsar "Firmar digitalmente" y se abre
    # en el editor visual (panel lateral con campos arrastrables). El sign.request
    # lo genera el propio editor al pulsar "Firmar ahora".
    sign_template_id = fields.Many2one(
        'sign.template',
        string='Plantilla de Firma',
        copy=False,
        ondelete='set null',
    )
    # Enlace a la solicitud de firma del módulo sign de Odoo 19 Enterprise
    sign_request_id = fields.Many2one(
        'sign.request',
        string='Solicitud de Firma',
        copy=False,
        tracking=True,
        ondelete='set null',
    )
    sign_request_state = fields.Selection(
        related='sign_request_id.state',
        string='Estado de Firma',
        store=False,
    )

    # Campo computed para mostrar botón de solicitar revisión en el portal
    show_solicitar_revision_final = fields.Boolean(
        string='Mostrar Solicitar Revisión Final',
        compute='_compute_show_solicitar_revision_final',
        store=False,
    )

    @api.depends('status')
    def _compute_show_solicitar_revision_final(self):
        for record in self:
            record.show_solicitar_revision_final = record.status == 'sign_company'

    def _compute_name(self):
        for record in self:
            record.computed_name = f"{record.type_id.name} - {record.description}"

    def _initial_status_for(self, work_group, requester):
        """Estado de arranque del circuito según quién solicita.

        El propio Jefe de Equipo no necesita aprobarse a sí mismo: si es
        quien solicita, se salta ese paso y entra directamente en la
        aprobación del Director I+D. Cualquier otro solicitante (incluido
        el Administrativo del mismo grupo) pasa primero por la aprobación
        del Jefe de Equipo."""
        if work_group and requester and work_group.equip_boss == requester:
            return 'approved_by_director_i_d'
        return 'approved_by_equip_boss'

    @api.model_create_multi
    def create(self, vals_list):
        WorkGroup = self.env['portal.work.group']
        for vals in vals_list:
            if vals.get('work_group_id') and vals.get('user_id'):
                work_group = WorkGroup.browse(vals['work_group_id'])
                requester = self.env['res.users'].browse(vals['user_id'])
                vals.setdefault('status', self._initial_status_for(work_group, requester))
        return super().create(vals_list)

    # ─────────────────────────────────────────────
    # Integración con módulo sign de Odoo 19 Enterprise
    # ─────────────────────────────────────────────

    def action_send_to_sign(self):
        """Crea una sign.template a partir del adjunto del documento y abre
        el editor visual de Sign (panel lateral con campos arrastrables).
        El Director Gerente coloca los campos y pulsa 'Firmar ahora' para
        firmar directamente sin envío por email."""
        self.ensure_one()

        # Verificar que hay un adjunto PDF
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'document.approval'),
            ('res_id', '=', self.id),
        ], limit=1)

        if not attachment:
            raise UserError(_(
                "No se encontró ningún adjunto en este documento. "
                "Suba el PDF antes de enviarlo a firmar."
            ))

        # Cancelar solicitud de firma anterior si existe y no está firmada
        if self.sign_request_id and self.sign_request_id.state != 'signed':
            self.sign_request_id.cancel()
            self.sign_request_id = False

        # Desactivar la template efímera anterior si existe
        if self.sign_template_id:
            self.sign_template_id.active = False
            self.sign_template_id = False

        # Crear sign.template dinámica con el adjunto del documento.
        # Se crea con active=False para que no aparezca en el listado de plantillas
        # del módulo Sign. El editor la activará automáticamente al abrirla.
        sign_template = self.env['sign.template'].create({
            'name': self.computed_name or _('Documento para firmar'),
            'active': True,
            'document_ids': [(0, 0, {
                'attachment_id': attachment.id,
            })],
        })

        # Guardar la referencia a la template para poder recuperar el sign.request
        # que el editor crea al pulsar "Firmar ahora"
        self.sign_template_id = sign_template.id

        # Registrar en el chatter
        self.sudo().message_post(
            body=_("Se ha abierto el editor de firma digital. Coloque los campos y pulse 'Firmar ahora'."),
            subtype_id=self.env.ref('mail.mt_note').id,
        )

        # Abrir el editor visual de Sign con el panel lateral de campos arrastrables.
        # sign_directly_without_mail=True → el botón "Firmar ahora" firma sin diálogo de email.
        # default_reference_doc → al cerrar el diálogo "Gracias" de Sign, vuelve al
        # formulario de este document.approval (sign.request.get_close_values lo usa).
        action = sign_template.go_to_custom_template(sign_directly_without_mail=True)
        # go_to_custom_template devuelve context como frozendict (inmutable),
        # hay que crear un nuevo dict normal con dict().
        action['context'] = dict(
            action.get('context') or {},
            default_reference_doc=f'document.approval,{self.id}',
            default_signer_id=self.env.user.partner_id.id,
        )
        return action

    def _sync_sign_request(self):
        """Busca el sign.request creado desde el editor visual y lo vincula
        a este documento si aún no está guardado en sign_request_id."""
        self.ensure_one()
        if self.sign_request_id:
            return
        if not self.sign_template_id:
            return
        # El editor crea el sign.request vinculado a la template
        sign_request = self.env['sign.request'].search([
            ('template_id', '=', self.sign_template_id.id),
            ('state', '!=', 'canceled'),
        ], order='id desc', limit=1)
        if sign_request:
            self.sign_request_id = sign_request.id

    def action_view_sign_request(self):
        """Abre la solicitud de firma asociada, o el editor de plantilla si
        el usuario aún no ha pulsado 'Firmar ahora' desde el editor."""
        self.ensure_one()
        # Intentar sincronizar por si el request ya fue creado desde el editor
        self._sync_sign_request()
        if self.sign_request_id:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Solicitud de Firma'),
                'res_model': 'sign.request',
                'res_id': self.sign_request_id.id,
                'views': [[False, 'form']],
                'target': 'current',
            }
        if self.sign_template_id:
            # El editor aún no ha generado el request: reabrir el editor
            # go_to_custom_template devuelve context como frozendict (inmutable).
            action = self.sign_template_id.go_to_custom_template(sign_directly_without_mail=True)
            action['context'] = dict(
                action.get('context') or {},
                default_reference_doc=f'document.approval,{self.id}',
                default_signer_id=self.env.user.partner_id.id,
            )
            return action
        raise UserError(_("No hay ninguna solicitud de firma asociada a este documento."))

    # ─────────────────────────────────────────────
    # Flujo de aprobación
    # ─────────────────────────────────────────────

    def action_solicite_final_revision(self):
        self.ensure_one()
        if self.status == 'sign_company':
            self.status = 'final_revision'
            self.is_company_signed = True
            group = self.env.ref('portal_requests.group_director_manager')
            user_to_send = group.sudo().user_ids
            self.send_request_email(self.type_id.name, user_to_send, "final_revision")

    def action_approve(self):
        self.ensure_one()
        if (self.status == 'approved_by_equip_boss'
                and self.work_group_id._is_equip_boss_step_approver(self.env.user)
                and not (self.work_group_id and self.env.user == self.user_id)):
            self.status = 'approved_by_director_i_d'
            group = self.env.ref('portal_requests.group_director_investigation_and_development')
            user_to_send = group.sudo().user_ids
            self.send_request_email(self.type_id.name, user_to_send, "approved_by_equip_boss")

        if self.status == 'approved_by_director_i_d' and self.env.user.has_group(
                "portal_requests.group_director_investigation_and_development"):
            self.status = 'approved_by_director_gerente'
            group = self.env.ref('portal_requests.group_director_manager')
            user_to_send = group.user_ids
            self.send_request_email(self.type_id.name, user_to_send, "approved_by_director_i_d")

        if self.status == 'approved_by_director_gerente' and self.env.user.has_group(
                "portal_requests.group_director_manager"):
            # Sincronizar el sign.request si fue creado desde el editor visual
            self._sync_sign_request()
            # Verificar que el Director Gerente ha firmado mediante sign
            if not self.sign_request_id or self.sign_request_id.state != 'signed':
                raise UserError(_(
                    "El Director Gerente debe firmar digitalmente el documento antes de aprobar. "
                    "Use el botón 'Firmar digitalmente' y complete la firma."
                ))
            if self.is_company_signed:
                group = self.env.ref('portal_requests.group_director_investigation_and_development')
                user_to_send = group.user_ids
                self.status = 'final_revision'
                self.send_request_email(self.type_id.name, user_to_send, "final_revision")
            else:
                user_to_send = self.user_id
                self.status = 'sign_company'
                self.send_request_email(self.type_id.name, user_to_send, "sign_director_manager")

        if self.status == 'final_revision' and self.env.user.has_group(
                "portal_requests.group_director_investigation_and_development"):
            self.status = 'approve'
            user_to_send = self.user_id
            self.send_request_email(self.type_id.name, user_to_send, "final_revision")

    def action_reject(self, reason=None):
        """Rechaza el documento. ``reason`` es el motivo indicado por el Jefe
        de Equipo al rechazar desde el portal: se guarda en el histórico y se
        incluye en el correo al solicitante."""
        for record in self:
            record.status = 'rejected'
            body = _(
                "Documento rechazado. El solicitante puede subir una nueva "
                "versión y reenviar la solicitud sin perder el histórico."
            )
            if reason:
                body = _("Documento rechazado. Motivo: %s", reason)
            record.sudo().message_post(
                body=body,
                subtype_id=self.env.ref('mail.mt_note').id,
            )
            if record.user_id:
                record.send_request_email(record.type_id.name, record.user_id, "rejected", notes=reason or "")

    def _notify_new_request(self):
        """Aviso de documento nuevo: al Jefe de Equipo del grupo si la
        solicitud empieza en su paso; si no (lo solicita el propio Jefe de
        Equipo, o no tiene grupo de trabajo), al Director I+D como hasta
        ahora."""
        self.ensure_one()
        if self.status == 'approved_by_equip_boss' and self.work_group_id.equip_boss:
            recipients = self.work_group_id.equip_boss
        else:
            recipients = self.env.ref(
                'portal_requests.group_director_investigation_and_development'
            ).sudo().user_ids
        if recipients:
            self.send_request_email(self.type_id.name, recipients, "new")

    def action_resubmit(self):
        """Reabre una solicitud rechazada para que el solicitante aporte una
        nueva versión del documento dentro del mismo flujo, conservando el
        histórico en el chatter y reiniciando el circuito de aprobación."""
        self.ensure_one()
        if self.status != 'rejected':
            raise UserError(_("Solo puede reenviar solicitudes rechazadas."))
        if self.sign_request_id and self.sign_request_id.state != 'signed':
            self.sign_request_id.cancel()
        restart_status = self._initial_status_for(self.work_group_id, self.user_id)
        self.write({
            'status': restart_status,
            'is_company_signed': False,
        })
        self.sudo().message_post(
            body=_(
                "El solicitante ha aportado una nueva versión y ha reenviado la "
                "solicitud a revisión."
            ),
            subtype_id=self.env.ref('mail.mt_note').id,
        )
        if restart_status == 'approved_by_equip_boss':
            recipients = self.work_group_id._equip_boss_step_recipients()
        else:
            recipients = self.env.ref(
                'portal_requests.group_director_investigation_and_development'
            ).sudo().user_ids
        if recipients:
            self.send_request_email(self.type_id.name, recipients, "resubmit")

    def action_to_revise(self):
        self.ensure_one()
        if self.env.user.has_group("portal_requests.group_director_manager"):
            self.status = 'sign_company'
        else:
            raise UserError(_("Solo el director gerente puede enviar a revisión."))

    # ─────────────────────────────────────────────
    # Envío de emails
    # ─────────────────────────────────────────────

    def send_request_email(self, move_text, user_to_send, type, notes=""):
        backend_link = (
            f"/web#id={self.id}&cids=1-24-28-29-32-25-30-31"
            f"&menu_id=899&active_id=1&model=document.approval&view_type=form"
        )
        user = self.user_id

        if not user_to_send:
            raise UserError(_("No se encontraron usuarios a los que enviar el correo."))

        for admin_user in user_to_send:
            if not admin_user.email:
                continue
            user_for_send = self.env.user.name
            admin_name = admin_user.name
            # El Jefe de Equipo es usuario de portal: enlace al portal.
            document_request_link = self._notify_link_for(admin_user, backend_link)
            notes_html = f"<p><strong>Motivo:</strong> <em>{notes}</em></p>" if notes else ""

            if type == "new":
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>El usuario {user.name} ha creado una solicitud de nuevo documento.</p>
                    <ul>
                        <li><strong>Usuario:</strong> {user.name}</li>
                        <li><strong>Tipo:</strong> {move_text}</li>
                        <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                    </ul>
                    <p>Saludos cordiales, Odoo</p>
                """
            elif type == "approved_by_equip_boss":
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>El Jefe de Equipo, {user_for_send}, ya ha dado su aprobación para la siguiente solicitud:</p>
                    <ul>
                        <li><strong>Solicitante:</strong> {user.name}</li>
                        <li><strong>Tipo:</strong> {move_text}</li>
                        <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                    </ul>
                    <p>Saludos cordiales, Odoo</p>
                """
            elif type == "approved_by_director_i_d":
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>El Director de I+D, {user_for_send}, ya ha dado su aprobación para la siguiente solicitud:</p>
                    <ul>
                        <li><strong>Solicitante:</strong> {user.name}</li>
                        <li><strong>Tipo:</strong> {move_text}</li>
                        <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                    </ul>
                    <p>Saludos cordiales, Odoo</p>
                """
            elif type == "sign_director_manager":
                document_request_link = (
                    f"/my/documents/{self.id}"
                )
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>El Director Gerente, {user_for_send}, ya ha firmado digitalmente la siguiente solicitud:</p>
                    <p>Es necesario que la empresa firme el documento para continuar con el proceso.</p>
                    <ul>
                        <li><strong>Solicitante:</strong> {user.name}</li>
                        <li><strong>Tipo:</strong> {move_text}</li>
                        <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                    </ul>
                    <p>Saludos cordiales, Odoo</p>
                """
            elif type == "sign_company":
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>El jefe de equipo, {user_for_send}, ha confirmado la firma de la empresa en la solicitud:</p>
                    <ul>
                        <li><strong>Solicitante:</strong> {user.name}</li>
                        <li><strong>Tipo:</strong> {move_text}</li>
                        <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                    </ul>
                    <p>Saludos cordiales, Odoo</p>
                """
            elif type == "rejected":
                portal_link = f"/my/documents/{self.id}"
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>Su solicitud de documento ha sido rechazada.</p>
                    {notes_html}
                    <p>Puede subir una nueva versión del documento y reenviar la
                    solicitud desde el portal, sin perder el histórico, a través
                    del siguiente enlace:</p>
                    <ul>
                        <li><strong>Tipo:</strong> {move_text}</li>
                        <li><strong>Enlace:</strong> <a href="{portal_link}">Subir nueva versión</a></li>
                    </ul>
                    <p>Saludos cordiales, Odoo</p>
                """
            elif type == "resubmit":
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>El solicitante {user.name} ha aportado una nueva versión de un
                    documento previamente rechazado y lo ha reenviado a revisión:</p>
                    <ul>
                        <li><strong>Solicitante:</strong> {user.name}</li>
                        <li><strong>Tipo:</strong> {move_text}</li>
                        <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                    </ul>
                    <p>Saludos cordiales, Odoo</p>
                """
            else:
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>El Director Gerente ya ha dado su aprobación para la siguiente solicitud:</p>
                    <ul>
                        <li><strong>Solicitante:</strong> {user.name}</li>
                        <li><strong>Tipo:</strong> {move_text}</li>
                        <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                    </ul>
                    <p>Saludos cordiales, Odoo</p>
                """

            mail_values = {
                'subject': 'Solicitud de documento',
                'email_from': 'no-reply@aicia.com',
                'email_to': admin_user.email,
                'body_html': body_html,
            }
            mail = self.env['mail.mail'].create(mail_values)
            mail.send()
