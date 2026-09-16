# -*- coding: utf-8 -*-
"""Test del campo "Miembros del Proyecto" en la Solicitud de Nuevo Proyecto.

Pedido del cliente: debajo de "Grupo de trabajo" debe poder seleccionarse uno
o varios usuarios de ese grupo, que pasan a la solicitud creada y, si se
aprueba, también al proyecto (cuenta analítica) resultante.
"""
from odoo.http import Request
from odoo.tests import HttpCase, TransactionCase, tagged


class ProjectRequestMembersSetupMixin:

    def _setup_team(self):
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Proyecto',
            'login': 'project_members_boss_test',
            'email': 'project_members_boss_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_equip_boss').id,
                self.env.ref('base.group_portal').id,
            ])],
            'password': 'project_members_http_test',
        })
        self.member_a = self.env['res.users'].create({
            'name': 'Miembro A',
            'login': 'project_member_a_test',
            'email': 'project_member_a_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.member_b = self.env['res.users'].create({
            'name': 'Miembro B',
            'login': 'project_member_b_test',
            'email': 'project_member_b_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.outsider = self.env['res.users'].create({
            'name': 'Ajeno al Equipo',
            'login': 'project_outsider_test',
            'email': 'project_outsider_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Proyecto Miembros',
            'code': 'PROJMEMBERS',
            'user_ids': [(6, 0, [self.boss.id, self.member_a.id, self.member_b.id])],
            'equip_boss': self.boss.id,
        })
        self.partner = self.env['res.partner'].create({'name': 'Cliente Proyecto Miembros'})
        # create_new_project() busca el plan analítico 'AICIA' por nombre;
        # en un entorno de test aislado puede no existir todavía.
        if not self.env['account.analytic.plan'].sudo().search([('name', '=', 'AICIA')], limit=1):
            self.env['account.analytic.plan'].sudo().create({'name': 'AICIA'})


@tagged('post_install', '-at_install')
class TestProjectRequestMembersModel(TransactionCase, ProjectRequestMembersSetupMixin):

    def setUp(self):
        super().setUp()
        self._setup_team()

    def test_member_domain_reflects_work_group_members(self):
        request = self.env['portal.project.request'].create({
            'user_id': self.boss.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'type': 'new',
        })
        self.assertEqual(set(request.member_domain.ids), {self.boss.id, self.member_a.id, self.member_b.id})

    def test_approve_copies_members_to_created_project(self):
        request = self.env['portal.project.request'].create({
            'user_id': self.boss.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'partner_id': self.partner.id,
            'project_name': 'Proyecto Con Miembros',
            'member_ids': [(6, 0, [self.member_a.id, self.member_b.id])],
            'type': 'new',
        })
        request.action_approve()
        self.assertEqual(
            set(request.created_analytic_id.member_ids.ids),
            {self.member_a.id, self.member_b.id},
        )

    def test_approve_without_members_leaves_project_members_empty(self):
        request = self.env['portal.project.request'].create({
            'user_id': self.boss.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'partner_id': self.partner.id,
            'project_name': 'Proyecto Sin Miembros',
            'type': 'new',
        })
        request.action_approve()
        self.assertFalse(request.created_analytic_id.member_ids)


@tagged('post_install', '-at_install')
class TestProjectRequestMembersSubmit(HttpCase, ProjectRequestMembersSetupMixin):

    def setUp(self):
        super().setUp()
        self._setup_team()

    def _submit(self, member_ids):
        self.authenticate(self.boss.login, 'project_members_http_test')
        data = [
            ('csrf_token', Request.csrf_token(self)),
            ('type_id', 'new'),
            ('company_id', str(self.env.company.id)),
            ('work_group_id', str(self.team.id)),
            ('partner_id_char', 'Cliente de prueba'),
            ('project_name', 'Proyecto HTTP Miembros'),
            ('date_start', '2026-01-01'),
            ('date_end', '2026-12-31'),
        ]
        for member_id in member_ids:
            data.append(('member_ids[]', str(member_id)))
        return self.url_open('/portal/project_request/submit', data=data, allow_redirects=False)

    def _last_request(self):
        return self.env['portal.project.request'].sudo().search(
            [('user_id', '=', self.boss.id)], order='id desc', limit=1
        )

    def test_submit_saves_selected_members(self):
        self._submit([self.member_a.id, self.member_b.id])
        request = self._last_request()
        self.assertEqual(set(request.member_ids.ids), {self.member_a.id, self.member_b.id})

    def test_submit_ignores_member_outside_work_group(self):
        # Defensa contra un POST manipulado: el filtrado del <select> por
        # grupo es solo en el navegador (JS), así que el servidor debe
        # validar igualmente que los miembros pertenecen al grupo elegido.
        self._submit([self.member_a.id, self.outsider.id])
        request = self._last_request()
        self.assertEqual(request.member_ids.ids, [self.member_a.id])

    def test_form_lists_all_team_members_not_just_self(self):
        # Bug real: sin sudo(), un usuario portal no tiene acceso de lectura
        # a la ficha de otros usuarios, así que group.user_ids solo
        # devolvía al propio usuario logueado en vez de a los 4 del equipo.
        self.authenticate(self.boss.login, 'project_members_http_test')
        response = self.url_open('/portal/project_request')
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn(self.boss.name, html)
        self.assertIn(self.member_a.name, html)
        self.assertIn(self.member_b.name, html)

    def test_detail_page_shows_selected_members(self):
        # Pedido del cliente: los miembros elegidos deben verse también en
        # el detalle de "Mis Solicitudes" del portal, no solo quedar
        # guardados internamente.
        self._submit([self.member_a.id, self.member_b.id])
        project_request = self._last_request()
        self.authenticate(self.boss.login, 'project_members_http_test')
        response = self.url_open(f'/my/project_requests/{project_request.id}')
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn(self.member_a.name, html)
        self.assertIn(self.member_b.name, html)
