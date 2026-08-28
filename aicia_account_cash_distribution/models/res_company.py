from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    cash_distribution_journal_id = fields.Many2one(
        'account.journal', string='Diario de Distribución',
        check_company=True,
        domain="[('type', '=', 'general')]",
    )
    cash_distribution_receiver_analytic_id = fields.Many2one(
        'account.analytic.account',
        string='Analítica Receptora AICIA (por defecto)',
        help="Proyecto AICIA receptor de los repartos cuando el plan "
             "no define una analítica receptora propia.",
    )
