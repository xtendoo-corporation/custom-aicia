# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'move_id' in vals and 'analytic_distribution' not in vals:
                move = self.env['account.move'].browse(vals['move_id'])
                if move.exists() and move.analytic_distribution:
                    if vals.get('display_type') not in ('line_section', 'line_note'):
                        vals['analytic_distribution'] = move.analytic_distribution
                        _logger.info(f"Copiando distribución analítica {move.analytic_distribution} a nueva línea")

        lines = super(AccountMoveLine, self).create(vals_list)

        for line in lines:
            if (not line.analytic_distribution and
                line.move_id and
                line.move_id.analytic_distribution and
                line.display_type not in ('line_section', 'line_note')):
                line.analytic_distribution = line.move_id.analytic_distribution
                _logger.info(f"Copiando distribución analítica post-create: {line.move_id.analytic_distribution}")

        return lines

    @api.onchange('product_id')
    def _onchange_product_id_analytic(self):
        if self.move_id and self.move_id.analytic_distribution and not self.analytic_distribution:
            if self.display_type not in ('line_section', 'line_note'):
                self.analytic_distribution = self.move_id.analytic_distribution
                _logger.info(f"Copiando distribución analítica en onchange product_id: {self.move_id.analytic_distribution}")

