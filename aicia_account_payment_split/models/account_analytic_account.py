# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    payment_split_template_id = fields.Many2one(
        comodel_name="account.payment.split.template",
        string="Plantilla de Reparto",
        help="Plantilla de reparto que se asignará automáticamente a los pagos "
        "cuando esta cuenta analítica se detecte como principal en las facturas.",
    )
