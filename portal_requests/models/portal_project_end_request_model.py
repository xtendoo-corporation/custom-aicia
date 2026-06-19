from odoo import models, fields, api


class PortalProjectEndRequest(models.Model):
    _name = 'portal.project.end.request'
    _description = 'Portal Project End Request'

    company_id = fields.Many2one('res.company', string='Company', required=True)
    project_end_date = fields.Date(string='Project End Date', required=True)
    concept = fields.Char(string='Concept', required=True)
