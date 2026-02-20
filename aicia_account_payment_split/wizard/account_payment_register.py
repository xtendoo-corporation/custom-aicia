# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class AccountPaymentRegister(models.TransientModel):
    """Extensión del wizard 'Registrar Pago' para incluir la plantilla
    de reparto.  El campo se propaga al account.payment creado."""

    _inherit = "account.payment.register"

    split_template_id = fields.Many2one(
        comodel_name="account.payment.split.template",
        string="Plantilla de Reparto",
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        check_company=True,
        help="Seleccione la plantilla de reparto a aplicar al pago.",
    )

    # ------------------------------------------------------------------
    # Sugerencia automática
    # ------------------------------------------------------------------
    @api.depends("line_ids", "company_id")
    def _compute_from_lines(self):
        """Extiende el compute para sugerir la plantilla de reparto."""
        res = super()._compute_from_lines()
        for wizard in self:
            if wizard.split_template_id:
                continue
            # Intentar sugerir plantilla basándose en la analítica de las facturas
            invoices = wizard.line_ids.move_id.filtered(
                lambda m: m.move_type in ("out_invoice", "out_refund")
            )
            if not invoices:
                continue

            analytic_ids = set()
            for inv in invoices:
                main_analytic = self.env[
                    "account.payment"
                ]._get_main_analytic_from_invoice(inv)
                if main_analytic:
                    analytic_ids.add(main_analytic)
                else:
                    break
            else:
                if len(analytic_ids) == 1:
                    analytic_id = analytic_ids.pop()
                    template = self.env["account.payment.split.template"].search(
                        [
                            ("company_id", "=", wizard.company_id.id),
                            ("active", "=", True),
                            ("default_for_analytic_account_id", "=", analytic_id),
                        ],
                        order="priority desc, id",
                        limit=1,
                    )
                    if template:
                        wizard.split_template_id = template
        return res

    # ------------------------------------------------------------------
    # Propagar al pago
    # ------------------------------------------------------------------
    def _create_payment_vals_from_wizard(self, batch_result):
        """Extiende para incluir split_template_id en los valores del pago."""
        vals = super()._create_payment_vals_from_wizard(batch_result)
        if self.split_template_id:
            vals["split_template_id"] = self.split_template_id.id
        return vals
