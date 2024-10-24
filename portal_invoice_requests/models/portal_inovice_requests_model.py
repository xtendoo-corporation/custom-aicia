from odoo import models, fields, api

class PortalInvoiceRequest(models.Model):
    _name = 'portal.invoice.request'
    _description = 'Portal Invoice Request'

    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True)
    partner_id = fields.Many2one('res.partner', string='Client', required=True)
    amount = fields.Float(string='Amount', required=True)
    notes = fields.Text(string='Invoice Concept')
    move_type = fields.Selection([
        ('out_invoice', 'Customer Invoice'),
        ('out_refund', 'Customer Credit Note'),
    ], string='Type', default='out_invoice', required=True)
    date = fields.Date(string='Date')
    l10n_es_edi_facturae_reason_code = fields.Selection(
        selection=lambda self: self.env['account.move']._fields[
            'l10n_es_edi_facturae_reason_code']._description_selection(self.env),
        string='Spanish Facturae EDI Reason Code',
        default='10'
    )
