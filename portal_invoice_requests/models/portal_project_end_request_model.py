from odoo import models, fields, api


class PortalProjectEndRequest(models.Model):
    _name = 'portal.project.end.request'
    _description = 'Portal Project End Request'

    project_id = fields.Many2one('res.company', string='Project', required=True)#filtro por empresas permitidas por el usuario
    project_end_date = fields.Date(string='Project End Date', required=True)
    concept = fields.Char(string='Concept', required=True)
