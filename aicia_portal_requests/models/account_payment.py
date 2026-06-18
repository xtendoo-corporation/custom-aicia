from odoo import models, fields

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    # Campo related a la distribución analítica de la primera factura asociada
    main_invoice_analytic_distribution = fields.Json(
        string='Distribución Analítica de la Factura',
        compute='_compute_main_invoice_analytic_distribution',
        store=False
    )

    def _compute_main_invoice_analytic_distribution(self):
        for payment in self:
            analytic = False
            if payment.invoice_ids:
                analytic = payment.invoice_ids[0].analytic_distribution
            payment.main_invoice_analytic_distribution = analytic

