# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class HrEmployee(models.Model):
    """Herencia de hr.employee para añadir el reparto de cuentas analíticas."""

    _inherit = "hr.employee"

    analytic_line_ids = fields.One2many(
        comodel_name="aicia.employee.analytic.line",
        inverse_name="employee_id",
        string="Reparto analítico",
    )

