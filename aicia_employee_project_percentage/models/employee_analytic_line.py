# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class EmployeeAnalyticLine(models.Model):
    """Línea de reparto analítico por empleado.

    Almacena la relación entre un empleado y una cuenta analítica,
    junto con el porcentaje de reparto asignado (valor libre, sin restricción de suma).
    """

    _name = "aicia.employee.analytic.line"
    _description = "Línea de reparto analítico de empleado"
    _order = "employee_id, sequence"

    sequence = fields.Integer(
        string="Secuencia",
        default=10,
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Empleado",
        required=True,
        ondelete="cascade",
        index=True,
    )
    analytic_account_id = fields.Many2one(
        comodel_name="account.analytic.account",
        string="Cuenta analítica",
        required=True,
        ondelete="restrict",
    )
    percentage = fields.Float(
        string="Porcentaje (%)",
        digits=(5, 2),
        default=0.0,
    )
    date_start = fields.Date(
        string="Fecha de inicio",
    )

