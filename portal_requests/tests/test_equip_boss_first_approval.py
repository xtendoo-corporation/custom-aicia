# -*- coding: utf-8 -*-
"""Tests del nuevo primer estado "Aprobación del Jefe de Equipo".

Tanto las Solicitudes de Documentos (``document.approval``) como las
Solicitudes de Proyectos (``portal.project.request``) empiezan ahora en un
estado inicial que solo el Jefe de Equipo (o Administrativo) del grupo de
trabajo de la solicitud puede aprobar, antes de que el circuito continúe con
la aprobación final (Director I+D). Cubre tanto la lógica de modelo como la
ruta de portal real (``/my/documents/<id>/approve`` y
``/my/project_requests/<id>/approve``), en paralelo a como ya se probaba el
resto del circuito de aprobación (``test_document_resubmit*.py``,
``test_project_request_resubmit.py``).
"""
from odoo.exceptions import UserError
from odoo.http import Request
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDocumentEquipBossFirstApproval(TransactionCase):

    def setUp(self):
        super().setUp()
        self.type_approval = self.env.ref('portal_requests.type_approval_nda')
        equip_boss_group = self.env.ref('portal_requests.group_equip_boss')
        portal_group = self.env.ref('base.group_portal')
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Doc',
            'login': 'equip_boss_doc_first_test',
            'email': 'equip_boss_doc_first_test@example.com',
            'group_ids': [(6, 0, [equip_boss_group.id, portal_group.id])],
        })
        self.requester = self.env['res.users'].create({
            'name': 'Solicitante Doc',
            'login': 'requester_doc_first_test',
            'email': 'requester_doc_first_test@example.com',
            'group_ids': [(6, 0, [portal_group.id])],
        })
        administrative_group = self.env.ref('portal_requests.group_administrative')
        self.administrative = self.env['res.users'].create({
            'name': 'Administrativo Doc Estado',
            'login': 'administrative_doc_first_test',
            'email': 'administrative_doc_first_test@example.com',
            'group_ids': [(6, 0, [administrative_group.id])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Doc Estado',
            'code': 'DOCSTATE',
            'user_ids': [(6, 0, [self.boss.id, self.requester.id, self.administrative.id])],
            'equip_boss': self.boss.id,
            'administrative_id': self.administrative.id,
        })
        director_group = self.env.ref(
            'portal_requests.group_director_investigation_and_development')
        self.director = self.env['res.users'].create({
            'name': 'Director I+D Doc Estado',
            'login': 'director_id_doc_first_test',
            'email': 'director_id_doc_first_test@example.com',
            'group_ids': [(6, 0, [director_group.id])],
        })
        self.document = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Documento de prueba',
            'user_id': self.requester.id,
            'work_group_id': self.team.id,
        })

    def test_initial_status_is_equip_boss_approval(self):
        self.assertEqual(self.document.status, 'approved_by_equip_boss')

    def test_requester_without_group_cannot_advance_state(self):
        # El propio solicitante puede ver su documento, pero no puede
        # autoaprobarse el primer paso: le falta el grupo de Jefe de Equipo.
        self.document.with_user(self.requester).action_approve()
        self.assertEqual(
            self.document.status, 'approved_by_equip_boss',
            "Sin el grupo de Jefe de Equipo, action_approve no debe avanzar el estado",
        )

    def test_equip_boss_approval_advances_to_director_i_d(self):
        self.document.with_user(self.boss).action_approve()
        self.assertEqual(self.document.status, 'approved_by_director_i_d')

    def test_document_created_by_equip_boss_skips_first_step(self):
        # El propio Jefe de Equipo no necesita aprobarse a sí mismo: la
        # solicitud entra directamente en la aprobación del Director I+D.
        document = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Documento del propio Jefe de Equipo',
            'user_id': self.boss.id,
            'work_group_id': self.team.id,
        })
        self.assertEqual(document.status, 'approved_by_director_i_d')

    def test_administrative_created_by_self_stays_in_equip_boss_step(self):
        # El Administrativo SÍ pasa por la aprobación del Jefe de Equipo,
        # aunque comparta el grupo (no es el mismo rol que el Jefe de Equipo).
        document = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Documento del Administrativo',
            'user_id': self.administrative.id,
            'work_group_id': self.team.id,
        })
        self.assertEqual(document.status, 'approved_by_equip_boss')

    def test_administrative_cannot_approve_own_request(self):
        document = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Documento del Administrativo',
            'user_id': self.administrative.id,
            'work_group_id': self.team.id,
        })
        document.with_user(self.administrative).action_approve()
        self.assertEqual(
            document.status, 'approved_by_equip_boss',
            "El Administrativo no puede aprobarse su propia solicitud: debe "
            "hacerlo el Jefe de Equipo",
        )
        # El Jefe de Equipo (persona distinta) sí puede aprobarla.
        document.with_user(self.boss).action_approve()
        self.assertEqual(document.status, 'approved_by_director_i_d')

    def test_resubmit_restarts_equip_boss_own_document_at_skip_target(self):
        document = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Documento del propio Jefe de Equipo',
            'user_id': self.boss.id,
            'work_group_id': self.team.id,
        })
        self.assertEqual(document.status, 'approved_by_director_i_d')
        document.action_reject()
        document.action_resubmit()
        # Al reenviar, no debe volver a pasar por su propia aprobación.
        self.assertEqual(document.status, 'approved_by_director_i_d')


