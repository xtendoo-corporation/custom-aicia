from odoo import models, fields, api, _

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
    approved = fields.Boolean(string='Approved', default=False)
    is_revised = fields.Boolean(string='Is revised', default=False, store=True)
    invoice_created = fields.Many2one('account.move', string='Invoice Created')
    invoice_to_refund = fields.Many2one('account.move', string='Invoice to Refund')

    invoice_count = fields.Integer(default=1, string='Invoice Count')

    def action_approve(self):
        for record in self:
            record.approved = True
            record.is_revised = True
            record.create_invoice()

    def action_reject(self):
        for record in self:
            record.approved = False
            record.is_revised = True

    def action_to_revise(self):
        for record in self:
            record.is_revised = False

    def create_invoice(self):
        print("*" * 100)
        if self.move_type == 'out_invoice':
            print("Factura")
            invoice = self.env['account.move'].sudo().create({
                'partner_id': self.partner_id.id,
                'company_id': self.company_id.id,
                'invoice_date': self.date,
                'invoice_origin': False,
                'amount_total': self.amount,
                'move_type': 'out_invoice',
                'invoice_line_ids': [
                    (0, 0, {
                        'name': self.notes,
                        'quantity': 1.0,
                        'price_unit': self.amount,
                    })
                ],
            })
        else:
            print("Factura rectificativa")
            print("self.l10n_",self.l10n_es_edi_facturae_reason_code)
            options = self.env['account.move']._fields['l10n_es_edi_facturae_reason_code']._description_selection(self.env)
            reason = _("Reversión de %s") % self.invoice_to_refund.name
            for value, label in options:
                if value == self.l10n_es_edi_facturae_reason_code:
                    reason =reason +" "+ label
                    break

            invoice = self.env['account.move'].sudo().create({
                'move_type': 'out_refund',
                'partner_id': self.partner_id.id,
                'company_id': self.company_id.id,
                'invoice_date': self.date,
                'ref': reason,
                'invoice_line_ids': [
                    (0, 0, {
                        'name': self.notes,
                        'quantity': 1.0,
                        'price_unit': self.amount,
                    })
                ],
            })
        invoice.sudo().action_post()
        self.invoice_created = invoice.id

    def action_view_invoice(self):
        self.ensure_one()
        invoice_ids = self.invoice_created.ids
        action = {
            "res_model": "account.move",
            "type": "ir.actions.act_window",
        }
        if len(invoice_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": invoice_ids[0],
                }
            )
        else:
            action.update(
                {
                    "name": "Fctura",
                    "domain": [("id", "in", invoice_ids)],
                    "view_mode": "tree,form",
                }
            )
        return action

