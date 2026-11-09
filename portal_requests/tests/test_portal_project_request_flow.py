# -*- coding: utf-8 -*-
"""Recorrido del portal para la solicitud de apertura de proyecto.

Comprueba con usuarios portal reales que el menú de solicitudes aparece en
/my y que el Jefe de Equipo puede abrir el formulario y crear una solicitud
de apertura de proyecto, solo con las dependencias declaradas del módulo.
"""
from odoo.http import Request
from odoo.tests import HttpCase, tagged

from .test_project_request_members import ProjectRequestMembersSetupMixin


@tagged('post_install', '-at_install')
class TestPortalProjectRequestFlow(HttpCase, ProjectRequestMembersSetupMixin):

    def setUp(self):
        super().setUp()
        self._setup_team()
        self.member_a.password = 'project_flow_member_test'

    def test_equip_boss_sees_requests_menu(self):
        self.authenticate(self.boss.login, 'project_members_http_test')
        response = self.url_open('/my')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/my/project_requests', response.text)
        self.assertIn('/my/expenses', response.text)
        self.assertIn('/my/invoices', response.text)

    def test_member_sees_requests_menu_without_project_card(self):
        self.authenticate(self.member_a.login, 'project_flow_member_test')
        response = self.url_open('/my')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/my/expenses', response.text)
        self.assertNotIn('/my/project_requests', response.text)

    def test_equip_boss_creates_project_opening_request(self):
        self.authenticate(self.boss.login, 'project_members_http_test')
        form = self.url_open('/portal/project_request')
        self.assertEqual(form.status_code, 200)
        response = self.url_open('/portal/project_request/submit', data={
            'csrf_token': Request.csrf_token(self),
            'type_id': 'new',
            'company_id': str(self.env.company.id),
            'work_group_id': str(self.team.id),
            'partner_id_char': 'Cliente apertura',
            'project_name': 'Proyecto Apertura Portal',
            'date_start': '2026-01-01',
            'date_end': '2026-12-31',
        }, allow_redirects=False)
        self.assertIn(response.status_code, (200, 302, 303))
        project_request = self.env['portal.project.request'].sudo().search(
            [('user_id', '=', self.boss.id), ('project_name', '=', 'Proyecto Apertura Portal')],
        )
        self.assertEqual(len(project_request), 1)
        self.assertEqual(project_request.type, 'new')
        self.assertEqual(project_request.work_group_id, self.team)
