from odoo import models, fields, api

class PortalPurchaseOrderController(models.Model):
    _name = 'portal.purchase.order.request'
    _description = 'Portal Purchase Order Request'

    company_id = fields.Many2one('res.company', string='Company', required=True)
    partner_id = fields.Many2one('res.partner', string='Supplier', required=True)
    concept = fields.Text(string='Purchase Order Concept', required=True)

