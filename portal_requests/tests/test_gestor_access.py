# -*- coding: utf-8 -*-
"""Tests de las reglas de acceso del rol "Gestor".

El Gestor es un usuario de portal que puede ver y crear solicitudes de su equipo
de trabajo, pero solo de su equipo. Además puede leer las cuentas analíticas de su
equipo (necesario para seleccionarlas al crear solicitudes) y ninguna otra.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGestorAccess(TransactionCase):

    def setUp(self):
        super().setUp()
        self.type_approval = self.env.ref('portal_requests.type_approval_nda')

        # Gestor: usuario de portal en el grupo Gestor.
        manager_group = self.env.ref('portal_requests.group_manager')
        self.gestor = self.env['res.users'].create({
            'name': 'Gestor Equipo A',
            'login': 'gestor_a_test',
            'email': 'gestor_a_test@example.com',
            'group_ids': [(6, 0, [manager_group.id])],
        })

        # Equipo del Gestor y equipo ajeno.
        self.team_a = self.env['portal.work.group'].create({
            'name': 'Equipo A', 'code': 'EQA',
            'user_ids': [(6, 0, [self.gestor.id])],
        })
        self.team_b = self.env['portal.work.group'].create({
            'name': 'Equipo B', 'code': 'EQB',
        })

        plan = self.env['account.analytic.plan'].create({'name': 'Plan'})
        self.analytic_a = self.env['account.analytic.account'].create({
            'name': 'Proyecto A', 'plan_id': plan.id,
            'work_group_id': self.team_a.id,
        })
        self.analytic_b = self.env['account.analytic.account'].create({
            'name': 'Proyecto B', 'plan_id': plan.id,
            'work_group_id': self.team_b.id,
        })

        # Documentos: uno del equipo del Gestor y otro ajeno.
        self.doc_team_a = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Doc equipo A',
            'work_group_id': self.team_a.id,
        })
        self.doc_team_b = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Doc equipo B',
            'work_group_id': self.team_b.id,
        })

    def test_gestor_is_portal_user(self):
        # El grupo Gestor implica portal: nunca es un usuario interno.
        self.assertTrue(self.gestor.has_group('base.group_portal'))
        self.assertFalse(self.gestor.has_group('base.group_user'))

    def test_gestor_sees_own_team_documents(self):
        visible = self.env['document.approval'].with_user(self.gestor).search([])
        self.assertIn(self.doc_team_a, visible)

    def test_gestor_cannot_see_other_team_documents(self):
        visible = self.env['document.approval'].with_user(self.gestor).search([])
        self.assertNotIn(self.doc_team_b, visible)
        with self.assertRaises(AccessError):
            self.doc_team_b.with_user(self.gestor).check_access('read')

    def test_gestor_can_create_document_for_team(self):
        doc = self.env['document.approval'].with_user(self.gestor).create({
            'type_id': self.type_approval.id,
            'description': 'Nuevo del gestor',
            'work_group_id': self.team_a.id,
        })
        self.assertTrue(doc.exists())

    def test_gestor_reads_only_own_team_analytics(self):
        # Puede leer las analíticas de su equipo (para seleccionarlas al crear).
        visible = self.env['account.analytic.account'].with_user(
            self.gestor).search([])
        self.assertIn(self.analytic_a, visible)
        # Pero no las de otros equipos.
        self.assertNotIn(self.analytic_b, visible)

    def test_gestor_is_not_project_responsible(self):
        # El Gestor no es responsable ni jefe: las vistas económicas (saldos,
        # históricos) se filtran por esas condiciones en los controladores, por
        # lo que quedan vacías para el Gestor.
        self.assertNotEqual(self.analytic_a.responsible_id, self.gestor)
        self.assertNotEqual(self.team_a.equip_boss, self.gestor)
