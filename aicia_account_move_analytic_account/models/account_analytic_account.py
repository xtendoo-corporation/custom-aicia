# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    def _journal_item_ids_by_account(self):
        """{id de cuenta analítica: ids de apuntes contables que la usan} para las cuentas de self.

        Una sola consulta para todas las cuentas (antes se cargaban todos los apuntes con
        analítica una vez por cuenta). Las claves de la distribución son "42" o "42,43"."""
        wanted = set(self.ids)
        result = {account_id: set() for account_id in wanted}
        line_ids = self.env['account.move.line'].search([('analytic_distribution', '!=', False)]).ids
        if not line_ids or not wanted:
            return result
        self.env.cr.execute(
            """SELECT l.id, k FROM account_move_line l,
                    LATERAL jsonb_object_keys(l.analytic_distribution::jsonb) AS k
                WHERE l.id = ANY(%s)""", [line_ids])
        for line_id, key in self.env.cr.fetchall():
            for id_str in key.split(','):
                if id_str.isdigit() and int(id_str) in wanted:
                    result[int(id_str)].add(line_id)
        return result

    def _compute_journal_item_count(self):
        """Cuenta los apuntes contables (account.move.line) asociados a cada cuenta analítica"""
        lines_by_account = self._journal_item_ids_by_account()
        for record in self:
            record.journal_item_count = len(lines_by_account.get(record.id, ()))

    journal_item_count = fields.Integer(string='Apuntes Contables', compute='_compute_journal_item_count')

    def action_view_journal_items(self):
        """Abre los apuntes contables asociados a esta cuenta analítica"""
        self.ensure_one()
        line_ids = sorted(self._journal_item_ids_by_account()[self.id])
        return {
            'name': 'Apuntes Contables',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', line_ids)],
            'context': {'create': False},
            'target': 'current',
        }
