"""Extensión de account.move para marcar asientos de distribución directa."""
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_cash_distribution_move = fields.Boolean(
        string='Asiento de distribución de cobros',
        default=False,
        copy=False,
    )
    distribution_partial_reconcile_id = fields.Many2one(
        'account.partial.reconcile',
        string='Conciliación origen',
        copy=False,
        ondelete='set null',
    )
    distribution_payment_id = fields.Many2one(
        'account.payment',
        string='Pago origen',
        copy=False,
        ondelete='set null',
    )
    distribution_source_analytic_ids = fields.Many2many(
        'account.analytic.account',
        'aicia_dist_move_source_analytic_rel',
        'distribution_move_id',
        'analytic_id',
        string='Analíticas Origen',
        copy=False,
    )
    distribution_applied_plan_ids = fields.Many2many(
        'aicia.distribution.plan',
        'aicia_dist_move_plan_rel',
        'distribution_move_id',
        'plan_id',
        string='Planes aplicados',
        copy=False,
    )

    @api.model
    def _register_hook(self, *args, **kwargs):
        """Normaliza datos legacy borrando relaciones huérfanas del antiguo modelo."""
        res = super()._register_hook(*args, **kwargs)
        cr = self.env.cr
        cr.execute(
            """
            DELETE FROM aicia_dist_move_source_analytic_rel rel
            WHERE NOT EXISTS (
                SELECT 1 FROM account_move am WHERE am.id = rel.distribution_move_id
            )
            """
        )
        cr.execute(
            """
            DELETE FROM aicia_dist_move_plan_rel rel
            WHERE NOT EXISTS (
                SELECT 1 FROM account_move am WHERE am.id = rel.distribution_move_id
            )
            """
        )
        return res

