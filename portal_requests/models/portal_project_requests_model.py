from odoo import models, fields, api , _
from odoo.exceptions import UserError

class PortalProjectRequest(models.Model):
    _name = 'portal.project.request'
    _description = 'Portal Project Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, tracking=True)
    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', tracking=True)
    project_id = fields.Many2one('project.project', string='Project', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Client', tracking=True)
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    project_name = fields.Char(string='Project Name')
    signed_contract = fields.Binary(string="Signed Contract", attachment=True)
    budget_file = fields.Binary(string="Budget", attachment=True)
    signed_contract_filename = fields.Char(string="Signed Contract Filename")
    budget_file_filename = fields.Char(string="Budget Filename")
    approved = fields.Boolean(string='Approved', default=False)
    is_revised = fields.Boolean(string='Is revised', default=False, store=True)
    type= fields.Selection([
        ('new', 'Nuevo Proyecto'),
        ('end', 'Finalizar Proyecto'),
    ], string='Tipo', required=True)
    concept = fields.Char(string='Concept')
    created_project_id = fields.Many2one('project.project', string='Created Project')
    project_count = fields.Integer(default=1, string='Project Count')

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
                record.created_project_id = record.create_new_project()
                notification_text = _("El proyecto %s ha sido creado correctamente.") % record.project_name
            else:
                notification_text = _("El proyecto %s ha sido finalizado correctamente.") % record.project_name
                record.project_id.active = False
                record.project_id.date = self.date_end
                record.created_project_id = record.project_id
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
        # Crear el proyecto
        project = self.env['project.project'].sudo().create({
            'name': self.project_name,
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'work_group_id': self.work_group_id.id,
            'date_start': self.date_start,
            'date': self.date_end,
            'user_id': self.user_id.id
        })

        # Adjuntar el contrato firmado si existe
        if self.signed_contract:
            self.env['ir.attachment'].sudo().create({
                'name': self.signed_contract_filename or 'contrato_firmado.pdf',
                'type': 'binary',
                'datas': self.signed_contract,
                'res_model': 'project.project',
                'res_id': project.id,
            })

        # Adjuntar el presupuesto si existe
        if self.budget_file:
            self.env['ir.attachment'].sudo().create({
                'name': self.budget_file_filename or 'presupuesto.pdf',
                'type': 'binary',
                'datas': self.budget_file,
                'res_model': 'project.project',
                'res_id': project.id,
            })

        return project

    def action_view_project(self):
        self.ensure_one()
        project_ids = self.created_project_id.ids
        action = {
            "res_model": "project.project",
            "type": "ir.actions.act_window",
        }
        if len(project_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": project_ids[0],
                }
            )
        else:
            action.update(
                {
                    "name": "Proyecto",
                    "domain": [("id", "in", project_ids)],
                    "view_mode": "tree,form",
                }
            )
        return action
