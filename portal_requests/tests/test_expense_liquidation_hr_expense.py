# -*- coding: utf-8 -*-
"""La liquidación de gastos se reembolsa al empleado con hr_expense.

Al aprobarla, en lugar de una factura de proveedor sin contacto se crea un
gasto de hr_expense pagado por el empleado, con los justificantes de la
solicitud y la distribución analítica del proyecto.
"""
import base64
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExpenseLiquidationHrExpense(TransactionCase):

    def setUp(self):
        super().setUp()
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Liquidación'})
        self.project = self.env['account.analytic.account'].create({
            'name': 'Proyecto Liquidación',
            'plan_id': plan.id,
        })
        self.requester = self.env['res.users'].create({
            'name': 'Solicitante Liquidación',
            'login': 'liquidation_requester_test',
            'email': 'liquidation_requester_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.purchase_responsible = self.env['res.users'].create({
            'name': 'Responsable Compras Liquidación',
            'login': 'liquidation_purchase_responsible_test',
            'email': 'liquidation_purchase_responsible_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('portal_requests.group_personnel_purchase_responsible').id,
            ])],
        })

    def _create_employee(self, user):
        return self.env['hr.employee'].create({
            'name': user.name,
            'user_id': user.id,
            'company_id': self.env.company.id,
        })

    def _create_request(self, expense_type='liquidacion_gastos'):
        return self.env['portal.hr.expensive.request'].create({
            'user_id': self.requester.id,
            'type': expense_type,
            'project': self.project.id,
            'status': 'approved_purchase_responsible',
        })

    def _attach(self, request, name):
        return self.env['ir.attachment'].create({
            'name': name,
            'datas': base64.b64encode(b'%PDF-1.4 test'),
            'mimetype': 'application/pdf',
            'res_model': 'portal.hr.expensive.request',
            'res_id': request.id,
        })

    def _approve(self, request):
        return request.with_user(self.purchase_responsible).action_approve()

    def test_approval_creates_draft_employee_expense(self):
        employee = self._create_employee(self.requester)
        request = self._create_request()
        self._approve(request)

        expense = request.expense_id
        self.assertEqual(request.status, 'approve')
        self.assertFalse(request.invoice_created)
        self.assertTrue(expense)
        self.assertEqual(expense.employee_id, employee)
        self.assertEqual(expense.payment_mode, 'own_account')
        self.assertEqual(expense.product_id, self.env.ref('hr_expense.product_product_no_cost'))
        self.assertEqual(expense.analytic_distribution, {str(self.project.id): 100.0})
        # Sin importe, hr_expense no permite aprobarlo: lo completa Contabilidad.
        self.assertEqual(expense.state, 'draft')
        self.assertIn(
            self.purchase_responsible.name,
            expense.message_ids[:1].body,
        )

    def test_approval_moves_all_receipts_to_expense(self):
        self._create_employee(self.requester)
        request = self._create_request()
        ticket = self._attach(request, 'ticket_restaurante.pdf')
        hotel = self._attach(request, 'factura_hotel.pdf')
        self._approve(request)

        expense = request.expense_id
        for attachment in ticket | hotel:
            self.assertEqual(attachment.res_model, 'hr.expense')
            self.assertEqual(attachment.res_id, expense.id)
        self.assertIn(expense.message_main_attachment_id, ticket | hotel)

    def test_approval_without_receipts_has_no_main_attachment(self):
        self._create_employee(self.requester)
        request = self._create_request()
        self._approve(request)
        self.assertFalse(request.expense_id.message_main_attachment_id)

    def test_requester_without_employee_blocks_approval(self):
        request = self._create_request()
        with self.assertRaises(UserError):
            self._approve(request)
        self.assertEqual(request.status, 'approved_purchase_responsible')
        self.assertFalse(request.expense_id)

    def test_employee_of_active_company_is_preferred(self):
        other_company = self.env['res.company'].create({'name': 'Otra compañía liquidación'})
        self.requester.company_ids = [(4, other_company.id)]
        self.env['hr.employee'].create({
            'name': self.requester.name,
            'user_id': self.requester.id,
            'company_id': other_company.id,
        })
        employee = self._create_employee(self.requester)
        request = self._create_request()
        self.assertEqual(request._get_requester_employee(), employee)

    def test_other_types_keep_creating_purchase_invoice(self):
        request = self._create_request(expense_type='bienes_servicios')
        with patch.object(type(request), '_create_purchase_invoice') as create_invoice:
            self._approve(request)
        create_invoice.assert_called_once()
        self.assertEqual(request.status, 'approve')
        self.assertFalse(request.expense_id)

    def test_accounting_amount_comes_from_expense(self):
        self._create_employee(self.requester)
        request = self._create_request()
        self._approve(request)
        request.expense_id.total_amount_currency = 42.5

        amount, currency = request._get_accounting_amount()
        self.assertEqual(amount, 42.5)
        self.assertEqual(currency, request.expense_id.currency_id)

    def test_accounting_amount_without_document(self):
        request = self._create_request()
        amount, currency = request._get_accounting_amount()
        self.assertIsNone(amount)
        self.assertFalse(currency)

    def test_action_view_expense_opens_created_expense(self):
        self._create_employee(self.requester)
        request = self._create_request()
        self._approve(request)
        action = request.action_view_expense()
        self.assertEqual(action['res_model'], 'hr.expense')
        self.assertEqual(action['res_id'], request.expense_id.id)
