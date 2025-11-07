# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = ["account.move"]

    # Campo Many2one que relaciona con cuenta analítica
    analytic_distribution = fields.Json(
        inverse="_inverse_analytic_distribution",
    )
    analytic_precision = fields.Integer(
        store=False,
        default=lambda self: self.env["decimal.precision"].precision_get(
            "Percentage Analytic"
        ),
    )

    @api.onchange("analytic_distribution")
    def _onchange_analytic_distribution(self):
        """Actualiza analytic_distribution en todas las líneas del movimiento"""
        if self.analytic_distribution:
            for line in self.line_ids:
                line.analytic_distribution = self.analytic_distribution
        else:
            for line in self.line_ids:
                line.analytic_distribution = False

