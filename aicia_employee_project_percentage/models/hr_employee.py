# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


class HrEmployee(models.Model):
    """Herencia de hr.employee para añadir el reparto de cuentas analíticas."""

    _inherit = "hr.employee"

    analytic_line_ids = fields.One2many(
        comodel_name="aicia.employee.analytic.line",
        inverse_name="employee_id",
        string="Reparto analítico",
    )
    analytic_line_count = fields.Integer(
        string="Nº proyectos",
        compute="_compute_analytic_line_count",
    )

    @api.depends("analytic_line_ids")
    def _compute_analytic_line_count(self):
        for record in self:
            record.analytic_line_count = len(record.analytic_line_ids)

    def action_open_analytic_lines(self):
        self.ensure_one()
        return {
            "name": _("Reparto analítico"),
            "type": "ir.actions.act_window",
            "res_model": "aicia.employee.analytic.line",
            "view_mode": "list",
            "domain": [("employee_id", "=", self.id)],
            "context": {
                "default_employee_id": self.id,
                "search_default_employee_id": self.id,
            },
            "target": "current",
        }

