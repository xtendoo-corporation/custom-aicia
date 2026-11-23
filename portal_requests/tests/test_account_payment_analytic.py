"""Analítica de la factura principal mostrada en el pago.

La analítica de cabecera (``account.move.analytic_distribution``) la aporta
``aicia_account_move_analytic_account``; si ese módulo no está instalado, el
cómputo no debe romper la lectura del pago.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAccountPaymentAnalytic(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': 'Cliente Pago'})
        self.invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
        })
        self.payment = self.env['account.payment'].create({
            'amount': 100,
            'partner_id': self.partner.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
        })

    def test_without_invoices_is_empty(self):
        self.assertFalse(self.payment.main_invoice_analytic_distribution)

    def test_without_header_analytic_field(self):
        self.payment.invoice_ids = self.invoice
        move_cls = type(self.env['account.move'])
        fields_without_header_analytic = {
            name: field for name, field in move_cls._fields.items()
            if name != 'analytic_distribution'
        }
        with patch.object(move_cls, '_fields', fields_without_header_analytic):
            self.payment.invalidate_recordset(
                ['main_invoice_analytic_distribution'])
            self.assertFalse(self.payment.main_invoice_analytic_distribution)

    def test_with_header_analytic_field(self):
        if 'analytic_distribution' not in self.env['account.move']._fields:
            self.skipTest('aicia_account_move_analytic_account no instalado')
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Pago'})
        analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Pago',
            'plan_id': plan.id,
        })
        distribution = {str(analytic.id): 100}
        self.invoice.analytic_distribution = distribution
        self.payment.invoice_ids = self.invoice
        self.assertEqual(
            self.payment.main_invoice_analytic_distribution, distribution)
