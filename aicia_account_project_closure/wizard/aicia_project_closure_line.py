# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class AiciaProjectClosureLine(models.TransientModel):
    """Línea de previsualización del cierre AICIA por proyecto."""

    _name = "aicia.project.closure.line"
    _description = "Línea de Cierre AICIA por Proyecto"

    wizard_id = fields.Many2one(
        comodel_name="aicia.project.closure.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    analytic_account_id = fields.Many2one(
        comodel_name="account.analytic.account",
        string="Cuenta Analítica (Proyecto)",
        required=True,
        readonly=True,
    )
    income = fields.Monetary(
        string="Ingresos",
        readonly=True,
        currency_field="currency_id",
        help="Suma neta de apuntes en cuentas con prefijo de ingresos (ej: 7xx).",
    )
    expense = fields.Monetary(
        string="Gastos",
        readonly=True,
        currency_field="currency_id",
        help="Suma neta de apuntes en cuentas con prefijo de gastos (ej: 6xx).",
    )
    result = fields.Monetary(
        string="Resultado",
        compute="_compute_result",
        store=True,
        currency_field="currency_id",
        help="Resultado = Ingresos - Gastos. Positivo = beneficio, negativo = pérdida.",
    )
    target_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta Destino",
        compute="_compute_result",
        store=True,
        help="Cuenta 130 (beneficio) o 131 (pérdida) según el resultado.",
    )
    provision_amount = fields.Monetary(
        string="Importe Provisión",
        compute="_compute_result",
        store=True,
        currency_field="currency_id",
        help="Importe absoluto del resultado, a contabilizar contra 294.",
    )
    has_existing_entries = fields.Boolean(
        string="Duplicado",
        compute="_compute_has_existing_entries",
        help="Indica si ya existen asientos de cierre AICIA para este proyecto y periodo.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="wizard_id.currency_id",
    )

    @api.depends("income", "expense")
    def _compute_result(self):
        for line in self:
            line.result = line.income - line.expense
            if line.result > 0:
                line.target_account_id = line.wizard_id.account_profit_id
            elif line.result < 0:
                line.target_account_id = line.wizard_id.account_loss_id
            else:
                line.target_account_id = False
            line.provision_amount = abs(line.result)

    @api.depends("analytic_account_id")
    def _compute_has_existing_entries(self):
        AccountMove = self.env["account.move"]
        for line in self:
            if not line.wizard_id or not line.analytic_account_id:
                line.has_existing_entries = False
                continue
            closure_ref = self._build_closure_ref(
                line.analytic_account_id.id,
                line.wizard_id.date_from,
                line.wizard_id.date_to,
            )
            existing = AccountMove.search_count(
                [
                    ("aicia_closure_ref", "=", closure_ref),
                    ("state", "!=", "cancel"),
                    ("company_id", "=", line.wizard_id.company_id.id),
                ],
                limit=1,
            )
            line.has_existing_entries = existing > 0

    @staticmethod
    def _build_closure_ref(analytic_id, date_from, date_to):
        """Genera la clave única de cierre AICIA."""
        return f"AICIA-{analytic_id}-{date_from}-{date_to}"

