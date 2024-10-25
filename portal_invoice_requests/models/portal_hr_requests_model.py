from odoo import models, fields, api

class PortalHrRequest(models.Model):
    _name = 'portal.hr.request'
    _description = 'Portal HR Request'

    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True)
    condition = fields.Char(string='Condition', required=True)
