from odoo import models, fields, api


class PortalHrExpensiveRequest(models.Model):
    _name = 'portal.hr.expensive.request'
    _description = 'Portal HR Expensive Request'

    name = fields.Char(string='Expensive Name', required=True)
    product_id = fields.Many2one('product.product', string='Product', required=True)
    total_amount_currency = fields.Float(string='Total Amount Currency', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    # payment_mode = fields.Selection(['employee', 'company'], string='Payment Mode', required=True)
    date = fields.Date(string='Date', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True)


