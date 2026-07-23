# -*- coding: utf-8 -*-
"""Test del segundo aprobador dinámico según el tipo de solicitud de gasto.

La gratificación la revisa el Responsable de Clientes y Becarios
(clientes@aicia.es); el resto de tipos, el Responsable de Personal y compras
(personal@aicia.es).
"""
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
