from odoo import models, fields, api

class PortalProjectRequest(models.Model):
    _name = 'portal.project.request'
    _description = 'Portal Project Request'

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

    def action_approve(self):
        for record in self:
            record.approved = True
            record.is_revised = True

    def action_reject(self):
        for record in self:
            record.approved = False
            record.is_revised = True

    def action_to_revise(self):
        for record in self:
            record.is_revised = False
