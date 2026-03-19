from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cash_distribution_active = fields.Boolean(
        related='company_id.cash_distribution_active',
        string='Activar Distribución de Cobros',
        readonly=False,
    )
    cash_distribution_journal_id = fields.Many2one(
        related='company_id.cash_distribution_journal_id',
        string='Diario de Distribución',
        readonly=False,
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]",
    )
    cash_distribution_receiver_analytic_id = fields.Many2one(
        related='company_id.cash_distribution_receiver_analytic_id',
        string='Analítica Receptora AICIA (por defecto)',
        readonly=False,
    )

