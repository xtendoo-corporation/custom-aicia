from odoo import models, fields, api

class AiciaDistributionRule(models.Model):
    _name = 'aicia.distribution.rule'
    _description = 'AICIA Distribution Rule'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    percentage = fields.Float(string='Percentage', required=True, digits=(16, 2))
    type = fields.Selection([
        ('source', 'Source Analytic'),
        ('fixed', 'Fixed Analytic')
    ], required=True, default='source', help="Type of distribution: Source (from Invoice Line) or Fixed (specific account)")

    # Matching criteria (optional)
    source_analytic_account_ids = fields.Many2many('account.analytic.account', string='Source Analytic Accounts', check_company=True)

    # Destination
    destination_analytic_account_id = fields.Many2one('account.analytic.account', string='Destination Analytic Account', check_company=True)

    # Financial Accounts for the move
    debit_account_id = fields.Many2one('account.account', string='Debit Account', check_company=True, required=True)
    credit_account_id = fields.Many2one('account.account', string='Credit Account', check_company=True, required=True)

    active = fields.Boolean(default=True)

