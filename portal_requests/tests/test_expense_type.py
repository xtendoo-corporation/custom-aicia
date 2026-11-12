# -*- coding: utf-8 -*-
"""Test del segundo aprobador dinámico según el tipo de solicitud de gasto.

La gratificación la revisa el Responsable de Clientes y Becarios
(clientes@aicia.es); el resto de tipos, el Responsable de Personal y compras
(personal@aicia.es).
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExpenseSecondApprover(TransactionCase):

    def setUp(self):
        super().setUp()
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Test'})
        self.project = self.env['account.analytic.account'].create({
            'name': 'Proyecto Test',
            'plan_id': plan.id,
        })
        self.user = self.env['res.users'].create({
            'name': 'Solicitante Gasto',
            'login': 'expense_requester_test',
            'email': 'expense_requester_test@example.com',
        })

    def _make_request(self, expense_type):
        return self.env['portal.hr.expensive.request'].create({
            'user_id': self.user.id,
            'type': expense_type,
            'project': self.project.id,
        })

    def test_gratificacion_goes_to_client_responsible(self):
        request = self._make_request('gratificacion')
        self.assertEqual(
            request._second_approver_group_xmlid(),
            'portal_requests.group_intern_partner_responsible',
        )

    def test_other_types_go_to_personnel_responsible(self):
        for expense_type in ('bienes_servicios', 'material_inventariable',
                             'liquidacion_gastos'):
            request = self._make_request(expense_type)
            self.assertEqual(
                request._second_approver_group_xmlid(),
                'portal_requests.group_personnel_purchase_responsible',
                "El tipo %s debe ir al responsable de personal y compras"
                % expense_type,
            )


@tagged('post_install', '-at_install')
class TestGratificationDashboard(TransactionCase):

    def setUp(self):
        super().setUp()
        group = self.env.ref('portal_requests.group_intern_partner_responsible')
        self.approver = self.env['res.users'].create({
            'name': 'Responsable Gratificaciones',
            'login': 'gratification_dashboard_approver',
            'email': 'gratification_approver@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_invoice').id,
                group.id,
            ])],
        })
        self.boss = self.env['res.users'].create({
            'name': 'Jefe Gratificaciones',
            'login': 'gratification_dashboard_boss',
            'email': 'gratification_boss@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_portal').id,
                self.env.ref('portal_requests.group_equip_boss').id,
            ])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Gratificaciones',
            'code': 'GRATTEST',
            'equip_boss': self.boss.id,
        })
        plan = self.env['account.analytic.plan'].create({
            'name': 'Plan Gratificaciones',
        })
        self.project = self.env['account.analytic.account'].create({
            'name': 'Proyecto Gratificaciones',
            'plan_id': plan.id,
            'work_group_id': self.team.id,
        })
        self.dashboard = self.env.ref(
            'portal_requests.dashboard_gratification'
        ).with_user(self.approver)
        self.expenses = self.env['portal.hr.expensive.request']

    def _expense(self, expense_type, status, is_more=False):
        return self.expenses.create({
            'user_id': self.env.user.id,
            'project': self.project.id,
            'type': expense_type,
            'status': status,
            'is_more': is_more,
        })

    def test_dashboard_visibility(self):
        dashboard_model = self.env['portal.request.dashboard']
        self.assertIn(
            self.dashboard, dashboard_model.with_user(self.approver).search([])
        )
        other_user = self.env['res.users'].create({
            'name': 'Responsable Compras',
            'login': 'gratification_dashboard_other',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('portal_requests.group_personnel_purchase_responsible').id,
            ])],
        })
        self.assertNotIn(
            self.dashboard.id, dashboard_model.with_user(other_user).search([]).ids
        )
        admin = self.env['res.users'].create({
            'name': 'Admin AICIA',
            'login': 'gratification_dashboard_admin',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_aicia_admin').id,
            ])],
        })
        self.assertIn(
            self.dashboard.id, dashboard_model.with_user(admin).search([]).ids
        )

    def test_counts_and_actions_only_include_matching_gratifications(self):
        pending = self._expense('gratificacion', 'approved_purchase_responsible')
        approved = self._expense('gratificacion', 'approve')
        waiting_boss = self._expense('gratificacion', 'approved_by_boss_group')
        other = self._expense('bienes_servicios', 'approved_purchase_responsible')
        pending_action = self.dashboard.open_new_action_to_revise()
        approved_action = self.dashboard.open_new_action_approve()
        pending_records = self.expenses.with_user(self.approver).search(
            pending_action['domain']
        )
        approved_records = self.expenses.with_user(self.approver).search(
            approved_action['domain']
        )
        self.assertIn(pending, pending_records)
        self.assertNotIn(waiting_boss, pending_records)
        self.assertNotIn(other, pending_records)
        self.assertIn(approved, approved_records)
        self.assertNotIn(pending, approved_records)
        self.assertEqual(self.dashboard.count_to_revise, len(pending_records))
        self.assertEqual(self.dashboard.count_approved, len(approved_records))

    def test_boss_approval_notifies_client_responsible(self):
        expense = self._expense('gratificacion', 'approved_by_boss_group')
        with patch.object(
            type(expense), '_send_purchase_request_mail', autospec=True
        ) as send_mail:
            result = expense.with_user(self.boss).action_approve()
        self.assertEqual(expense.status, 'approved_purchase_responsible')
        self.assertIn(self.approver, send_mail.call_args.args[2])
        self.assertIn('clientes y becarios', result['params']['message'])

    def test_boss_resubmission_notifies_client_responsible(self):
        expense = self._expense('gratificacion', 'to_revise')
        expense.user_id = self.boss
        with patch.object(
            type(expense), '_send_purchase_request_mail', autospec=True
        ) as send_mail:
            expense.with_user(self.boss).action_approve()
        self.assertEqual(expense.status, 'approved_purchase_responsible')
        self.assertIn(self.approver, send_mail.call_args.args[2])

    def test_other_expense_notifies_purchase_responsible(self):
        purchase_responsible = self.env['res.users'].create({
            'name': 'Responsable Compras',
            'login': 'gratification_dashboard_purchase',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('portal_requests.group_personnel_purchase_responsible').id,
            ])],
        })
        expense = self._expense('bienes_servicios', 'approved_by_boss_group')
        with patch.object(
            type(expense), '_send_purchase_request_mail', autospec=True
        ) as send_mail:
            expense.with_user(self.boss).action_approve()
        recipients = send_mail.call_args.args[2]
        self.assertIn(purchase_responsible, recipients)
        self.assertNotIn(self.approver, recipients)

    def test_client_responsible_approves_gratification(self):
        expense = self._expense('gratificacion', 'approved_purchase_responsible')
        expense.with_user(self.approver).action_approve()
        self.assertEqual(expense.status, 'approve')
        self.assertFalse(expense.invoice_created)
        self.assertTrue(expense.with_user(self.approver).show_mark_paid_button)

    def test_gratification_above_threshold_goes_to_director(self):
        expense = self._expense(
            'gratificacion', 'approved_purchase_responsible', is_more=True
        )
        with patch.object(type(expense), '_send_purchase_request_mail'):
            expense.with_user(self.approver).action_approve()
        self.assertEqual(expense.status, 'approved_director')
        self.assertFalse(expense.invoice_created)
