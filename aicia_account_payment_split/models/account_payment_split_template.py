# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

import logging

_logger = logging.getLogger(__name__)


class AccountPaymentSplitTemplate(models.Model):
    """Plantilla de reparto de cobros.

    Define cómo se distribuye un porcentaje del importe cobrado en un asiento
    contable adicional (tipo 'entry').  La plantilla contiene:
    - Un diario destino para el asiento de reparto.
    - Una cuenta de cargo (debit_account_id) desde la que «sale» el importe.
    - Líneas de abono (credit) con porcentaje y cuenta destino.
    - Configuración del modo de cálculo (lines_sum_to_100 vs lines_sum_to_base).
    """

    _name = "account.payment.split.template"
    _description = "Plantilla de Reparto de Cobros"
    _order = "priority desc, name"
    _check_company_auto = True

    # ------------------------------------------------------------------
    # Campos
    # ------------------------------------------------------------------
    name = fields.Char(
        string="Nombre",
        required=True,
        translate=True,
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Diario de Reparto",
        required=True,
        check_company=True,
        domain="[('type', '=', 'general')]",
        help="Diario donde se creará el asiento de reparto.",
    )
    debit_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta Origen (Debe)",
        required=True,
        check_company=True,
        help="Cuenta de clearing/origen que se carga (DEBE) con el importe total a repartir.",
    )
    default_for_analytic_account_id = fields.Many2one(
        comodel_name="account.analytic.account",
        string="Cuenta Analítica por Defecto",
        help="Si se asigna, esta plantilla se sugerirá automáticamente "
        "cuando la factura del pago tenga esta analítica como principal.",
    )
    priority = fields.Integer(
        string="Prioridad",
        default=10,
        help="Mayor valor = mayor preferencia al sugerir automáticamente.",
    )
    split_base_mode = fields.Selection(
        selection=[
            ("lines_sum_to_100", "Líneas suman 100% (del % base)"),
            ("lines_sum_to_base", "Líneas suman el % base directamente"),
        ],
        string="Modo de Cálculo",
        required=True,
        default="lines_sum_to_100",
        help=(
            "• lines_sum_to_100: las líneas suman 100%%. El importe a repartir "
            "es split_base_percentage%% del pago.\n"
            "• lines_sum_to_base: las líneas suman directamente split_base_percentage "
            "(ej. 4+3+3 = 10%%)."
        ),
    )
    split_base_percentage = fields.Float(
        string="Porcentaje Base (%)",
        required=True,
        default=10.0,
        help="Porcentaje del pago que se reparte.  Ej: 10.0 = 10%%.",
    )
    split_line_ids = fields.One2many(
        comodel_name="account.payment.split.template.line",
        inverse_name="template_id",
        string="Líneas de Reparto",
        copy=True,
    )

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains("split_base_percentage")
    def _check_split_base_percentage(self):
        for tpl in self:
            if tpl.split_base_percentage < 0 or tpl.split_base_percentage > 100:
                raise ValidationError(
                    _(
                        "El porcentaje base debe estar entre 0 y 100. "
                        "Valor actual: %(pct)s%%",
                        pct=tpl.split_base_percentage,
                    )
                )

    @api.constrains("split_line_ids", "split_base_mode", "split_base_percentage")
    def _check_split_lines_percentage(self):
        """Valida que los porcentajes de las líneas sean coherentes según el modo."""
        for tpl in self:
            if not tpl.split_line_ids:
                continue
            total = sum(tpl.split_line_ids.mapped("percentage"))
            if tpl.split_base_mode == "lines_sum_to_100":
                # Las líneas deben sumar 100 (tolerancia 0.01)
                if abs(total - 100.0) > 0.01:
                    raise ValidationError(
                        _(
                            "En modo 'Líneas suman 100%%', la suma de porcentajes "
                            "de las líneas debe ser 100%%. Suma actual: %(total)s%%",
                            total=total,
                        )
                    )
            elif tpl.split_base_mode == "lines_sum_to_base":
                # Las líneas deben sumar exactamente split_base_percentage
                if abs(total - tpl.split_base_percentage) > 0.01:
                    raise ValidationError(
                        _(
                            "En modo 'Líneas suman el %% base', la suma de porcentajes "
                            "de las líneas debe ser %(base)s%%. Suma actual: %(total)s%%",
                            base=tpl.split_base_percentage,
                            total=total,
                        )
                    )
