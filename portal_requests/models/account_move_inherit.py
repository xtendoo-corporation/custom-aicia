from odoo import models, fields, api, _


class AccountMoveInherit(models.Model):
    _inherit = 'account.move'

    # Campo de cuenta analítica en la cabecera de la factura
    analytic_account_header_id = fields.Many2one(
        'account.analytic.account',
        string='Cuenta Analítica',
        help='Cuenta analítica que se aplicará a todas las líneas de la factura'
    )

    @api.onchange('analytic_account_header_id')
    def _onchange_analytic_account_header_id(self):
        """Propaga la cuenta analítica de la cabecera a todas las líneas de factura"""
        if self.analytic_account_header_id:
            for line in self.invoice_line_ids:
                # Actualizar la cuenta analítica en cada línea
                line.analytic_distribution = {
                    str(self.analytic_account_header_id.id): 100.0
                }
        else:
            # Si se quita la cuenta analítica, limpiar las líneas
            for line in self.invoice_line_ids:
                line.analytic_distribution = False
