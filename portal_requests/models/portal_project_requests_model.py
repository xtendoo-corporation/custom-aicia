from odoo import models, fields, api , _
from odoo.exceptions import UserError

class PortalProjectRequest(models.Model):
    _name = 'portal.project.request'
    _description = 'Portal Project Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True)
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
    created_company_id = fields.Many2one('res.company', string='Created Company')
    company_count = fields.Integer(default=1, string='Invoice Count')

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
                record.created_company_id = record.create_new_company()
                notification_text = _("El proyecto %s ha sido creado correctamente.") % record.project_name
            else:
                notification_text = _("El proyecto %s ha sido finalizado correctamente.") % record.project_name
                record.company_id.active = False
                record.created_company_id = record.company_id
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

    def create_new_company(self):
        country = self.env['res.country'].search([('name', '=', 'España')],
                                                 limit=1)  # Cambia 'España' por el país que necesitas
        if not country:
            raise UserError("No se encontró el país especificado.")

        partner_new = self.env['res.partner'].with_context(default_parent_id=False).sudo().create({
            'name': self.project_name,
            'company_type': 'company',
            'is_company': True,
            'country_id': country.id,
        })



        company = self.env['res.company'].sudo().create({
            'name': self.project_name,
            'partner_id': partner_new.id,
            'parent_id': self.company_id.id,
            'country_id': country.id,
            'currency_id': self.env.user.company_id.currency_id.id,  # Esto asegura que se asigna una moneda válida
        })
        return company

    def action_view_company(self):
        self.ensure_one()
        company_ids = self.created_company_id.ids
        action = {
            "res_model": "res.company",
            "type": "ir.actions.act_window",
        }
        if len(company_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": company_ids[0],
                }
            )
        else:
            action.update(
                {
                    "name": "Factura",
                    "domain": [("id", "in", company_ids)],
                    "view_mode": "tree,form",
                }
            )
        return action


