from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cash_distribution_journal_id = fields.Many2one(
        related='company_id.cash_distribution_journal_id',
        string='Distribution Journal',
        readonly=False,
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]"
    )
    cash_distribution_active = fields.Boolean(
        related='company_id.cash_distribution_active',
        string='Active Distribution',
        readonly=False
    )

