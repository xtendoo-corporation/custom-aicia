from odoo import models, fields, api , _
from odoo.exceptions import UserError

class PortalProjectRequest(models.Model):
    _name = 'portal.project.request'
    _description = 'Portal Project Request'
    _rec_name = 'computed_name'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, tracking=True)
    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', tracking=True)
    partner_id_char = fields.Char(string='Cliente', store=True)
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    project_name = fields.Char(string='Project Name')
    signed_contract = fields.Binary(string="Signed Contract", attachment=True)
    budget_file = fields.Binary(string="Budget", attachment=True)
    signed_contract_filename = fields.Char(string="Signed Contract Filename")
    budget_file_filename = fields.Char(string="Budget Filename")
    approved = fields.Boolean(string='Approved', default=False)
    is_revised = fields.Boolean(string='Is revised', default=False, store=True)
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

    def _compute_analytic_count(self):
        for record in self:
            record.project_count = 1 if record.created_analytic_id else 0

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

    def action_approve(self):
        for record in self:
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

        return self.show_notificacion("¡Solicitud aprobada!", notification_text, "success")

    def action_reject(self):
        for record in self:
            record.approved = False
            record.is_revised = True

    def action_to_revise(self):
        for record in self:
            record.is_revised = False

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
