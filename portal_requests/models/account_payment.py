from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    main_invoice_analytic_distribution = fields.Json(
        string='Distribución Analítica de la Factura',
        compute='_compute_main_invoice_analytic_distribution',
        store=False,
    )

    def _compute_main_invoice_analytic_distribution(self):
        # La analítica de cabecera de account.move la aporta
        # aicia_account_move_analytic_account, del que este módulo no depende.
        has_header_analytic = (
            'analytic_distribution' in self.env['account.move']._fields
        )
        for payment in self:
            analytic = False
            if has_header_analytic and payment.invoice_ids:
                analytic = payment.invoice_ids[0].analytic_distribution
            payment.main_invoice_analytic_distribution = analytic
