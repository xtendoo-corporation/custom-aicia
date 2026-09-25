# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


class AccountAnalyticAccount(models.Model):
    """Relación inversa de investigadores (reparto por empleado) en el proyecto."""

    _inherit = "account.analytic.account"

    analytic_line_ids = fields.One2many(
        comodel_name="aicia.employee.analytic.line",
        inverse_name="analytic_account_id",
        string="Investigadores",
    )
    researcher_count = fields.Integer(
        string="Nº investigadores",
        compute="_compute_researcher_count",
    )

    @api.depends("analytic_line_ids")
    def _compute_researcher_count(self):
        for record in self:
            record.researcher_count = len(record.analytic_line_ids)

    def action_open_researchers(self):
        self.ensure_one()
        return {
            "name": _("Investigadores"),
            "type": "ir.actions.act_window",
            "res_model": "aicia.employee.analytic.line",
            "view_mode": "list",
            "domain": [("analytic_account_id", "=", self.id)],
            "context": {
                "default_analytic_account_id": self.id,
                "search_default_analytic_account_id": self.id,
            },
            "target": "current",
        }
