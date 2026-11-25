# -*- coding: utf-8 -*-
"""Liquidación de gastos con tickets y facturas a nombre de AICIA.

El empleado declara el total adelantado y sube por separado los tickets y
las facturas a nombre de AICIA. Al aprobar:
- cada factura se registra como factura de proveedor pagada por el empleado;
  al contabilizarla, su deuda se traslada del proveedor al empleado;
- los tickets se reembolsan como gasto de hr_expense.
Todo lo pendiente queda en la cuenta a pagar del empleado y se le paga de
una sola vez.
"""
import base64

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestLiquidationEmployeeInvoices(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        plan = cls.env['account.analytic.plan'].create({'name': 'Plan Liquidación Facturas'})
        cls.project = cls.env['account.analytic.account'].create({
            'name': 'Proyecto Liquidación Facturas',
            'plan_id': plan.id,
        })
        user_vals = {'company_id': company.id, 'company_ids': [Command.set(company.ids)]}
        cls.requester = cls.env['res.users'].create({
            'name': 'Empleada Viajera', 'login': 'liquidation_invoices_requester',
            'email': 'liquidation_invoices_requester@example.com',
            'group_ids': [Command.set(cls.env.ref('base.group_user').ids)], **user_vals,
        })
        cls.purchase_responsible = cls.env['res.users'].create({
            'name': 'Responsable Compras Facturas', 'login': 'liquidation_invoices_purchase',
            'email': 'liquidation_invoices_purchase@example.com',
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('portal_requests.group_personnel_purchase_responsible').id,
            ])], **user_vals,
        })
        # El usuario de los tests es contable, sin permisos de Empleados.
        cls.employee = cls.env['hr.employee'].sudo().create({
            'name': cls.requester.name, 'user_id': cls.requester.id, 'company_id': company.id,
        })
        bank = cls.env['res.partner.bank'].sudo().create({
            'acc_number': 'ES9121000418450200051332',
            'partner_id': cls.employee.work_contact_id.id,
        })
        cls.employee.bank_account_ids = [Command.set(bank.ids)]
        cls.employee_partner = cls.employee.work_contact_id
        cls.bank_journal = cls.company_data['default_journal_bank']

    # Helpers ---------------------------------------------------------------

    def _attach(self, request, name):
        return self.env['ir.attachment'].create({
            'name': name,
            'datas': base64.b64encode(b'%PDF-1.4 test'),
            'mimetype': 'application/pdf',
            'res_model': 'portal.hr.expensive.request',
            'res_id': request.id,
        })

    def _attach_payment_order(self, request, name='orden_pago_gastos.xlsx'):
        attachment = self.env['ir.attachment'].create({
            'name': name,
            'datas': base64.b64encode(b'PK test'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': 'portal.hr.expensive.request',
            'res_id': request.id,
        })
        request.payment_order_attachment_ids = attachment
        return attachment

    def _post_expense(self, request):
        expense = request.expense_id.sudo()
        expense.action_submit()
        expense.action_approve()
        post_action = expense.action_post()
        self.env[post_action['res_model']].sudo().with_context(**post_action['context']).create(
            {}).action_post_entry()

    def _create_liquidation(self, amount, tickets=(), invoices=()):
        request = self.env['portal.hr.expensive.request'].create({
            'user_id': self.requester.id,
            'type': 'liquidacion_gastos',
            'project': self.project.id,
            'status': 'approved_purchase_responsible',
            'liquidation_amount': amount,
        })
        for name in tickets:
            self._attach(request, name)
        invoice_attachments = self.env['ir.attachment']
        for name in invoices:
            invoice_attachments |= self._attach(request, name)
        request.employee_invoice_attachment_ids = invoice_attachments
        return request

    def _approve(self, request):
        return request.with_user(self.purchase_responsible).action_approve()

    def _complete_and_post(self, invoice, amount):
        """Lo que hace Contabilidad: proveedor, fecha y líneas; luego contabiliza."""
        invoice.write({
            'partner_id': self.partner_a.id,
            'invoice_date': '2026-11-02',
            'invoice_line_ids': [Command.create({
                'name': 'Hotel congreso', 'quantity': 1, 'price_unit': amount,
                'tax_ids': [Command.clear()],
            })],
        })
        invoice.action_post()
        return invoice

    def _employee_line(self, invoice):
        return invoice.employee_transfer_move_id.line_ids.filtered(
            lambda line: line.partner_id == self.employee_partner)

    def _pay_employee(self, request):
        action = request.action_register_employee_payment()
        wizard = self.env['account.payment.register'].with_context(**action['context']).create({
            'journal_id': self.bank_journal.id,
        })
        return wizard._create_payments()

    # Aprobación ------------------------------------------------------------

    def test_approval_splits_invoices_and_tickets(self):
        request = self._create_liquidation(
            350.0, tickets=['taxi_1.pdf', 'taxi_2.pdf'], invoices=['hotel.pdf', 'inscripcion.pdf'])
        self._approve(request)

        self.assertEqual(request.status, 'approve')
        invoices = request.employee_invoice_ids
        self.assertEqual(len(invoices), 2)
        self.assertEqual(request.employee_invoice_count, 2)
        for invoice in invoices:
            self.assertEqual(invoice.move_type, 'in_invoice')
            self.assertEqual(invoice.state, 'draft')
            self.assertEqual(invoice.paid_by_employee_id, self.employee)
            self.assertEqual(invoice.message_main_attachment_id.res_id, invoice.id)
            self.assertEqual(invoice.message_main_attachment_id.res_model, 'account.move')
        self.assertEqual(
            set(invoices.message_main_attachment_id.mapped('name')), {'hotel.pdf', 'inscripcion.pdf'})

        expense = request.expense_id
        self.assertEqual(expense.payment_mode, 'own_account')
        self.assertEqual(expense.employee_id, self.employee)
        tickets = self.env['ir.attachment'].search(
            [('res_model', '=', 'hr.expense'), ('res_id', '=', expense.id)])
        self.assertEqual(set(tickets.mapped('name')), {'taxi_1.pdf', 'taxi_2.pdf'})
        # Con facturas, el importe de los tickets se propone al contabilizarlas.
        self.assertFalse(expense.total_amount_currency)

    def test_only_tickets_proposes_total_as_expense_amount(self):
        request = self._create_liquidation(45.5, tickets=['taxi.pdf'])
        self._approve(request)
        self.assertFalse(request.employee_invoice_ids)
        self.assertEqual(request.expense_id.total_amount_currency, 45.5)
        # El precio unitario es lo que se contabiliza: debe seguir al total.
        self.assertEqual(request.expense_id.price_unit, 45.5)
        self.assertEqual(request.liquidation_difference, 0.0)

    def test_only_invoices_creates_no_expense(self):
        request = self._create_liquidation(200.0, invoices=['hotel.pdf'])
        self._approve(request)
        self.assertEqual(len(request.employee_invoice_ids), 1)
        self.assertFalse(request.expense_id)

    def test_employee_without_bank_account_blocks_approval(self):
        self.employee.sudo().bank_account_ids = [Command.clear()]
        request = self._create_liquidation(100.0, invoices=['hotel.pdf'])
        with self.assertRaises(UserError):
            self._approve(request)
        self.assertFalse(request.employee_invoice_ids)

    # Contabilización de la factura ------------------------------------------

    def test_posting_invoice_moves_debt_to_employee(self):
        request = self._create_liquidation(200.0, invoices=['hotel.pdf'])
        self._approve(request)
        invoice = self._complete_and_post(request.employee_invoice_ids, 200.0)

        transfer = invoice.employee_transfer_move_id
        self.assertEqual(transfer.state, 'posted')
        self.assertEqual(transfer.journal_id.type, 'general')
        # La factura queda saldada: no se paga al proveedor.
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        self.assertFalse(invoice.amount_residual)
        employee_line = self._employee_line(invoice)
        self.assertEqual(employee_line.amount_residual, -200.0)
        self.assertEqual(
            employee_line.account_id,
            self.employee_partner.with_company(invoice.company_id).property_account_payable_id)
        self.assertFalse(request.is_reimbursed)

    def test_tickets_amount_is_total_minus_posted_invoices(self):
        request = self._create_liquidation(
            350.0, tickets=['taxi.pdf'], invoices=['hotel.pdf', 'inscripcion.pdf'])
        self._approve(request)
        hotel, inscription = request.employee_invoice_ids
        self._complete_and_post(hotel, 200.0)
        # Mientras quede una factura en borrador no se propone importe.
        self.assertFalse(request.expense_id.total_amount_currency)
        self._complete_and_post(inscription, 100.0)

        self.assertEqual(request.expense_id.total_amount_currency, 50.0)
        self.assertEqual(request.expense_id.price_unit, 50.0)
        self.assertEqual(request.liquidation_invoices_amount, 300.0)
        self.assertEqual(request.liquidation_tickets_amount, 50.0)
        self.assertEqual(request.liquidation_difference, 0.0)

    def test_difference_shows_unjustified_amount(self):
        request = self._create_liquidation(250.0, invoices=['hotel.pdf'])
        self._approve(request)
        self._complete_and_post(request.employee_invoice_ids, 200.0)
        self.assertEqual(request.liquidation_difference, 50.0)

    def test_invoice_back_to_draft_cancels_transfer(self):
        request = self._create_liquidation(200.0, invoices=['hotel.pdf'])
        self._approve(request)
        invoice = self._complete_and_post(request.employee_invoice_ids, 200.0)
        transfer = invoice.employee_transfer_move_id

        invoice.button_draft()

        self.assertFalse(invoice.employee_transfer_move_id)
        self.assertTrue(transfer.reversal_move_ids)
        self.assertTrue(all(transfer.line_ids.mapped('reconciled')))
        # Al volver a contabilizar se genera un traslado nuevo.
        invoice.action_post()
        self.assertTrue(invoice.employee_transfer_move_id)
        self.assertNotEqual(invoice.employee_transfer_move_id, transfer)
        self.assertEqual(self._employee_line(invoice).amount_residual, -200.0)

    def test_invoices_not_paid_by_employee_are_untouched(self):
        invoice = self.init_invoice('in_invoice', amounts=[100.0], post=True)
        self.assertFalse(invoice.employee_transfer_move_id)
        self.assertEqual(invoice.payment_state, 'not_paid')

    # Reembolso -------------------------------------------------------------

    def test_single_payment_reimburses_invoices_and_tickets(self):
        request = self._create_liquidation(
            350.0, tickets=['taxi.pdf'], invoices=['hotel.pdf', 'inscripcion.pdf'])
        self._approve(request)
        hotel, inscription = request.employee_invoice_ids
        self._complete_and_post(hotel, 200.0)
        self._complete_and_post(inscription, 100.0)
        # Contabilidad aprueba y contabiliza el gasto de los tickets.
        expense = request.expense_id.sudo()
        expense.action_submit()
        expense.action_approve()
        post_action = expense.action_post()
        self.env[post_action['res_model']].sudo().with_context(**post_action['context']).create(
            {}).action_post_entry()

        lines = request._employee_payable_lines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(sum(lines.mapped('amount_residual')), -350.0)

        payments = self._pay_employee(request)
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments.amount, 350.0)
        self.assertEqual(payments.partner_id, self.employee_partner)
        # La transferencia (y su remesa SEPA) va a la cuenta del empleado.
        self.assertEqual(payments.partner_bank_id, self.employee.primary_bank_account_id)
        self.assertTrue(request.is_reimbursed)

    def test_reimbursed_invoice_cannot_go_back_to_draft(self):
        request = self._create_liquidation(200.0, invoices=['hotel.pdf'])
        self._approve(request)
        invoice = self._complete_and_post(request.employee_invoice_ids, 200.0)
        self._pay_employee(request)
        self.assertTrue(request.is_reimbursed)
        with self.assertRaises(UserError):
            invoice.button_draft()

    def test_register_payment_without_pending_amounts_fails(self):
        request = self._create_liquidation(200.0, invoices=['hotel.pdf'])
        self._approve(request)
        with self.assertRaises(UserError):
            request.action_register_employee_payment()

    def test_not_reimbursed_while_documents_are_draft(self):
        request = self._create_liquidation(350.0, tickets=['taxi.pdf'], invoices=['hotel.pdf'])
        self._approve(request)
        self._complete_and_post(request.employee_invoice_ids, 200.0)
        self._pay_employee(request)
        # El gasto de los tickets sigue sin contabilizar.
        self.assertFalse(request.is_reimbursed)

    def test_portal_amount_is_declared_total(self):
        request = self._create_liquidation(350.0, tickets=['taxi.pdf'])
        amount, currency = request._get_accounting_amount()
        self.assertEqual(amount, 350.0)
        self.assertEqual(currency, request.currency_id)

    # Orden de pago (Excel) y tickets visibles --------------------------------

    def test_payment_order_is_not_treated_as_a_ticket(self):
        request = self._create_liquidation(100.0, tickets=['taxi.pdf'])
        order = self._attach_payment_order(request)
        self._approve(request)

        tickets = self.env['ir.attachment'].search(
            [('res_model', '=', 'hr.expense'), ('res_id', '=', request.expense_id.id)])
        self.assertEqual(tickets.mapped('name'), ['taxi.pdf'])
        # La orden de pago se queda en la solicitud.
        self.assertEqual((order.res_model, order.res_id), (request._name, request.id))
        self.assertEqual(request.payment_order_attachment_ids, order)

    def test_only_payment_order_and_invoices_creates_no_ticket_expense(self):
        request = self._create_liquidation(100.0, invoices=['hotel.pdf'])
        self._attach_payment_order(request)
        self._approve(request)
        self.assertFalse(request.expense_id)
        self.assertEqual(len(request.employee_invoice_ids), 1)

    def test_ticket_attachments_exclude_invoices_and_payment_order(self):
        request = self._create_liquidation(
            350.0, tickets=['taxi_1.pdf', 'taxi_2.pdf'], invoices=['hotel.pdf'])
        self._attach_payment_order(request)
        self.assertEqual(
            set(request.ticket_attachment_ids.mapped('name')), {'taxi_1.pdf', 'taxi_2.pdf'})

    def test_ticket_attachments_still_visible_after_approval(self):
        request = self._create_liquidation(
            350.0, tickets=['taxi_1.pdf', 'taxi_2.pdf'], invoices=['hotel.pdf'])
        self._attach_payment_order(request)
        self._approve(request)
        # Los tickets han pasado al gasto de hr_expense pero se siguen viendo.
        self.assertEqual(
            set(request.ticket_attachment_ids.mapped('name')), {'taxi_1.pdf', 'taxi_2.pdf'})

    def test_ticket_attachments_empty_for_other_types(self):
        request = self.env['portal.hr.expensive.request'].create({
            'user_id': self.requester.id, 'type': 'bienes_servicios', 'project': self.project.id,
            'status': 'approved_purchase_responsible'})
        self._attach(request, 'presupuesto.pdf')
        self.assertFalse(request.ticket_attachment_ids)

    # Importes de reembolso ---------------------------------------------------

    def test_reimbursement_amounts_follow_accounting_and_payments(self):
        request = self._create_liquidation(350.0, tickets=['taxi.pdf'], invoices=['hotel.pdf'])
        self._approve(request)
        # Aún nada contabilizado: no hay nada que reembolsar.
        self.assertEqual(
            (request.liquidation_paid_amount, request.liquidation_pending_amount), (0.0, 0.0))

        self._complete_and_post(request.employee_invoice_ids, 200.0)
        # Solo la factura trasladada: 200 por reembolsar.
        self.assertEqual(request.liquidation_pending_amount, 200.0)

        self._post_expense(request)
        self.assertEqual(request.liquidation_paid_amount, 0.0)
        self.assertEqual(request.liquidation_pending_amount, 350.0)

        action = request.action_register_employee_payment()
        wizard = self.env['account.payment.register'].with_context(**action['context']).create({
            'journal_id': self.bank_journal.id, 'amount': 100.0})
        wizard._create_payments()
        self.assertEqual(request.liquidation_paid_amount, 100.0)
        self.assertEqual(request.liquidation_pending_amount, 250.0)
        self.assertFalse(request.is_reimbursed)

        self._pay_employee(request)
        self.assertEqual(request.liquidation_paid_amount, 350.0)
        self.assertEqual(request.liquidation_pending_amount, 0.0)
        self.assertTrue(request.is_reimbursed)

    def test_reimbursement_amounts_are_zero_for_other_types(self):
        request = self.env['portal.hr.expensive.request'].create({
            'user_id': self.requester.id, 'type': 'bienes_servicios', 'project': self.project.id,
            'status': 'approved_purchase_responsible'})
        self.assertEqual(
            (request.liquidation_paid_amount, request.liquidation_pending_amount), (0.0, 0.0))
