# -*- coding: utf-8 -*-
"""Test del enrutado de aprobación de las Solicitudes de Factura.

A petición del cliente, el Administrativo vuelve a necesitar la aprobación
del Jefe de Equipo (tanto al solicitar como al reenviar tras un rechazo),
igual que un miembro normal del equipo: solo el propio Jefe de Equipo va
directo al Responsable de Clientes.

Como group_administrative implica group_equip_boss (ver
res_group_data.xml), el botón "Solicitar Revisión" -oculto para cualquiera
con group_equip_boss- se quedaba oculto también para el Administrativo,
dejando sin forma de reenviar una solicitud propia rechazada.
_compute_show_solicitar_revision excluye ahora explícitamente a
group_administrative de ese ocultamiento.
"""
from odoo.http import Request
from odoo.tests import HttpCase, TransactionCase, tagged


class InvoiceRoutingSetupMixin:
    """Monta un equipo con Jefe de Equipo, Administrativo y un miembro
    normal, más el proyecto/cliente necesarios para solicitar una factura."""

    def _setup_invoice_routing_team(self, boss_vals=None, administrative_vals=None,
                                     team_member_vals=None):
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Factura',
            'login': 'invoice_boss_test',
            'email': 'invoice_boss_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_equip_boss').id,
                self.env.ref('base.group_portal').id,
            ])],
            **(boss_vals or {}),
        })
        self.administrative = self.env['res.users'].create({
            'name': 'Administrativo Factura',
            'login': 'invoice_administrative_test',
            'email': 'invoice_administrative_test@example.com',
            # group_administrative ya implica group_equip_boss + base.group_portal.
            'group_ids': [(6, 0, [self.env.ref('portal_requests.group_administrative').id])],
            **(administrative_vals or {}),
        })
        self.team_member = self.env['res.users'].create({
            'name': 'Miembro de Equipo Factura',
            'login': 'invoice_team_member_test',
            'email': 'invoice_team_member_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
            **(team_member_vals or {}),
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Factura',
            'code': 'INVROUTE',
            'user_ids': [(6, 0, [self.boss.id, self.administrative.id, self.team_member.id])],
            'equip_boss': self.boss.id,
            'administrative_id': self.administrative.id,
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Factura Routing'})
        self.analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Factura Routing',
            'plan_id': plan.id,
            'work_group_id': self.team.id,
        })
        self.partner = self.env['res.partner'].create({'name': 'Cliente de Prueba Factura'})


@tagged('post_install', '-at_install')
class TestInvoiceRequestSubmitRouting(HttpCase, InvoiceRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'invoice_routing_http_test'
        self._setup_invoice_routing_team(
            boss_vals={'password': self.password},
            administrative_vals={'password': self.password},
            team_member_vals={'password': self.password},
        )

    def _submit(self, user):
        self.authenticate(user.login, self.password)
        return self.url_open(
            '/portal/invoice_request/submit',
            data={
                'csrf_token': Request.csrf_token(self),
                'company_id': str(self.analytic.id),
                'partner_id': str(self.partner.id),
                'amount': '100.0',
                'notes': 'Factura de prueba',
                'move_type': 'out_invoice',
                'date': '2026-01-01',
            },
            allow_redirects=False,
        )

    def _last_request_for(self, user):
        return self.env['portal.invoice.request'].sudo().search(
            [('user_id', '=', user.id)], order='id desc', limit=1
        )

    def test_boss_request_goes_directly_to_client_responsible(self):
        response = self._submit(self.boss)
        self.assertTrue(
            response.headers.get('Location', '').endswith('/my/invoices/thank-you')
        )
        invoice_request = self._last_request_for(self.boss)
        self.assertEqual(invoice_request.status, 'approved_by_client_responsible')

    def test_administrative_request_still_needs_boss_approval(self):
        # A petición del cliente: el Administrativo vuelve a necesitar la
        # aprobación del Jefe de Equipo, igual que un miembro normal.
        response = self._submit(self.administrative)
        self.assertTrue(
            response.headers.get('Location', '').endswith('/my/invoices/thank-you')
        )
        invoice_request = self._last_request_for(self.administrative)
        self.assertEqual(
            invoice_request.status, 'approved_by_boss_group',
            "La solicitud del Administrativo debe pasar por la aprobación "
            "del Jefe de Equipo, igual que la de un miembro normal",
        )

    def test_team_member_request_still_needs_boss_approval(self):
        # Caso no afectado por el fix: un miembro normal del equipo sigue
        # necesitando la aprobación del Jefe de Equipo/Administrativo.
        self._submit(self.team_member)
        invoice_request = self._last_request_for(self.team_member)
        self.assertEqual(invoice_request.status, 'approved_by_boss_group')


@tagged('post_install', '-at_install')
class TestInvoiceRequestRejectWizardRouting(TransactionCase, InvoiceRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self._setup_invoice_routing_team()

    def _create_request(self, requester, status):
        return self.env['portal.invoice.request'].create({
            'user_id': requester.id,
            'analytic_id': self.analytic.id,
            'partner_id': self.partner.id,
            'amount': 100.0,
            'move_type': 'out_invoice',
            'status': status,
        })

    def _reject(self, invoice_request):
        wizard = self.env['invoice.request.reject.wizard'].create({
            'request_id': invoice_request.id,
            'descripcion': 'Motivo de prueba',
        })
        wizard.action_accept()

    def test_reject_boss_request_skips_to_revise(self):
        invoice_request = self._create_request(self.boss, 'approved_by_client_responsible')
        self._reject(invoice_request)
        self.assertEqual(invoice_request.status, 'approved_by_boss_group')

    def test_reject_administrative_request_goes_to_revise(self):
        # A petición del cliente: el rechazo de una solicitud del
        # Administrativo vuelve a quedar en 'to_revise', igual que la de un
        # miembro normal.
        invoice_request = self._create_request(self.administrative, 'approved_by_client_responsible')
        self._reject(invoice_request)
        self.assertEqual(invoice_request.status, 'to_revise')

    def test_reject_team_member_request_goes_to_revise(self):
        invoice_request = self._create_request(self.team_member, 'approved_by_client_responsible')
        self._reject(invoice_request)
        self.assertEqual(invoice_request.status, 'to_revise')

    def test_administrative_sees_solicitar_revision_button_when_to_revise(self):
        # group_administrative implica group_equip_boss, así que sin la
        # exclusión explícita en _compute_show_solicitar_revision el
        # Administrativo se quedaría sin forma de reenviar su propia
        # solicitud rechazada.
        invoice_request = self._create_request(self.administrative, 'to_revise')
        invoice_request = invoice_request.with_user(self.administrative)
        self.assertTrue(invoice_request.show_solicitar_revision)

    def test_boss_does_not_see_solicitar_revision_button_when_to_revise(self):
        invoice_request = self._create_request(self.boss, 'to_revise')
        invoice_request = invoice_request.with_user(self.boss)
        self.assertFalse(invoice_request.show_solicitar_revision)
