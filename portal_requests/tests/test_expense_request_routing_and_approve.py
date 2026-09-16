# -*- coding: utf-8 -*-
"""Test del enrutado y del botón "Aprobar" de las Solicitudes de Gastos.

1. A petición del cliente, la solicitud de gasto del Administrativo pasa de
   nuevo por 'approved_by_boss_group' (aprobación del Jefe de Equipo), igual
   que la de un miembro normal del equipo -- solo el propio Jefe de Equipo va
   directo a 'approved_purchase_responsible'. Esto incluye también el
   reenvío tras un 'to_revise'.

2. Al abrir el detalle de CUALQUIER solicitud de gasto (tanto Jefe de Equipo
   como Administrativo) daba "500: Internal Server Error". Causa real: la
   plantilla ``portal_my_expense_detail.xml`` incluye un botón "Aprobar"
   condicionado a ``expense.show_approve_button``, pero ese campo nunca se
   había añadido al modelo ``portal.hr.expensive.request`` (a diferencia de
   ``portal.invoice.request``, que sí lo tiene) -- un ``AttributeError`` no
   controlado que Odoo devuelve como 500. Solo se disparaba para los roles
   cuyo botón "Solicitar Revisión" (el otro botón de la cabecera) no aplica,
   dejando que el motor de plantillas intentase evaluar el campo inexistente.

3. Al volver a exigir la aprobación del Jefe de Equipo, una solicitud
   rechazada del Administrativo puede quedar en 'to_revise'. Como
   group_administrative implica group_equip_boss, el Administrativo no veía
   el botón "Solicitar Revisión" (oculto para cualquiera con group_equip_boss)
   y se quedaba sin forma de reenviarla: _compute_show_solicitar_revision
   ahora excluye explícitamente a group_administrative de ese ocultamiento.
"""
from odoo.http import Request
from odoo.tests import HttpCase, TransactionCase, tagged


class ExpenseRoutingSetupMixin:

    def _setup_expense_routing_team(self, boss_vals=None, administrative_vals=None,
                                     team_member_vals=None):
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Gasto',
            'login': 'expense_boss_test',
            'email': 'expense_boss_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_equip_boss').id,
                self.env.ref('base.group_portal').id,
            ])],
            **(boss_vals or {}),
        })
        self.administrative = self.env['res.users'].create({
            'name': 'Administrativo Gasto',
            'login': 'expense_administrative_test',
            'email': 'expense_administrative_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('portal_requests.group_administrative').id])],
            **(administrative_vals or {}),
        })
        self.team_member = self.env['res.users'].create({
            'name': 'Miembro de Equipo Gasto',
            'login': 'expense_team_member_test',
            'email': 'expense_team_member_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
            **(team_member_vals or {}),
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Gasto',
            'code': 'EXPROUTE',
            'user_ids': [(6, 0, [self.boss.id, self.administrative.id, self.team_member.id])],
            'equip_boss': self.boss.id,
            'administrative_id': self.administrative.id,
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Gasto Routing'})
        self.analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Gasto Routing',
            'plan_id': plan.id,
            'work_group_id': self.team.id,
        })


