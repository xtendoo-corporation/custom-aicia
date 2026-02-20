# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountPaymentSplitLog(models.Model):
    """Log de auditoría para repartos de cobro.

    Registra cada reparto generado para garantizar trazabilidad y
    evitar duplicados.  La constraint SQL unique garantiza que no
    se creen dos repartos para el mismo pago + plantilla.
    """

    _name = "account.payment.split.log"
    _description = "Log de Reparto de Cobro"
    _order = "date desc, id desc"
    _check_company_auto = True

    payment_id = fields.Many2one(
        comodel_name="account.payment",
        string="Pago",
        required=True,
        ondelete="cascade",
        index=True,
    )
    invoice_ids = fields.Many2many(
        comodel_name="account.move",
        string="Facturas",
        relation="split_log_invoice_rel",
        column1="log_id",
        column2="invoice_id",
        help="Facturas reconciliadas con el pago al momento del reparto.",
    )
    split_move_id = fields.Many2one(
        comodel_name="account.move",
        string="Asiento de Reparto",
        required=True,
        ondelete="restrict",
        index=True,
    )
    template_id = fields.Many2one(
        comodel_name="account.payment.split.template",
        string="Plantilla Utilizada",
        required=True,
        ondelete="restrict",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda del Pago",
        required=True,
    )
    amount_base_currency = fields.Monetary(
        string="Importe Repartido (Moneda Pago)",
        currency_field="currency_id",
    )
    amount_base_company = fields.Monetary(
        string="Importe Repartido (Moneda Compañía)",
        currency_field="company_currency_id",
    )
    company_currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="company_id.currency_id",
        string="Moneda Compañía",
    )
    date = fields.Date(
        string="Fecha",
        required=True,
    )
    state = fields.Selection(
        selection=[
            ("posted", "Publicado"),
            ("reversed", "Revertido"),
        ],
        string="Estado",
        default="posted",
        required=True,
    )

    # ------------------------------------------------------------------
    # Constraint SQL: unicidad payment + template
    # ------------------------------------------------------------------
    _payment_template_unique = models.Constraint(
        "UNIQUE(payment_id, template_id)",
        "Ya existe un reparto para este pago con esta plantilla.",
    )
