from odoo import models, fields, api

class PortalProjectRequest(models.Model):
    _name = 'portal.project.request'
    _description = 'Portal Project Request'

    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    project_name = fields.Char(string='Project Name')
    signed_contract = fields.Binary(string="Signed Contract", attachment=True)
    budget_file = fields.Binary(string="Budget", attachment=True)
    signed_contract_filename = fields.Char(string="Signed Contract Filename")
    budget_file_filename = fields.Char(string="Budget Filename")
