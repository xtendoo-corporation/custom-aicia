from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models


class AiciaPayrollImportLine(models.Model):
    _name = "aicia.payroll.import.line"
    _description = "Línea de importación de nómina AICIA"
    _order = "sequence, id"

    import_id = fields.Many2one("aicia.payroll.import", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    payment_date = fields.Date(required=True)
    liquid = fields.Monetary(currency_field="currency_id")
    cont = fields.Integer()
    nif = fields.Char()
    employee_name = fields.Char(required=True)
    irpf = fields.Monetary(currency_field="currency_id")
    ss_employee = fields.Monetary(currency_field="currency_id")
    ss_company = fields.Monetary(currency_field="currency_id")
    diet = fields.Monetary(currency_field="currency_id")
    km = fields.Monetary(currency_field="currency_id")
    bonus = fields.Monetary(currency_field="currency_id")
    deduction = fields.Monetary(currency_field="currency_id")
    management_cost = fields.Monetary(currency_field="currency_id")
    ct_cost = fields.Monetary(currency_field="currency_id")
    travel_cost = fields.Monetary(currency_field="currency_id")
    advances = fields.Monetary(currency_field="currency_id")
    gross_salary = fields.Monetary(compute="_compute_gross_salary", currency_field="currency_id", store=True)
    raw_data = fields.Text()
    currency_id = fields.Many2one(related="import_id.currency_id", store=True)

    @api.depends("liquid", "irpf", "ss_employee", "deduction", "advances")
    def _compute_gross_salary(self):
        for line in self:
            gross_salary = (
                Decimal(str(line.liquid or 0.0))
                + Decimal(str(line.irpf or 0.0))
                + Decimal(str(line.ss_employee or 0.0))
                + Decimal(str(line.deduction or 0.0))
                + Decimal(str(line.advances or 0.0))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            line.gross_salary = float(gross_salary)
