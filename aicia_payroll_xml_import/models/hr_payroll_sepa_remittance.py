from odoo import models, fields


class HrPayrollSepaRemittance(models.Model):
    _name = "hr.payroll.sepa.remittance"
    _description = "Remesa SEPA Nóminas"

    name = fields.Char()
    msg_id = fields.Char(index=True)
    pmt_inf_id = fields.Char()

    date_execution = fields.Date()
    total_amount = fields.Float()

    state = fields.Selection([
        ("draft", "Borrador"),
        ("done", "Procesado"),
        ("error", "Error"),
    ], default="draft")

    move_id = fields.Many2one("account.move", readonly=True)

    log = fields.Text()

    line_ids = fields.One2many(
        "hr.payroll.sepa.remittance.line",
        "remittance_id"
    )


class HrPayrollSepaRemittanceLine(models.Model):
    _name = "hr.payroll.sepa.remittance.line"
    _description = "Línea Remesa SEPA Nóminas"

    remittance_id = fields.Many2one(
        "hr.payroll.sepa.remittance",
        ondelete="cascade"
    )

    employee_id = fields.Many2one("hr.employee")
    partner_id = fields.Many2one("res.partner")

    name = fields.Char()
    iban = fields.Char()
    end_to_end_id = fields.Char(index=True)

    amount = fields.Float()

    move_line_id = fields.Many2one("account.move.line", readonly=True)
