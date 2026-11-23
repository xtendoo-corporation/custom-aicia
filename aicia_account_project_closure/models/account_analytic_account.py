# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models

class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    def action_open_project_closure_wizard(self):
        """Abre el wizard de cierre de proyectos pre-configurado para esta cuenta analítica."""
        self.ensure_one()
        return {
            'name': 'Cierre Contable por Proyectos',
            'type': 'ir.actions.act_window',
            'res_model': 'aicia.project.closure.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_analytic_account_ids': [self.id],
            }
        }
