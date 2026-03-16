from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    cash_distribution_journal_id = fields.Many2one('account.journal', string='Cash Distribution Journal', check_company=True)
    cash_distribution_active = fields.Boolean(string='Enable Cash Distribution', default=False)
