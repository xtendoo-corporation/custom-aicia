# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountPaymentSplitTemplateLine(models.Model):
    """Línea de reparto dentro de una plantilla.

    Cada línea define:
    - Un porcentaje del reparto.
    - La cuenta contable destino (HABER/credit).
    - Opcionalmente, una cuenta analítica para el apunte.
    """

    _name = "account.payment.split.template.line"
    _description = "Línea de Plantilla de Reparto"
    _order = "sequence, id"

    template_id = fields.Many2one(
        comodel_name="account.payment.split.template",
        string="Plantilla",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(
        string="Secuencia",
        default=10,
    )
    name = fields.Char(
        string="Descripción",
        required=True,
    )
    credit_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta Destino (Haber)",
        required=True,
        check_company=True,
        help="Cuenta que se abona (CRÉDITO) con la parte correspondiente.",
    )
    percentage = fields.Float(
        string="Porcentaje (%)",
        required=True,
        help="Porcentaje de reparto asignado a esta línea.",
    )
    analytic_account_id = fields.Many2one(
        comodel_name="account.analytic.account",
        string="Cuenta Analítica",
        help="Cuenta analítica opcional para el apunte generado.",
    )
    analytic_distribution = fields.Json(
        string="Distribución Analítica",
        help="Distribución analítica en formato JSON (alternativa al campo simple).",
    )
    company_id = fields.Many2one(
        related="template_id.company_id",
        store=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains("percentage")
    def _check_percentage_non_negative(self):
        for line in self:
            if line.percentage < 0:
                raise ValidationError(
                    _(
                        "El porcentaje no puede ser negativo. "
                        "Línea: %(name)s, Valor: %(pct)s%%",
                        name=line.name,
                        pct=line.percentage,
                    )
                )