@tagged('post_install', '-at_install')
class TestExpenseRequestSubmitRouting(HttpCase, ExpenseRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'expense_routing_http_test'
        self._setup_expense_routing_team(
            boss_vals={'password': self.password},
            administrative_vals={'password': self.password},
            team_member_vals={'password': self.password},
        )

    def _submit(self, user):
        self.authenticate(user.login, self.password)
        return self.url_open(
            '/portal/hr_expensive_request/submit',
            data={
                'csrf_token': Request.csrf_token(self),
                'expensive_type': 'bienes_servicios',
                'user_id': str(user.id),
                'company_id': str(self.analytic.id),
                'is_more': '',
            },
            allow_redirects=False,
        )

    def _last_request_for(self, user):
        return self.env['portal.hr.expensive.request'].sudo().search(
            [('user_id', '=', user.id)], order='id desc', limit=1
        )

    def test_boss_request_goes_directly_to_purchase_responsible(self):
        self._submit(self.boss)
        expense = self._last_request_for(self.boss)
        self.assertEqual(expense.status, 'approved_purchase_responsible')

    def test_administrative_request_still_needs_boss_approval(self):
        # A petición del cliente: el Administrativo vuelve a necesitar la
        # aprobación del Jefe de Equipo, igual que un miembro normal.
        self._submit(self.administrative)
        expense = self._last_request_for(self.administrative)
        self.assertEqual(
            expense.status, 'approved_by_boss_group',
            "La solicitud de gasto del Administrativo debe pasar por la "
            "aprobación del Jefe de Equipo, igual que la de un miembro "
            "normal del equipo",
        )

    def test_team_member_request_still_needs_boss_approval(self):
        self._submit(self.team_member)
        expense = self._last_request_for(self.team_member)
        self.assertEqual(expense.status, 'approved_by_boss_group')


@tagged('post_install', '-at_install')
class TestExpenseDetailNoServerError(HttpCase, ExpenseRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'expense_detail_500_test'
        self._setup_expense_routing_team(
            boss_vals={'password': self.password},
            administrative_vals={'password': self.password},
        )
        self.expense = self.env['portal.hr.expensive.request'].create({
            'user_id': self.boss.id,
            'type': 'bienes_servicios',
            'project': self.analytic.id,
            'status': 'approved_by_boss_group',
        })

    def test_boss_can_open_detail_without_500(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open(f'/my/expenses/{self.expense.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/my/expenses/%d/approve' % self.expense.id, response.text)

    def test_administrative_can_open_detail_without_500(self):
        # El Administrativo no es el propietario ni el equip_boss literal
        # del registro, pero es el Administrativo de ese equipo de trabajo:
        # el bug de la plantilla afectaba aquí también.
        self.authenticate(self.administrative.login, self.password)
        response = self.url_open(f'/my/expenses/{self.expense.id}')
        self.assertEqual(response.status_code, 200)


@tagged('post_install', '-at_install')
class TestExpenseApproveRoute(HttpCase, ExpenseRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'expense_approve_route_test'
        self._setup_expense_routing_team(
            boss_vals={'password': self.password},
            administrative_vals={'password': self.password},
        )
        self.expense = self.env['portal.hr.expensive.request'].create({
            'user_id': self.team_member.id,
            'type': 'bienes_servicios',
            'project': self.analytic.id,
            'status': 'approved_by_boss_group',
        })

    def _approve_as(self, user):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/expenses/{self.expense.id}/approve',
            data={'csrf_token': Request.csrf_token(self)},
            allow_redirects=False,
        )

    def test_boss_can_approve_via_portal_route(self):
        response = self._approve_as(self.boss)
        self.assertTrue(
            response.headers.get('Location', '').endswith(
                f'/my/expenses/{self.expense.id}?success=approved'
            )
        )
        self.assertEqual(self.expense.status, 'approved_purchase_responsible')

    def test_administrative_can_approve_via_portal_route(self):
        response = self._approve_as(self.administrative)
        self.assertTrue(
            response.headers.get('Location', '').endswith(
                f'/my/expenses/{self.expense.id}?success=approved'
            )
        )
        self.assertEqual(self.expense.status, 'approved_purchase_responsible')


@tagged('post_install', '-at_install')
class TestExpenseToReviseRouting(TransactionCase, ExpenseRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self._setup_expense_routing_team()

    def _create_expense(self, requester, status):
        return self.env['portal.hr.expensive.request'].create({
            'user_id': requester.id,
            'type': 'bienes_servicios',
            'project': self.analytic.id,
            'status': status,
        })

    def test_administrative_resubmit_still_needs_boss_approval(self):
        # A petición del cliente: el reenvío del Administrativo vuelve a
        # pasar por el Jefe de Equipo, igual que un miembro normal.
        expense = self._create_expense(self.administrative, 'to_revise')
        expense.action_approve()
        self.assertEqual(expense.status, 'approved_by_boss_group')

    def test_team_member_resubmit_still_goes_to_boss_group(self):
        expense = self._create_expense(self.team_member, 'to_revise')
        expense.action_approve()
        self.assertEqual(expense.status, 'approved_by_boss_group')

    def test_administrative_sees_solicitar_revision_button_when_to_revise(self):
        # group_administrative implica group_equip_boss, así que sin la
        # exclusión explícita en _compute_show_solicitar_revision el
        # Administrativo se quedaría sin forma de reenviar su propia
        # solicitud rechazada.
        expense = self._create_expense(self.administrative, 'to_revise')
        expense = expense.with_user(self.administrative)
        self.assertTrue(expense.show_solicitar_revision)

    def test_boss_does_not_see_solicitar_revision_button_when_to_revise(self):
        expense = self._create_expense(self.boss, 'to_revise')
        expense = expense.with_user(self.boss)
        self.assertFalse(expense.show_solicitar_revision)
