# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    def _compute_journal_item_count(self):
        """Cuenta los apuntes contables (account.move.line) asociados a esta cuenta analítica"""
        for record in self:
            # Buscar apuntes que tengan distribución analítica asignada
            move_lines = self.env['account.move.line'].search([
                ('analytic_distribution', '!=', False),
            ])

            # Filtrar las que contienen este analytic account en su distribución
            # analytic_distribution es un JSON como: {"42": 100.0} o {"42,43": 50.0}
            count = 0
            for line in move_lines:
                if line.analytic_distribution:
                    for key in line.analytic_distribution.keys():
                        # Las claves pueden ser "42" o "42,43" (múltiples IDs separados por coma)
                        analytic_ids = [int(id_str) for id_str in key.split(',')]
                        if record.id in analytic_ids:
                            count += 1
                            break

            record.journal_item_count = count

    journal_item_count = fields.Integer(string='Apuntes Contables', compute='_compute_journal_item_count')

    def action_view_journal_items(self):
        """Abre los apuntes contables asociados a esta cuenta analítica"""
        # Buscar apuntes que tengan distribución analítica
        move_lines = self.env['account.move.line'].search([
            ('analytic_distribution', '!=', False),
        ])

        # Filtrar las que contienen este analytic account en su distribución
        line_ids = []
        for line in move_lines:
            if line.analytic_distribution:
                for key in line.analytic_distribution.keys():
                    analytic_ids = [int(id_str) for id_str in key.split(',')]
                    if self.id in analytic_ids:
                        line_ids.append(line.id)
                        break

        return {
            'name': 'Apuntes Contables',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', line_ids)],
            'context': {'create': False},
            'target': 'current',
        }
