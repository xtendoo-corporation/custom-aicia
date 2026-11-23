# -*- coding: utf-8 -*-
"""Tests del perfil "Secretaria".

Usuario externo (portal) que hace las tareas administrativas de todos los
grupos de trabajo: un Administrativo global que, además, ve la información
económica. Se comprueba que:
- es usuario portal y conserva las restricciones del Administrativo (no
  aprueba ningún paso del circuito);
- ve y puede solicitar para todos los grupos de trabajo y proyectos;
- ve saldos, presupuestos y el histórico de pagos de todos los proyectos;
- el Administrativo y el Jefe de Equipo mantienen su alcance de siempre.
"""
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.portal_requests.controllers.portal_main import PortalRequestsCustomerPortal


class SecretaryAccessCommon:
    """Datos comunes: dos grupos de trabajo con su Jefe de Equipo y su
    Administrativo, y una Secretaria que no pertenece a ninguno."""

    password = 'secretary_access_test'

    @classmethod
    def _create_user(cls, login, group_xmlid):
        return cls.env['res.users'].create({
            'name': login,
            'login': login,
            'password': cls.password,
            'email': f'{login}@example.com',
            'group_ids': [(6, 0, [cls.env.ref(group_xmlid).id])],
        })

    @classmethod
    def _create_secretary_data(cls):
        cls.secretary = cls._create_user('secretary_test', 'portal_requests.group_secretary')
        cls.administrative = cls._create_user(
            'secretary_administrative_test', 'portal_requests.group_administrative')
        cls.boss = cls._create_user('secretary_boss_test', 'portal_requests.group_equip_boss')
        cls.other_boss = cls._create_user(
            'secretary_other_boss_test', 'portal_requests.group_equip_boss')

        WorkGroup = cls.env['portal.work.group']
        cls.team = WorkGroup.create({
            'name': 'Equipo Secretaria A', 'code': 'SEA',
            'user_ids': [(6, 0, [cls.boss.id, cls.administrative.id])],
            'equip_boss': cls.boss.id,
            'administrative_id': cls.administrative.id,
        })
        cls.other_team = WorkGroup.create({
            'name': 'Equipo Secretaria B', 'code': 'SEB',
            'user_ids': [(6, 0, [cls.other_boss.id])],
            'equip_boss': cls.other_boss.id,
        })

        plan = cls.env['account.analytic.plan'].create({'name': 'Plan Secretaria'})
        Analytic = cls.env['account.analytic.account']
        # Con compañía, como en producción: el saldo del portal se formatea
        # con su moneda.
        cls.project = Analytic.create({
            'name': 'Proyecto Secretaria A', 'plan_id': plan.id,
            'company_id': cls.env.company.id,
            'work_group_id': cls.team.id, 'responsible_id': cls.boss.id,
        })
        cls.other_project = Analytic.create({
            'name': 'Proyecto Secretaria B', 'plan_id': plan.id,
            'company_id': cls.env.company.id,
            'work_group_id': cls.other_team.id, 'responsible_id': cls.other_boss.id,
        })


