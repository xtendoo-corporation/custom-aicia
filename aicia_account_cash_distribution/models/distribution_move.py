from odoo import models, fields, api

class AiciaDistributionMove(models.Model):
    _name = 'aicia.distribution.move'
    _description = 'AICIA Distribution Log'
    _check_company_auto = True

    name = fields.Char(required=True, default='/')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    partial_reconcile_id = fields.Many2one('account.partial.reconcile', string='Reconciliation', required=True, ondelete='cascade')
    move_id = fields.Many2one('account.move', string='Journal Entry', required=True, check_company=True)
    state = fields.Selection(related='move_id.state', store=True)

    amount_total = fields.Monetary(string='Total Amount', currency_field='currency_id')
    currency_id = fields.Many2one(related='move_id.currency_id')

    @api.constrains('partial_reconcile_id', 'move_id')
    def _check_unique_link(self):
        # Ensure one-to-one or one-to-many as needed
        pass