@tagged('post_install', '-at_install')
class TestDocumentEquipBossFirstApprovalHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.type_approval = self.env.ref('portal_requests.type_approval_nda')
        self.password = 'equip_boss_doc_http_test'
        equip_boss_group = self.env.ref('portal_requests.group_equip_boss')
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Doc HTTP',
            'login': 'equip_boss_doc_http_test',
            'password': self.password,
            'email': 'equip_boss_doc_http_test@example.com',
            'group_ids': [(6, 0, [equip_boss_group.id, self.env.ref('base.group_portal').id])],
        })
        self.requester = self.env['res.users'].create({
            'name': 'Solicitante Doc HTTP',
            'login': 'requester_doc_http_test',
            'password': self.password,
            'email': 'requester_doc_http_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.outsider = self.env['res.users'].create({
            'name': 'Ajeno Doc HTTP',
            'login': 'outsider_doc_http_test',
            'password': self.password,
            'email': 'outsider_doc_http_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Doc HTTP',
            'code': 'DOCFIRST',
            'user_ids': [(6, 0, [self.boss.id, self.requester.id])],
            'equip_boss': self.boss.id,
        })
        director_group = self.env.ref(
            'portal_requests.group_director_investigation_and_development')
        self.director = self.env['res.users'].create({
            'name': 'Director I+D Doc HTTP',
            'login': 'director_id_doc_http_test',
            'email': 'director_id_doc_http_test@example.com',
            'group_ids': [(6, 0, [director_group.id])],
        })
        self.document = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Documento de prueba HTTP',
            'user_id': self.requester.id,
            'work_group_id': self.team.id,
        })

    def _approve(self, user):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/documents/{self.document.id}/approve',
            data={'csrf_token': Request.csrf_token(self)},
            allow_redirects=False,
        )

    def test_team_boss_can_approve(self):
        response = self._approve(self.boss)
        self.assertTrue(
            response.headers.get('Location', '').endswith(
                f'/my/documents/{self.document.id}?success=equip_boss_approved'
            ),
        )
        self.assertEqual(self.document.status, 'approved_by_director_i_d')

    def test_outsider_cannot_approve(self):
        response = self._approve(self.outsider)
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.document.invalidate_recordset()
        self.assertEqual(self.document.status, 'approved_by_equip_boss')

    def test_template_shows_approve_button_to_team_boss(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open(f'/my/documents/{self.document.id}')
        self.assertIn(f'/my/documents/{self.document.id}/approve', response.text)


@tagged('post_install', '-at_install')
class TestProjectRequestEquipBossFirstApproval(TransactionCase):

    def setUp(self):
        super().setUp()
        equip_boss_group = self.env.ref('portal_requests.group_equip_boss')
        portal_group = self.env.ref('base.group_portal')
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Proyecto Estado',
            'login': 'equip_boss_project_first_test',
            'email': 'equip_boss_project_first_test@example.com',
            'group_ids': [(6, 0, [equip_boss_group.id, portal_group.id])],
        })
        self.outsider = self.env['res.users'].create({
            'name': 'Ajeno Proyecto Estado',
            'login': 'outsider_project_first_test',
            'email': 'outsider_project_first_test@example.com',
        })
        administrative_group = self.env.ref('portal_requests.group_administrative')
        self.administrative = self.env['res.users'].create({
            'name': 'Administrativo Proyecto Estado',
            'login': 'administrative_project_first_test',
            'email': 'administrative_project_first_test@example.com',
            'group_ids': [(6, 0, [administrative_group.id])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Proyecto Estado',
            'code': 'PROJSTATE',
            'user_ids': [(6, 0, [self.boss.id, self.administrative.id])],
            'equip_boss': self.boss.id,
            'administrative_id': self.administrative.id,
        })
        self.project_request = self.env['portal.project.request'].create({
            'user_id': self.boss.id,
            'company_id': self.env.company.id,
            'project_name': 'Proyecto de prueba',
            'type': 'new',
        })

    def test_initial_status_is_equip_boss_approval(self):
        self.assertEqual(self.project_request.status, 'approved_by_equip_boss')

    def test_final_approval_blocked_before_equip_boss_step(self):
        with self.assertRaises(UserError):
            self.project_request.action_approve()

    def test_user_without_group_cannot_approve_equip_boss_step(self):
        with self.assertRaises(UserError):
            self.project_request.with_user(self.outsider).action_approve_equip_boss()
        self.assertEqual(self.project_request.status, 'approved_by_equip_boss')

    def test_equip_boss_approval_advances_state(self):
        self.project_request.with_user(self.boss).action_approve_equip_boss()
        self.assertEqual(self.project_request.status, 'pending_review')

    def test_resubmit_restarts_equip_boss_step(self):
        self.project_request.with_user(self.boss).action_approve_equip_boss()
        self.project_request.action_reject()
        self.project_request.action_resubmit()
        self.assertEqual(self.project_request.status, 'approved_by_equip_boss')

    def test_project_created_by_equip_boss_with_team_skips_first_step(self):
        # El propio Jefe de Equipo no necesita aprobarse a sí mismo: la
        # solicitud queda pendiente directamente de la aprobación final.
        project_request = self.env['portal.project.request'].create({
            'user_id': self.boss.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'project_name': 'Proyecto del propio Jefe de Equipo',
            'type': 'new',
        })
        self.assertEqual(project_request.status, 'pending_review')

    def test_administrative_created_by_self_stays_in_equip_boss_step(self):
        project_request = self.env['portal.project.request'].create({
            'user_id': self.administrative.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'project_name': 'Proyecto del Administrativo',
            'type': 'new',
        })
        self.assertEqual(project_request.status, 'approved_by_equip_boss')

    def test_administrative_cannot_approve_own_project_request(self):
        project_request = self.env['portal.project.request'].create({
            'user_id': self.administrative.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'project_name': 'Proyecto del Administrativo',
            'type': 'new',
        })
        with self.assertRaises(UserError):
            project_request.with_user(self.administrative).action_approve_equip_boss()
        self.assertEqual(project_request.status, 'approved_by_equip_boss')
        # El Jefe de Equipo (persona distinta) sí puede aprobarla.
        project_request.with_user(self.boss).action_approve_equip_boss()
        self.assertEqual(project_request.status, 'pending_review')


@tagged('post_install', '-at_install')
class TestProjectRequestEquipBossFirstApprovalHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = 'equip_boss_project_http_test'
        equip_boss_group = self.env.ref('portal_requests.group_equip_boss')
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Proyecto HTTP Estado',
            'login': 'equip_boss_project_http_test',
            'password': self.password,
            'email': 'equip_boss_project_http_test@example.com',
            'group_ids': [(6, 0, [equip_boss_group.id, self.env.ref('base.group_portal').id])],
        })
        self.requester = self.env['res.users'].create({
            'name': 'Solicitante Proyecto HTTP Estado',
            'login': 'requester_project_http_test',
            'password': self.password,
            'email': 'requester_project_http_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.outsider = self.env['res.users'].create({
            'name': 'Ajeno Proyecto HTTP Estado',
            'login': 'outsider_project_http_test',
            'password': self.password,
            'email': 'outsider_project_http_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Proyecto HTTP Estado',
            'code': 'PROJFIRST',
            'user_ids': [(6, 0, [self.boss.id, self.requester.id])],
            'equip_boss': self.boss.id,
        })
        self.project_request = self.env['portal.project.request'].create({
            'user_id': self.requester.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'project_name': 'Proyecto HTTP de prueba',
            'type': 'new',
        })

    def _approve(self, user):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/project_requests/{self.project_request.id}/approve',
            data={'csrf_token': Request.csrf_token(self)},
            allow_redirects=False,
        )

    def test_team_boss_can_approve(self):
        response = self._approve(self.boss)
        self.assertTrue(
            response.headers.get('Location', '').endswith(
                f'/my/project_requests/{self.project_request.id}?success=equip_boss_approved'
            ),
        )
        self.assertEqual(self.project_request.status, 'pending_review')

    def test_outsider_cannot_approve(self):
        response = self._approve(self.outsider)
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.project_request.invalidate_recordset()
        self.assertEqual(self.project_request.status, 'approved_by_equip_boss')

    def test_requester_cannot_approve_own_request(self):
        # El solicitante puede ver/gestionar su solicitud, pero no es el
        # Jefe de Equipo del grupo: no puede aprobar este paso.
        response = self._approve(self.requester)
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.project_request.invalidate_recordset()
        self.assertEqual(self.project_request.status, 'approved_by_equip_boss')

    def test_template_shows_approve_button_to_team_boss(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open(f'/my/project_requests/{self.project_request.id}')
        self.assertIn(f'/my/project_requests/{self.project_request.id}/approve', response.text)
