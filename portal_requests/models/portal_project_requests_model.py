from odoo import models, fields, api , _
from odoo.exceptions import UserError

class PortalProjectRequest(models.Model):
    _name = 'portal.project.request'
    _description = 'Portal Project Request'
    _rec_name = 'computed_name'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin', 'portal.request.notify.mixin']

    _notify_portal_route = '/my/project_requests'


    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, tracking=True)
    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', tracking=True)
    member_ids = fields.Many2many(
        'res.users',
        'portal_project_request_member_rel',
        'request_id',
        'user_id',
        string='Miembros del Proyecto',
    )
    member_domain = fields.Many2many('res.users', compute='_compute_member_domain')
    partner_id = fields.Many2one('res.partner', string='Cliente', tracking=True)
    partner_id_char = fields.Char(string='Nombre del Cliente', store=True)
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    project_name = fields.Char(string='Project Name')
    signed_contract = fields.Binary(string="Signed Contract", attachment=True)
    budget_file = fields.Binary(string="Budget", attachment=True)
    signed_contract_filename = fields.Char(string="Signed Contract Filename")
    budget_file_filename = fields.Char(string="Budget Filename")
    approved = fields.Boolean(string='Approved', default=False)
    is_revised = fields.Boolean(string='Is revised', default=False, store=True)
    status = fields.Selection([
        ('approved_by_equip_boss', 'Aprobación del Jefe de Equipo'),
        ('pending_review', 'Pendiente de Revisión'),
    ], string='Estado', default='approved_by_equip_boss', tracking=True)
    computed_name = fields.Char('Computed Name', compute='_compute_name')
    type= fields.Selection([
        ('new', 'Nuevo Proyecto'),
        ('end', 'Finalizar Proyecto'),
    ], string='Tipo', required=True)
    concept = fields.Char(string='Concept')
    created_analytic_id = fields.Many2one('account.analytic.account', string='Created Analytic Account')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Cuenta Analítica', tracking=True)
    project_count = fields.Integer(compute='_compute_analytic_count', string='Analytic Count')

    def _compute_name(self):
        for record in self:
            record.computed_name = f"Solicitud de apertura - {record.project_name}"

    def _initial_status_for(self, work_group, requester):
        """Estado de arranque del circuito según quién solicita.

        El propio Jefe de Equipo no necesita aprobarse a sí mismo: si es
        quien solicita, se salta ese paso y la solicitud queda pendiente
        directamente de la aprobación final (Director I+D). Cualquier otro
        solicitante (incluido el Administrativo del mismo grupo) pasa
        primero por la aprobación del Jefe de Equipo."""
        if work_group and requester and work_group.equip_boss == requester:
            return 'pending_review'
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

    def _compute_analytic_count(self):
        for record in self:
            record.project_count = 1 if record.created_analytic_id else 0

    @api.depends('work_group_id')
    def _compute_member_domain(self):
        for record in self:
            record.member_domain = record.work_group_id.user_ids.ids if record.work_group_id else []

    def _compute_access_url(self):
        """Genera la URL del portal para cada solicitud"""
        for record in self:
            record.access_url = f'/my/project_requests/{record.id}'

    def show_notificacion(self, title_char, text, type_char):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': type_char,
                'message': text,
                'title': title_char,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_approve_equip_boss(self):
        """Primer paso de revisión: el Jefe de Equipo del grupo da su visto
        bueno y la solicitud pasa al siguiente estado, donde queda pendiente
        de la aprobación final (Director I+D). El Administrativo no puede
        aprobar este paso."""
        for record in self:
            if not record.work_group_id._is_equip_boss_step_approver(self.env.user):
                raise UserError(_("Solo el Jefe de Equipo puede aprobar este paso."))
            if record.status != 'approved_by_equip_boss':
                continue
            if record.work_group_id and record.user_id == self.env.user:
                # Solo aplica cuando hay un grupo de trabajo con Jefe de
                # Equipo/Administrativo distinguibles: si el propio Jefe de
                # Equipo es quien solicita, ya se ha saltado este paso al
                # crear la solicitud (ver _initial_status_for), así que
                # llegar aquí como su propio solicitante solo puede ser el
                # caso del Administrativo pidiendo para sí mismo.
                raise UserError(_(
                    "No puede aprobar su propia solicitud. Debe hacerlo el "
                    "Jefe de Equipo del grupo de trabajo."
                ))
            record.status = 'pending_review'
            record._notify_requester_state(_("Aprobación del Jefe de Equipo"))
            record._notify_director_approval_pending()

    def action_approve(self):
        for record in self:
            if record.status != 'pending_review':
                raise UserError(_(
                    "Esta solicitud debe ser aprobada primero por el Jefe de Equipo."
                ))
            if record.type == 'new':
                if not record.partner_id:
                    raise UserError(_("Por favor, seleccione un cliente para el proyecto."))
                analytic_account = record.create_new_project()
                record.created_analytic_id = analytic_account
                notification_text = _("La cuenta analítica %s ha sido creada correctamente.") % record.project_name
            else:
                if not record.analytic_account_id:
                    raise UserError(_("No se encontró la cuenta analítica asociada a esta solicitud."))
                notification_text = _("La cuenta analítica %s ha sido archivada correctamente.") % record.project_name
                record.created_analytic_id = record.analytic_account_id
                record.analytic_account_id.active = False
            record.approved = True
            record.is_revised = True

        self._notify_requester_state(_("Aprobada"))
        return self.show_notificacion("¡Solicitud aprobada!", notification_text, "success")

    def action_reject(self, reason=None):
        """Rechaza la solicitud. ``reason`` es el motivo indicado por el Jefe
        de Equipo al rechazar desde el portal: se guarda en el histórico y se
        incluye en el correo al solicitante."""
        for record in self:
            record.approved = False
            record.is_revised = True
            body = _(
                "Solicitud rechazada. El solicitante puede corregirla y "
                "reenviarla sin perder el histórico."
            )
            if reason:
                body = _("Solicitud rechazada. Motivo: %s", reason)
            record.sudo().message_post(
                body=body,
                subtype_id=self.env.ref('mail.mt_note').id,
            )
        self._notify_requester_state(_("Rechazada"), note=reason)

    def action_to_revise(self):
        for record in self:
            record.is_revised = False
        self._notify_requester_state(_("En revisión"))

    def action_resubmit(self):
        """Reabre una solicitud de proyecto rechazada para que el solicitante
        la corrija (adjuntando una nueva versión de los archivos si hace
        falta) y la reenvíe a revisión, sin tener que crear una solicitud
        nueva. Conserva el histórico en el chatter."""
        for record in self:
            if record.approved or not record.is_revised:
                raise UserError(_("Solo puede reenviar solicitudes rechazadas."))
            record.is_revised = False
            restart_status = record._initial_status_for(record.work_group_id, record.user_id)
            record.status = restart_status
            record.sudo().message_post(
                body=_(
                    "El solicitante ha corregido la solicitud y la ha "
                    "reenviado a revisión."
                ),
                subtype_id=self.env.ref('mail.mt_note').id,
            )
            if restart_status == 'approved_by_equip_boss':
                record._notify_project_request_approvers()
            else:
                record._notify_director_approval_pending()

    def _notify_director_approval_pending(self):
        """Avisa al grupo aprobador (Director I+D) de que el Jefe de Equipo
        ya ha dado su visto bueno y la solicitud queda pendiente de la
        aprobación final."""
        self.ensure_one()
        group = self.env.ref('portal_requests.group_director_investigation_and_development')
        users_to_notify = group.sudo().user_ids
        portal_link = self._notify_get_portal_url()
        for admin_user in users_to_notify:
            if not admin_user.email:
                continue
            body_html = f"""
                <p>Estimado/a {admin_user.name},</p>
                <p>El Jefe de Equipo, {self.env.user.name}, ya ha dado su aprobación
                para la solicitud de proyecto <strong>{self.project_name}</strong>,
                que queda pendiente de su aprobación final.</p>
                <p><a href="{portal_link}">Ver la solicitud</a></p>
                <p>Saludos cordiales, Odoo</p>
            """
            self.env['mail.mail'].sudo().create({
                'subject': _('Solicitud de proyecto pendiente de aprobación final'),
                'email_from': self.env.company.email or 'no-reply@aicia.es',
                'email_to': admin_user.email,
                'body_html': body_html,
            }).send()

    def _notify_project_request_approvers(self, resubmit=True):
        """Avisa al Jefe de Equipo del grupo de trabajo de que tiene una
        solicitud pendiente de su aprobación: nueva (``resubmit=False``) o
        corregida y reenviada tras un rechazo. Sin grupo de trabajo, a todos
        los Jefes de Equipo (salvo Administrativos), como hasta ahora."""
        self.ensure_one()
        recipients = self.work_group_id._equip_boss_step_recipients()
        portal_link = self._notify_get_portal_url()
        if resubmit:
            subject = _('Solicitud de proyecto reenviada a revisión')
            text = (
                f"El solicitante {self.user_id.name} ha corregido la solicitud de "
                f"proyecto <strong>{self.project_name}</strong>, previamente rechazada, "
                f"y la ha reenviado a revisión."
            )
        else:
            subject = _('Solicitud de proyecto pendiente de su aprobación')
            text = (
                f"El usuario {self.user_id.name} ha creado la solicitud de proyecto "
                f"<strong>{self.project_name}</strong>, pendiente de su aprobación "
                f"como Jefe de Equipo."
            )
        for boss in recipients:
            if not boss.email:
                continue
            body_html = f"""
                <p>Estimado/a {boss.name},</p>
                <p>{text}</p>
                <p><a href="{portal_link}">Ver la solicitud</a></p>
                <p>Saludos cordiales, Odoo</p>
            """
            self.env['mail.mail'].sudo().create({
                'subject': subject,
                'email_from': self.env.company.email or 'no-reply@aicia.es',
                'email_to': boss.email,
                'body_html': body_html,
            }).send()

    def create_new_project(self):
        # Buscar el plan analítico AICIA
        plan = self.env['account.analytic.plan'].sudo().search([('name', '=', 'AICIA')], limit=1)
        if not plan:
            raise UserError(_("No se encontró el plan analítico 'AICIA'. Por favor, créelo primero."))

        # Crear la cuenta analítica
        analytic_account = self.env['account.analytic.account'].sudo().create({
            'name': self.project_name,
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'plan_id': plan.id,
            'work_group_id': self.work_group_id.id if self.work_group_id else False,
            'responsible_id': self.user_id.id,
            'member_ids': [(6, 0, self.member_ids.ids)],
        })

        # Adjuntar el contrato firmado si existe
        if self.signed_contract:
            self.env['ir.attachment'].sudo().create({
                'name': self.signed_contract_filename or 'contrato_firmado.pdf',
                'type': 'binary',
                'datas': self.signed_contract,
                'res_model': 'account.analytic.account',
                'res_id': analytic_account.id,
            })

        # Adjuntar el presupuesto si existe
        if self.budget_file:
            self.env['ir.attachment'].sudo().create({
                'name': self.budget_file_filename or 'presupuesto.pdf',
                'type': 'binary',
                'datas': self.budget_file,
                'res_model': 'account.analytic.account',
                'res_id': analytic_account.id,
            })

        return analytic_account

    def action_view_analytic(self):
        self.ensure_one()
        if not self.created_analytic_id:
            return

        action = {
            "type": "ir.actions.act_window",
            "res_model": "account.analytic.account",
            "view_mode": "form",
            "res_id": self.created_analytic_id.id,
            "target": "current",
        }
        return action