@tagged('post_install', '-at_install')
class TestSecretaryAccess(SecretaryAccessCommon, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_secretary_data()
        cls.WorkGroup = cls.env['portal.work.group']
        cls.other_document = cls.env['document.approval'].create({
            'type_id': cls.env.ref('portal_requests.type_approval_nda').id,
            'description': 'Documento del equipo B',
            'user_id': cls.other_boss.id,
            'work_group_id': cls.other_team.id,
        })

    def test_is_external_administrative_profile(self):
        self.assertTrue(self.secretary.share)
        self.assertTrue(self.secretary.has_group('base.group_portal'))
        self.assertTrue(self.secretary.has_group('portal_requests.group_administrative'))
        self.assertTrue(self.secretary.has_group('portal_requests.group_equip_boss'))
        self.assertFalse(self.secretary.has_group('base.group_user'))

    def test_sees_all_work_groups_only_for_global_profiles(self):
        self.assertTrue(self.WorkGroup._sees_all_work_groups(self.secretary))
        admin = self.env['res.users'].create({
            'name': 'Admin AICIA', 'login': 'secretary_aicia_admin_test',
            'group_ids': [(6, 0, [self.env.ref('portal_requests.group_aicia_admin').id])],
        })
        self.assertTrue(self.WorkGroup._sees_all_work_groups(admin))
        self.assertFalse(self.WorkGroup._sees_all_work_groups(self.administrative))
        self.assertFalse(self.WorkGroup._sees_all_work_groups(self.boss))

    def test_team_visibility_covers_every_work_group(self):
        groups = self.WorkGroup.search(self.WorkGroup._boss_or_administrative_domain(self.secretary))
        self.assertIn(self.team, groups)
        self.assertIn(self.other_team, groups)
        self.assertTrue(self.other_team._is_boss_or_administrative(self.secretary))
        # El Administrativo sigue limitado a su propio equipo.
        groups = self.WorkGroup.search(
            self.WorkGroup._boss_or_administrative_domain(self.administrative))
        self.assertIn(self.team, groups)
        self.assertNotIn(self.other_team, groups)

    def test_can_request_for_any_work_group(self):
        groups = self.WorkGroup.search(self.WorkGroup._requestable_domain(self.secretary))
        self.assertIn(self.team, groups)
        self.assertIn(self.other_team, groups)
        # Un miembro solo puede solicitar para sus grupos.
        groups = self.WorkGroup.search(self.WorkGroup._requestable_domain(self.administrative))
        self.assertEqual(groups, self.team)

    def test_never_approves_equip_boss_step(self):
        self.assertFalse(self.team._is_equip_boss_step_approver(self.secretary))
        self.assertFalse(self.other_team._is_equip_boss_step_approver(self.secretary))
        self.assertFalse(self.WorkGroup._is_equip_boss_step_approver(self.secretary))
        self.assertNotIn(self.secretary, self.WorkGroup._equip_boss_step_recipients())

    def test_invoice_request_as_requester_goes_to_team_boss(self):
        partner = self.env['res.partner'].create({'name': 'Cliente Secretaria'})
        invoice_request = self.env['portal.invoice.request'].create({
            'user_id': self.secretary.id,
            'analytic_id': self.other_project.id,
            'partner_id': partner.id,
            'amount': 250.0,
            'move_type': 'out_invoice',
            'status': 'approved_by_boss_group',
        })
        self.assertEqual(invoice_request.user_id, self.secretary)
        self.assertEqual(invoice_request.work_group_id, self.other_team)
        self.assertFalse(invoice_request.with_user(self.secretary).show_approve_button)
        self.assertTrue(invoice_request.with_user(self.other_boss).show_approve_button)

    def test_shows_project_financials(self):
        controller = PortalRequestsCustomerPortal()
        self.assertFalse(controller._hide_project_financials(self.secretary))
        self.assertTrue(controller._hide_project_financials(self.administrative))
        self.assertFalse(controller._hide_project_financials(self.boss))

    def test_payment_history_scope_by_profile(self):
        Analytic = self.env['account.analytic.account']

        def visible(user):
            return Analytic.search(Analytic._portal_payment_visible_domain(user))

        secretary_projects = visible(self.secretary)
        self.assertIn(self.project, secretary_projects)
        self.assertIn(self.other_project, secretary_projects)
        # El Jefe de Equipo ve los proyectos de sus grupos...
        self.assertIn(self.project, visible(self.boss))
        self.assertNotIn(self.other_project, visible(self.boss))
        # ...y el Administrativo solo aquellos de los que es responsable.
        self.assertFalse(visible(self.administrative))

    def test_record_rules_grant_read_only_on_all_groups(self):
        accounts = self.env['account.analytic.account'].with_user(self.secretary).search([])
        self.assertIn(self.other_project, accounts)
        documents = self.env['document.approval'].with_user(self.secretary).search([])
        self.assertIn(self.other_document, documents)
        with self.assertRaises(AccessError):
            self.other_document.with_user(self.secretary).check_access('write')
        with self.assertRaises(AccessError):
            self.other_project.with_user(self.secretary).check_access('write')


@tagged('post_install', '-at_install')
class TestSecretaryPortal(SecretaryAccessCommon, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_secretary_data()

    def _get(self, user, url):
        self.authenticate(user.login, self.password)
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_projects_list_shows_every_project_with_balance(self):
        page = self._get(self.secretary, '/my/analytic_projects')
        self.assertIn(self.project.name, page)
        self.assertIn(self.other_project.name, page)
        self.assertIn('<th>Saldo</th>', page)

    def test_project_without_company_shows_balance(self):
        # Una cuenta analítica compartida (sin compañía) no tiene moneda: el
        # saldo se muestra con la de la compañía en vez de romper la página.
        shared_project = self.env['account.analytic.account'].create({
            'name': 'Proyecto Compartido Secretaria',
            'plan_id': self.project.plan_id.id,
            'company_id': False,
            'work_group_id': self.other_team.id,
        })
        self.assertFalse(shared_project.currency_id)
        self.assertIn(shared_project.name, self._get(self.secretary, '/my/analytic_projects'))
        page = self._get(self.secretary, f'/my/analytic_projects/{shared_project.id}')
        self.assertIn('Presupuesto:', page)

    def test_administrative_projects_list_unchanged(self):
        page = self._get(self.administrative, '/my/analytic_projects')
        self.assertIn(self.project.name, page)
        self.assertNotIn(self.other_project.name, page)
        self.assertNotIn('<th>Saldo</th>', page)

    def test_request_forms_offer_every_work_group_and_project(self):
        page = self._get(self.secretary, '/portal/approval_request')
        self.assertIn(self.team.name, page)
        self.assertIn(self.other_team.name, page)
        page = self._get(self.secretary, '/portal/project_request')
        self.assertIn(self.other_team.name, page)
        page = self._get(self.secretary, '/portal/invoice_request')
        self.assertIn(self.project.name, page)
        self.assertIn(self.other_project.name, page)
        page = self._get(self.secretary, '/portal/hr_expensive_request')
        self.assertIn(self.other_project.name, page)

    def test_sees_secretary_manual(self):
        page = self._get(self.secretary, '/my/manual')
        self.assertIn(self.env.ref('portal_requests.manual_article_secretaria').name, page)
        self.assertNotIn(self.env.ref('portal_requests.manual_article_administrativo').name, page)
        self.assertIn('/my/manual/image/manual_img_secretaria_05_mis_proyectos', page)
        self.assertIn('href="/my/manual/pdf"', page)
        response = self.url_open('/my/manual/image/manual_img_secretaria_05_mis_proyectos')
        self.assertEqual(response.status_code, 200)
        response = self.url_open('/my/manual/pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:4], b'%PDF')
        # No puede pedir las imágenes de otro rol.
        response = self.url_open('/my/manual/image/manual_img_administrativo_01_inicio')
        self.assertEqual(response.status_code, 404)
