# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = ["account.move"]

    # Campo Many2one que relaciona con cuenta analítica
    analytic_distribution = fields.Json(
    )
    analytic_precision = fields.Integer(
        store=False,
        default=lambda self: self.env["decimal.precision"].precision_get(
            "Percentage Analytic"
        ),
    )
    work_group_id = fields.Many2one(
        compute="_compute_work_group_id",
        comodel_name="portal.work.group",
        string="Grupo de Trabajo",
        store=False,  # Almacenar para evitar que la primera lectura devuelva `_unknown`
        compute_sudo=True,  # Calcular con privilegios de superusuario para evitar errores de acceso
    )

    @api.depends("analytic_distribution")
    def _compute_work_group_id(self):
        for record in self:
            if record.analytic_distribution:
                print("analytic_distribution",record.analytic_distribution)
                first_key = next(iter(record.analytic_distribution))
                if first_key:
                    account = self.env['account.analytic.account'].browse(int(first_key))
                    print("first_key",first_key)
                    if account and account.work_group_id:
                        work_group = self.env['portal.work.group'].browse(account.work_group_id.id)
                        if work_group:
                            record.work_group_id = work_group.id
                else:
                    record.work_group_id = False
            else:
                record.work_group_id = False


    @api.onchange("analytic_distribution")
    def _onchange_analytic_distribution(self):
        """Actualiza analytic_distribution en todas las líneas del movimiento"""
        if self.analytic_distribution:
            for line in self.line_ids:
                line.analytic_distribution = self.analytic_distribution
        else:
            for line in self.line_ids:
                line.analytic_distribution = False
