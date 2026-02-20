from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class DocumentApproval(models.Model):
    _name = 'document.approval'
    _rec_name = 'computed_name'
    _description = 'Solicitud Documentos'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

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
        ('approved_by_director_i_d', 'Aprobación del Director I+D'),
        ('approved_by_director_gerente', 'Aprobación del Director Gerente'),
        ('sign_company', 'Esperando firma de empresa'),
        ('final_revision', 'Revisión final'),
        ('approve', 'Aprobada'),
        ('rejected', 'Rechazada'),
    ], string='Estado', default='approved_by_director_i_d', tracking=True)

    is_company_signed = fields.Boolean(string='Firmado por la empresa', default=False, tracking=True)

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

    # ─────────────────────────────────────────────
    # Integración con módulo sign de Odoo 19 Enterprise
    # ─────────────────────────────────────────────

    def action_send_to_sign(self):
        """Crea una sign.template a partir del adjunto del documento y lanza
        un sign.request para que el Director Gerente firme digitalmente."""
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
            # Desactivar la template efímera anterior
            old_template = self.sign_request_id.template_id
            self.sign_request_id = False
            if old_template:
                old_template.active = False

        # Obtener el rol por defecto del módulo sign
        default_role = self.env.ref('sign.sign_item_role_default', raise_if_not_found=False)
        if not default_role:
            default_role = self.env['sign.item.role'].search([('default', '=', True)], limit=1)
        if not default_role:
            raise UserError(_("No se encontró un rol de firma por defecto. Verifique la configuración del módulo Sign."))

        # Obtener el tipo de firma 'signature' del módulo sign
        sign_type = self.env['sign.item.type'].search([('item_type', '=', 'signature')], limit=1)
        if not sign_type:
            raise UserError(_("No se encontró el tipo de campo 'Firma' en el módulo Sign. Verifique la configuración."))

        # Crear sign.template dinámica con el adjunto del documento
        sign_template = self.env['sign.template'].create({
            'name': self.computed_name or _('Documento para firmar'),
            'document_ids': [(0, 0, {
                'attachment_id': attachment.id,
            })],
        })

        # Obtener el sign.document creado y calcular la última página
        sign_document = sign_template.document_ids[:1]
        last_page = sign_document.num_pages or 1

        # Añadir campo de firma en la parte inferior derecha de la última página
        self.env['sign.item'].create({
            'document_id': sign_document.id,
            'type_id': sign_type.id,
            'responsible_id': default_role.id,
            'required': True,
            'name': sign_type.placeholder or sign_type.name or 'Firma',
            'page': last_page,
            'posX': 0.65,
            'posY': 0.85,
            'width': sign_type.default_width,
            'height': sign_type.default_height,
        })

        # El firmante es el usuario actual (Director Gerente)
        signer_partner = self.env.user.partner_id
        if not signer_partner.email:
            raise UserError(_(
                "El usuario %s no tiene email configurado. "
                "Es necesario para enviar la solicitud de firma."
            ) % self.env.user.name)

        # Crear sign.request con context no_sign_mail=True para controlar el envío
        sign_request = self.env['sign.request'].with_context(no_sign_mail=True).create({
            'template_id': sign_template.id,
            'reference': self.computed_name or _('Documento para firmar'),
            'reference_doc': f'{self._name},{self.id}',
            'request_item_ids': [(0, 0, {
                'partner_id': signer_partner.id,
                'role_id': default_role.id,
            })],
        })

        self.sign_request_id = sign_request.id

        # Registrar en el chatter
        self.sudo().message_post(
            body=_("Se ha enviado una solicitud de firma electrónica a %s.") % signer_partner.name,
            subtype_id=self.env.ref('mail.mt_note').id,
        )

        # Abrir el documento de firma directamente para que el Director Gerente firme
        return sign_request.go_to_signable_document()

    def action_view_sign_request(self):
        """Abre la solicitud de firma asociada."""
        self.ensure_one()
        if not self.sign_request_id:
            raise UserError(_("No hay ninguna solicitud de firma asociada a este documento."))
        return self.sign_request_id.go_to_document()

    # ─────────────────────────────────────────────
    # Flujo de aprobación
    # ─────────────────────────────────────────────

    def action_solicite_final_revision(self):
        self.ensure_one()
        if self.status == 'sign_company' and self.env.user.has_group("portal_requests.group_equip_boss"):
            self.status = 'final_revision'
            self.is_company_signed = True
            group = self.env.ref('portal_requests.group_director_manager')
            user_to_send = group.user_ids
            self.send_request_email(self.type_id.name, user_to_send, "final_revision")

    def action_approve(self):
        self.ensure_one()
        if self.status == 'approved_by_director_i_d' and self.env.user.has_group(
                "portal_requests.group_director_investigation_and_development"):
            self.status = 'approved_by_director_gerente'
            group = self.env.ref('portal_requests.group_director_manager')
            user_to_send = group.user_ids
            self.send_request_email(self.type_id.name, user_to_send, "approved_by_director_i_d")

        if self.status == 'approved_by_director_gerente' and self.env.user.has_group(
                "portal_requests.group_director_manager"):
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

    def action_reject(self):
        for record in self:
            record.status = 'rejected'

    def action_to_revise(self):
        self.ensure_one()
        if self.env.user.has_group("portal_requests.group_director_manager"):
            self.status = 'sign_company'
        else:
            raise UserError(_("Solo el director gerente puede enviar a revisión."))

    # ─────────────────────────────────────────────
    # Envío de emails
    # ─────────────────────────────────────────────

    def send_request_email(self, move_text, user_to_send, type):
        document_request_link = (
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

            if type == "approved_by_director_i_d":
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
