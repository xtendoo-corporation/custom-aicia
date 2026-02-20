# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models, _


class AccountMove(models.Model):
    """Extensión de account.move para mostrar repartos relacionados.

    Se añade un computed field que busca los logs de reparto vinculados
    a pagos reconciliados con esta factura.
    """

    _inherit = "account.move"

    split_log_ids = fields.One2many(
        comodel_name="account.payment.split.log",
        compute="_compute_split_log_ids",
        string="Logs de Reparto",
    )
    split_log_count = fields.Integer(
        string="Nº Repartos",
        compute="_compute_split_log_ids",
    )

    def _compute_split_log_ids(self):
        """Busca logs de reparto vinculados a esta factura a través de
        los pagos reconciliados o por invoice_ids en el log."""
        SplitLog = self.env["account.payment.split.log"]
        for move in self:
            if move.move_type in ("out_invoice", "out_refund"):
                logs = SplitLog.search(
                    [
                        ("invoice_ids", "in", move.id),
                    ]
                )
                move.split_log_ids = logs
                move.split_log_count = len(logs)
            else:
                move.split_log_ids = SplitLog
                move.split_log_count = 0

    def button_open_split_logs(self):
        """Abre los logs de reparto relacionados con esta factura."""
        self.ensure_one()
        logs = self.split_log_ids
        if not logs:
            return

        action = {
            "name": _("Repartos de Cobro"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment.split.log",
            "context": {"create": False},
        }
        if len(logs) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": logs.id,
                }
            )
        else:
            action.update(
                {
                    "view_mode": "list,form",
                    "domain": [("id", "in", logs.ids)],
                }
            )
        return action
