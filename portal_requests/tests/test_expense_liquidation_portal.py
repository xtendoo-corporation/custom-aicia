# -*- coding: utf-8 -*-
"""Formulario del portal para la liquidación de gastos: importe total
adelantado y dos selectores, tickets y facturas a nombre de AICIA."""
from odoo.http import Request
from odoo.tests import HttpCase, tagged

from .test_expense_request_routing_and_approve import ExpenseRoutingSetupMixin

PDF = b'%PDF-1.4 test'
XLSX = b'PK\x03\x04 test'
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


@tagged('post_install', '-at_install')
class TestExpenseLiquidationPortal(HttpCase, ExpenseRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'expense_liquidation_portal_test'
        self._setup_expense_routing_team(team_member_vals={'password': self.password})
        self.authenticate(self.team_member.login, self.password)

    def _submit(self, amount, tickets=(), invoices=(), expense_type='liquidacion_gastos', payment_orders=()):
        files = [('ticket_files', (name, PDF, 'application/pdf')) for name in tickets]
        files += [('invoice_files', (name, PDF, 'application/pdf')) for name in invoices]
        files += [('payment_order_file', (name, XLSX, XLSX_MIME)) for name in payment_orders]
        return self.url_open(
            '/portal/hr_expensive_request/submit',
            data={
                'csrf_token': Request.csrf_token(self),
                'expensive_type': expense_type,
                'user_id': str(self.team_member.id),
                'company_id': str(self.analytic.id),
                'liquidation_amount': amount,
            },
            files=files or None,
            allow_redirects=False,
        )

    def _last_request(self):
        return self.env['portal.hr.expensive.request'].sudo().search(
            [('user_id', '=', self.team_member.id)], order='id desc', limit=1)

    def test_form_shows_liquidation_fields(self):
        response = self.url_open('/portal/hr_expensive_request')
        self.assertEqual(response.status_code, 200)
        for name in ('liquidation_amount', 'ticket_files', 'invoice_files', 'payment_order_file'):
            self.assertIn(f'name="{name}"', response.text)

    def test_submit_classifies_tickets_and_invoices(self):
        response = self._submit('350,50', tickets=['taxi.pdf', 'parking.pdf'], invoices=['hotel.pdf'])
        self.assertEqual(response.status_code, 303)
        request = self._last_request()
        self.assertEqual(request.type, 'liquidacion_gastos')
        self.assertEqual(request.liquidation_amount, 350.5)
        self.assertFalse(request.is_more)
        attachments = self.env['ir.attachment'].sudo().search(
            [('res_model', '=', request._name), ('res_id', '=', request.id)])
        self.assertEqual(len(attachments), 3)
        self.assertEqual(request.employee_invoice_attachment_ids.mapped('name'), ['hotel.pdf'])

    def test_total_over_threshold_needs_director(self):
        self._submit('12000', invoices=['equipo.pdf'])
        self.assertTrue(self._last_request().is_more)

    def test_submit_without_amount_is_rejected(self):
        response = self._submit('', tickets=['taxi.pdf'])
        self.assertIn('error=liquidation', response.headers['Location'])
        self.assertFalse(self._last_request())

    def test_submit_without_documents_is_rejected(self):
        response = self._submit('80')
        self.assertIn('error=liquidation', response.headers['Location'])
        self.assertFalse(self._last_request())

    def test_detail_shows_total_and_invoice_badge(self):
        self._submit('120', tickets=['taxi.pdf'], invoices=['hotel.pdf'])
        request = self._last_request()
        response = self.url_open(f'/my/expenses/{request.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Importe total adelantado', response.text)
        self.assertIn('Factura a nombre de AICIA', response.text)

    def test_payment_order_field_is_the_last_one(self):
        text = self.url_open('/portal/hr_expensive_request').text
        self.assertGreater(text.index('name="payment_order_file"'), text.index('name="invoice_files"'))
        self.assertGreater(text.index('name="invoice_files"'), text.index('name="ticket_files"'))

    def test_submit_stores_payment_order_apart_from_tickets_and_invoices(self):
        response = self._submit(
            '350,50', tickets=['taxi.pdf'], invoices=['hotel.pdf'], payment_orders=['gastos.xlsx'])
        self.assertEqual(response.status_code, 303)
        request = self._last_request()
        self.assertEqual(request.payment_order_attachment_ids.mapped('name'), ['orden_pago_gastos.xlsx'])
        self.assertEqual(request.employee_invoice_attachment_ids.mapped('name'), ['hotel.pdf'])
        self.assertEqual(request.ticket_attachment_ids.mapped('name'), ['taxi.pdf'])

    def test_payment_order_is_optional(self):
        self._submit('80', tickets=['taxi.pdf'])
        self.assertFalse(self._last_request().payment_order_attachment_ids)

    def test_payment_order_must_be_a_spreadsheet(self):
        response = self._submit('80', tickets=['taxi.pdf'], payment_orders=['orden.pdf'])
        self.assertIn('error=payment_order', response.headers['Location'])
        self.assertFalse(self._last_request())
        page = self.url_open(response.headers['Location'])
        self.assertIn('La orden de pago debe ser un archivo Excel', page.text)
        self.assertNotIn('adjunte al\n', page.text)

    def test_detail_shows_payment_order_badge(self):
        self._submit('120', tickets=['taxi.pdf'], payment_orders=['gastos.xlsx'])
        response = self.url_open(f'/my/expenses/{self._last_request().id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Orden de pago', response.text)
