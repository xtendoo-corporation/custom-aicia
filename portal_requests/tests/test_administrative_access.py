# -*- coding: utf-8 -*-
"""Tests del perfil "Administrativo".

Este perfil implica group_equip_boss, por lo que hereda automáticamente
todas sus funciones (aprobar/rechazar solicitudes de su equipo, ver en el
portal "Mis Proyectos" los mismos proyectos y solicitudes que el Jefe de
Equipo, etc). La única diferencia es que no debe ver la información
económica de los proyectos (saldos/presupuestos): puede leer la cuenta
analítica de su equipo (a nivel de datos, vía
rule_analytic_account_work_group_boss), pero esos campos económicos se
ocultan en la plantilla del portal mediante _hide_project_financials(), que
queda fuera del alcance de un TransactionCase.

IMPORTANTE: en `portal.work.group`, "Jefe de Equipo" (equip_boss) y
"Administrativo" (administrative_id) son DOS personas distintas en el caso
general (el administrativo NO tiene por qué ser también el jefe de
equipo). Por eso el setUp usa usuarios separados para cada rol: así se
comprueba que el administrativo ve los proyectos/solicitudes de su equipo
por ser el administrative_id del grupo, no porque "de casualidad" también
sea el equip_boss.
"""
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.portal_requests.controllers.portal_main import PortalRequestsCustomerPortal


@tagged('post_install', '-at_install')
class TestAdministrativeAccess(TransactionCase):

    def setUp(self):
        super().setUp()
        self.type_approval = self.env.ref('portal_requests.type_approval_nda')
        administrative_group = self.env.ref('portal_requests.group_administrative')
        equip_boss_group = self.env.ref('portal_requests.group_equip_boss')

        self.boss_user = self.env['res.users'].create({
            'name': 'Jefe de Equipo Restringido',
            'login': 'equip_boss_restricted_test',
            'email': 'equip_boss_restricted_test@example.com',
            'group_ids': [(6, 0, [equip_boss_group.id])],
        })
        self.administrative_user = self.env['res.users'].create({
            'name': 'Usuario Administrativo',
            'login': 'administrative_test',
            'email': 'administrative_test@example.com',
            'group_ids': [(6, 0, [administrative_group.id])],
        })

        # El administrativo NO es el jefe de equipo: son dos personas
        # distintas, ambas miembros del equipo (como en el uso real).
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Restringido', 'code': 'EQR',
            'user_ids': [(6, 0, [self.boss_user.id, self.administrative_user.id])],
            'equip_boss': self.boss_user.id,
            'administrative_id': self.administrative_user.id,
        })
        self.other_team = self.env['portal.work.group'].create({
            'name': 'Otro Equipo', 'code': 'EQO',
        })

        plan = self.env['account.analytic.plan'].create({'name': 'Plan'})
        self.analytic_own_team = self.env['account.analytic.account'].create({
            'name': 'Proyecto Equipo Restringido', 'plan_id': plan.id,
            'work_group_id': self.team.id,
        })

        self.doc_own_team = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Doc equipo restringido',
            'work_group_id': self.team.id,
        })

    def test_implies_equip_boss_group(self):
        # El perfil restringido conserva todas las funciones del Jefe de
        # Equipo porque implica ese grupo.
        self.assertTrue(
            self.administrative_user.has_group('portal_requests.group_equip_boss'))
        self.assertTrue(self.administrative_user.has_group('base.group_portal'))

    def test_keeps_functional_access_to_team_documents(self):
        # Misma función que el Jefe de Equipo: puede leer/escribir los
        # documentos de su equipo (rule_equip_boss_company, heredada, basada
        # en la pertenencia al equipo vía user_ids).
        visible = self.env['document.approval'].with_user(
            self.administrative_user).search([])
        self.assertIn(self.doc_own_team, visible)
        self.doc_own_team.with_user(self.administrative_user).check_access('write')

    def test_sees_team_analytic_account_as_administrative_not_boss(self):
        # El administrativo ve la cuenta analítica de su equipo aunque NO
        # sea el equip_boss (es una persona distinta), porque la regla
        # rule_analytic_account_work_group_boss también comprueba
        # work_group_administrative_id. Los campos económicos se ocultan en
        # la plantilla del portal (_hide_project_financials), no a nivel de
        # acceso al registro.
        self.assertNotEqual(self.team.equip_boss, self.administrative_user)
        self.assertEqual(self.team.administrative_id, self.administrative_user)
        visible = self.env['account.analytic.account'].with_user(
            self.administrative_user).search([])
        self.assertIn(self.analytic_own_team, visible)
        self.analytic_own_team.with_user(
            self.administrative_user).check_access('read')

    def test_hide_project_financials_only_for_administrative(self):
        # _hide_project_financials() es el punto único donde se oculta la
        # info económica (saldo/presupuesto) en la plantilla del portal.
        # Debe aplicar al Administrativo mismo aunque implique group_equip_boss...
        controller = PortalRequestsCustomerPortal()
        self.assertTrue(
            controller._hide_project_financials(self.administrative_user))
        # ...pero no a un Jefe de Equipo normal, que sigue viendo esos datos.
        self.assertFalse(controller._hide_project_financials(self.boss_user))

    def test_work_group_is_boss_or_administrative(self):
        # El helper central usado en todos los controladores debe reconocer
        # tanto al Jefe de Equipo como al Administrativo del grupo, y a
        # nadie más.
        self.assertTrue(self.team._is_boss_or_administrative(self.boss_user))
        self.assertTrue(self.team._is_boss_or_administrative(self.administrative_user))
        outsider = self.env['res.users'].create({
            'name': 'Ajeno al Equipo',
            'login': 'outsider_test',
            'email': 'outsider_test@example.com',
        })
        self.assertFalse(self.team._is_boss_or_administrative(outsider))
        # Un recordset vacío (p.ej. document.work_group_id sin grupo) no
        # debe romper, simplemente no es boss/administrativo de nada.
        empty = self.env['portal.work.group']
        self.assertFalse(empty._is_boss_or_administrative(self.administrative_user))

    def test_boss_or_administrative_domain_finds_team_by_administrative_id(self):
        # El dominio usado para las búsquedas (listados de proyectos,
        # documentos, selector de proyectos al crear solicitudes...) debe
        # encontrar el equipo tanto por equip_boss como por
        # administrative_id.
        WorkGroup = self.env['portal.work.group']
        found_via_admin = WorkGroup.search(
            WorkGroup._boss_or_administrative_domain(self.administrative_user))
        self.assertIn(self.team, found_via_admin)
        found_via_boss = WorkGroup.search(
            WorkGroup._boss_or_administrative_domain(self.boss_user))
        self.assertIn(self.team, found_via_boss)

    def test_invoice_request_administrative_id_field(self):
        # El campo related administrative_id en portal.invoice.request debe
        # reflejar el administrativo del grupo de trabajo del proyecto, para
        # que _can_access_invoice_request() y el listado de "Mis Facturas"
        # también lo reconozcan.
        partner = self.env['res.partner'].create({'name': 'Cliente de Prueba'})
        invoice_request = self.env['portal.invoice.request'].create({
            'user_id': self.env.user.id,
            'analytic_id': self.analytic_own_team.id,
            'partner_id': partner.id,
            'amount': 100.0,
            'move_type': 'out_invoice',
        })
        self.assertEqual(invoice_request.equip_boss, self.boss_user)
        self.assertEqual(invoice_request.administrative_id, self.administrative_user)
