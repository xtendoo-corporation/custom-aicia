# -*- coding: utf-8 -*-
"""Revisión de las solicitudes del equipo desde el portal.

- El paso "Aprobación del Jefe de Equipo" solo lo aprueba o rechaza el Jefe
  de Equipo del grupo de trabajo, nunca el Administrativo (no tiene un estado
  propio en el circuito). Aplica a documentos, proyectos, facturas y gastos.
- El Jefe de Equipo puede rechazar desde el portal en su paso, con motivo
  obligatorio (mismo efecto que el rechazo del backend).
- El Jefe de Equipo y el Administrativo ven y abren en el portal los gastos
  de su equipo, no solo los propios.
- Las solicitudes de proyecto del equipo aparecen en el listado del Jefe de
  Equipo y del Administrativo.
- Avisos: el Jefe de Equipo recibe el aviso de documentos/proyectos nuevos
  que entran en su paso, con enlace al portal.
"""
from odoo.exceptions import UserError
from odoo.http import Request
from odoo.tests import HttpCase, TransactionCase, tagged

from .test_expense_request_routing_and_approve import ExpenseRoutingSetupMixin
from .test_invoice_request_routing import InvoiceRoutingSetupMixin


class TeamSetupMixin:
    """Equipo con Jefe de Equipo, Administrativo y un miembro, más un
    usuario ajeno, todos de portal."""

    def _setup_team(self, prefix, password=None):
        portal = self.env.ref('base.group_portal')
        pwd = {'password': password} if password else {}
        self.boss = self.env['res.users'].create({
            'name': f'Jefe {prefix}',
            'login': f'{prefix}_boss',
            'email': f'{prefix}_boss@example.com',
            'group_ids': [(6, 0, [self.env.ref('portal_requests.group_equip_boss').id, portal.id])],
            **pwd,
        })
        self.administrative = self.env['res.users'].create({
            'name': f'Administrativo {prefix}',
            'login': f'{prefix}_administrative',
            'email': f'{prefix}_administrative@example.com',
            'group_ids': [(6, 0, [self.env.ref('portal_requests.group_administrative').id])],
            **pwd,
        })
        self.member = self.env['res.users'].create({
            'name': f'Miembro {prefix}',
            'login': f'{prefix}_member',
            'email': f'{prefix}_member@example.com',
            'group_ids': [(6, 0, [portal.id])],
            **pwd,
        })
        self.outsider = self.env['res.users'].create({
            'name': f'Ajeno {prefix}',
            'login': f'{prefix}_outsider',
            'email': f'{prefix}_outsider@example.com',
            'group_ids': [(6, 0, [portal.id])],
            **pwd,
        })
        self.team = self.env['portal.work.group'].create({
            'name': f'Equipo {prefix}',
            'code': prefix.upper(),
            'user_ids': [(6, 0, [self.boss.id, self.administrative.id, self.member.id])],
            'equip_boss': self.boss.id,
            'administrative_id': self.administrative.id,
        })


# ─────────────────────────────────────────────
# Documentos
# ─────────────────────────────────────────────

@tagged('post_install', '-at_install')
class TestDocumentBossStep(TransactionCase, TeamSetupMixin):

    def setUp(self):
        super().setUp()
        self._setup_team('docstep')
        self.document = self.env['document.approval'].create({
            'type_id': self.env.ref('portal_requests.type_approval_nda').id,
            'description': 'Documento del miembro',
            'user_id': self.member.id,
            'work_group_id': self.team.id,
        })

    def test_administrative_cannot_approve_team_document(self):
        self.document.with_user(self.administrative).action_approve()
        self.assertEqual(self.document.status, 'approved_by_equip_boss')

    def test_boss_approves_team_document(self):
        self.document.with_user(self.boss).action_approve()
        self.assertEqual(self.document.status, 'approved_by_director_i_d')

    def test_reject_with_reason_is_logged(self):
        self.document.action_reject(reason='Falta la firma del anexo')
        self.assertEqual(self.document.status, 'rejected')
        self.assertTrue(any(
            'Falta la firma del anexo' in (message.body or '')
            for message in self.document.message_ids
        ))

    def test_new_document_notifies_boss_with_portal_link(self):
        self.document._notify_new_request()
        mail = self.env['mail.mail'].sudo().search(
            [('email_to', '=', self.boss.email)], order='id desc', limit=1)
        self.assertTrue(mail)
        self.assertIn(f'/my/documents/{self.document.id}', mail.body_html)

    def test_boss_own_document_notifies_director(self):
        director = self.env['res.users'].create({
            'name': 'Director I+D docstep',
            'login': 'docstep_director',
            'email': 'docstep_director@example.com',
            'group_ids': [(6, 0, [self.env.ref(
                'portal_requests.group_director_investigation_and_development').id])],
        })
        document = self.env['document.approval'].create({
            'type_id': self.env.ref('portal_requests.type_approval_nda').id,
            'description': 'Documento del Jefe',
            'user_id': self.boss.id,
            'work_group_id': self.team.id,
        })
        document._notify_new_request()
        self.assertTrue(self.env['mail.mail'].sudo().search_count(
            [('email_to', '=', director.email)]))
        self.assertFalse(self.env['mail.mail'].sudo().search_count(
            [('email_to', '=', self.boss.email)]))

    def test_resubmit_notifies_only_team_boss(self):
        other_boss = self.env['res.users'].create({
            'name': 'Otro Jefe docstep',
            'login': 'docstep_other_boss',
            'email': 'docstep_other_boss@example.com',
            'group_ids': [(6, 0, [self.env.ref('portal_requests.group_equip_boss').id,
                                  self.env.ref('base.group_portal').id])],
        })
        self.document.action_reject(reason='Motivo')
        self.document.action_resubmit()
        self.assertTrue(self.env['mail.mail'].sudo().search_count(
            [('email_to', '=', self.boss.email)]))
        self.assertFalse(self.env['mail.mail'].sudo().search_count(
            [('email_to', '=', other_boss.email)]))


@tagged('post_install', '-at_install')
class TestDocumentBossStepHttp(HttpCase, TeamSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'docstep_http_pwd'
        self._setup_team('docstephttp', self.password)
        self.document = self.env['document.approval'].create({
            'type_id': self.env.ref('portal_requests.type_approval_nda').id,
            'description': 'Documento del miembro HTTP',
            'user_id': self.member.id,
            'work_group_id': self.team.id,
        })

    def _post(self, user, action, data=None):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/documents/{self.document.id}/{action}',
            data={'csrf_token': Request.csrf_token(self), **(data or {})},
            allow_redirects=False,
        )

    def test_administrative_cannot_approve(self):
        response = self._post(self.administrative, 'approve')
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.document.invalidate_recordset()
        self.assertEqual(self.document.status, 'approved_by_equip_boss')

    def test_administrative_detail_has_no_approve_or_reject(self):
        self.authenticate(self.administrative.login, self.password)
        response = self.url_open(f'/my/documents/{self.document.id}')
        self.assertIn(f'Solicitud de Documento #', response.text)
        self.assertNotIn(f'/my/documents/{self.document.id}/approve', response.text)
        self.assertNotIn(f'/my/documents/{self.document.id}/reject', response.text)

    def test_boss_detail_shows_reject(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open(f'/my/documents/{self.document.id}')
        self.assertIn(f'/my/documents/{self.document.id}/reject', response.text)

    def test_boss_rejects_with_reason(self):
        response = self._post(self.boss, 'reject', {'reason': 'Documento incompleto'})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/documents/{self.document.id}?success=rejected'))
        self.document.invalidate_recordset()
        self.assertEqual(self.document.status, 'rejected')

    def test_reject_without_reason_does_nothing(self):
        response = self._post(self.boss, 'reject', {'reason': '   '})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/documents/{self.document.id}?error=reason_required'))
        self.document.invalidate_recordset()
        self.assertEqual(self.document.status, 'approved_by_equip_boss')

    def test_administrative_cannot_reject(self):
        response = self._post(self.administrative, 'reject', {'reason': 'No'})
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.document.invalidate_recordset()
        self.assertEqual(self.document.status, 'approved_by_equip_boss')

    def test_administrative_cannot_confirm_company_sign(self):
        self.document.write({'status': 'sign_company'})
        response = self._post(self.administrative, 'request_revision')
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.document.invalidate_recordset()
        self.assertEqual(self.document.status, 'sign_company')


# ─────────────────────────────────────────────
# Solicitudes de proyecto
# ─────────────────────────────────────────────

@tagged('post_install', '-at_install')
class TestProjectRequestBossStep(TransactionCase, TeamSetupMixin):

    def setUp(self):
        super().setUp()
        self._setup_team('projstep')
        self.project_request = self.env['portal.project.request'].create({
            'user_id': self.member.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'project_name': 'Proyecto del miembro',
            'type': 'new',
        })

    def test_administrative_cannot_approve_team_request(self):
        with self.assertRaises(UserError):
            self.project_request.with_user(self.administrative).action_approve_equip_boss()
        self.assertEqual(self.project_request.status, 'approved_by_equip_boss')

    def test_boss_approves_team_request(self):
        self.project_request.with_user(self.boss).action_approve_equip_boss()
        self.assertEqual(self.project_request.status, 'pending_review')

    def test_new_request_notifies_boss(self):
        self.project_request._notify_project_request_approvers(resubmit=False)
        mail = self.env['mail.mail'].sudo().search(
            [('email_to', '=', self.boss.email)], order='id desc', limit=1)
        self.assertTrue(mail)
        self.assertIn(f'/my/project_requests/{self.project_request.id}', mail.body_html)


@tagged('post_install', '-at_install')
class TestProjectRequestBossStepHttp(HttpCase, TeamSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'projstep_http_pwd'
        self._setup_team('projstephttp', self.password)
        self.project_request = self.env['portal.project.request'].create({
            'user_id': self.member.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'project_name': 'Proyecto HTTP del miembro',
            'type': 'new',
        })

    def _post(self, user, action, data=None):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/project_requests/{self.project_request.id}/{action}',
            data={'csrf_token': Request.csrf_token(self), **(data or {})},
            allow_redirects=False,
        )

    def test_team_request_in_boss_list(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open('/my/project_requests')
        self.assertIn(f'/my/project_requests/{self.project_request.id}', response.text)

    def test_team_request_in_administrative_list(self):
        self.authenticate(self.administrative.login, self.password)
        response = self.url_open('/my/project_requests')
        self.assertIn(f'/my/project_requests/{self.project_request.id}', response.text)

    def test_administrative_cannot_approve(self):
        response = self._post(self.administrative, 'approve')
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.project_request.invalidate_recordset()
        self.assertEqual(self.project_request.status, 'approved_by_equip_boss')

    def test_boss_rejects_with_reason(self):
        response = self._post(self.boss, 'reject', {'reason': 'Presupuesto incorrecto'})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/project_requests/{self.project_request.id}?success=rejected'))
        self.project_request.invalidate_recordset()
        self.assertTrue(self.project_request.is_revised)
        self.assertFalse(self.project_request.approved)

    def test_reject_without_reason_does_nothing(self):
        response = self._post(self.boss, 'reject', {'reason': ''})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/project_requests/{self.project_request.id}?error=reason_required'))
        self.project_request.invalidate_recordset()
        self.assertFalse(self.project_request.is_revised)

    def test_administrative_cannot_reject(self):
        response = self._post(self.administrative, 'reject', {'reason': 'No'})
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.project_request.invalidate_recordset()
        self.assertFalse(self.project_request.is_revised)


# ─────────────────────────────────────────────
# Facturas
# ─────────────────────────────────────────────

@tagged('post_install', '-at_install')
class TestInvoiceBossStepHttp(HttpCase, InvoiceRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'invstep_http_pwd'
        self._setup_invoice_routing_team(
            boss_vals={'password': self.password},
            administrative_vals={'password': self.password},
            team_member_vals={'password': self.password},
        )
        self.invoice_request = self.env['portal.invoice.request'].create({
            'user_id': self.team_member.id,
            'analytic_id': self.analytic.id,
            'partner_id': self.partner.id,
            'amount': 100.0,
            'status': 'approved_by_boss_group',
        })

    def _post(self, user, action, data=None):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/invoices/{self.invoice_request.id}/{action}',
            data={'csrf_token': Request.csrf_token(self), **(data or {})},
            allow_redirects=False,
        )

    def test_approve_button_only_for_boss(self):
        self.assertTrue(self.invoice_request.with_user(self.boss).show_approve_button)
        self.assertFalse(self.invoice_request.with_user(self.administrative).show_approve_button)

    def test_administrative_detail_has_no_buttons(self):
        self.authenticate(self.administrative.login, self.password)
        response = self.url_open(f'/my/invoices/{self.invoice_request.id}')
        self.assertIn('Solicitud de Factura #', response.text)
        self.assertNotIn(f'/my/invoices/{self.invoice_request.id}/approve', response.text)
        self.assertNotIn(f'/my/invoices/{self.invoice_request.id}/reject', response.text)

    def test_boss_rejects_with_reason(self):
        response = self._post(self.boss, 'reject', {'reason': 'Importe erróneo'})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/invoices/{self.invoice_request.id}?success=rejected'))
        self.invoice_request.invalidate_recordset()
        self.assertEqual(self.invoice_request.status, 'to_revise')

    def test_reject_without_reason_does_nothing(self):
        response = self._post(self.boss, 'reject', {'reason': ''})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/invoices/{self.invoice_request.id}?error=reason_required'))
        self.invoice_request.invalidate_recordset()
        self.assertEqual(self.invoice_request.status, 'approved_by_boss_group')

    def test_administrative_cannot_reject(self):
        response = self._post(self.administrative, 'reject', {'reason': 'No'})
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.invoice_request.invalidate_recordset()
        self.assertEqual(self.invoice_request.status, 'approved_by_boss_group')

    def test_new_invoice_mail_to_boss_links_portal(self):
        self.authenticate(self.team_member.login, self.password)
        self.url_open(
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
        mail = self.env['mail.mail'].sudo().search(
            [('email_to', '=', self.boss.email)], order='id desc', limit=1)
        self.assertTrue(mail)
        self.assertIn('/my/invoices/', mail.body_html)
        self.assertNotIn('/web#', mail.body_html)


@tagged('post_install', '-at_install')
class TestInvoiceResubmitNotifiesBossOnly(TransactionCase, InvoiceRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self._setup_invoice_routing_team()

    def test_resubmit_notifies_boss_not_administrative(self):
        invoice_request = self.env['portal.invoice.request'].create({
            'user_id': self.team_member.id,
            'analytic_id': self.analytic.id,
            'partner_id': self.partner.id,
            'amount': 50.0,
            'status': 'to_revise',
        })
        invoice_request.action_approve()
        self.assertEqual(invoice_request.status, 'approved_by_boss_group')
        subject = 'Nueva Revisión de'
        self.assertTrue(self.env['mail.mail'].sudo().search_count(
            [('email_to', '=', self.boss.email), ('subject', 'like', subject)]))
        self.assertFalse(self.env['mail.mail'].sudo().search_count(
            [('email_to', '=', self.administrative.email), ('subject', 'like', subject)]))


# ─────────────────────────────────────────────
# Gastos
# ─────────────────────────────────────────────

@tagged('post_install', '-at_install')
class TestExpenseTeamReviewHttp(HttpCase, ExpenseRoutingSetupMixin):

    def setUp(self):
        super().setUp()
        self.password = 'expstep_http_pwd'
        self._setup_expense_routing_team(
            boss_vals={'password': self.password},
            administrative_vals={'password': self.password},
            team_member_vals={'password': self.password},
        )
        self.outsider = self.env['res.users'].create({
            'name': 'Ajeno Gasto',
            'login': 'expstep_outsider',
            'email': 'expstep_outsider@example.com',
            'password': self.password,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.expense = self.env['portal.hr.expensive.request'].create({
            'user_id': self.team_member.id,
            'type': 'bienes_servicios',
            'project': self.analytic.id,
            'status': 'approved_by_boss_group',
        })

    def _post(self, user, action, data=None):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/expenses/{self.expense.id}/{action}',
            data={'csrf_token': Request.csrf_token(self), **(data or {})},
            allow_redirects=False,
        )

    def test_team_expense_in_boss_list(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open('/my/expenses')
        self.assertIn(f'/my/expenses/{self.expense.id}', response.text)

    def test_team_expense_in_administrative_list(self):
        self.authenticate(self.administrative.login, self.password)
        response = self.url_open('/my/expenses')
        self.assertIn(f'/my/expenses/{self.expense.id}', response.text)

    def test_team_expense_not_in_outsider_list(self):
        self.authenticate(self.outsider.login, self.password)
        response = self.url_open('/my/expenses')
        self.assertNotIn(f'/my/expenses/{self.expense.id}', response.text)

    def test_boss_opens_team_expense_with_buttons(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open(f'/my/expenses/{self.expense.id}')
        self.assertIn(f'Solicitud de Gastos #', response.text)
        self.assertIn(f'/my/expenses/{self.expense.id}/approve', response.text)
        self.assertIn(f'/my/expenses/{self.expense.id}/reject', response.text)

    def test_administrative_opens_team_expense_without_buttons(self):
        self.authenticate(self.administrative.login, self.password)
        response = self.url_open(f'/my/expenses/{self.expense.id}')
        self.assertIn(f'Solicitud de Gastos #', response.text)
        self.assertNotIn(f'/my/expenses/{self.expense.id}/approve', response.text)
        self.assertNotIn(f'/my/expenses/{self.expense.id}/reject', response.text)

    def test_outsider_cannot_open_detail(self):
        self.authenticate(self.outsider.login, self.password)
        response = self.url_open(f'/my/expenses/{self.expense.id}', allow_redirects=False)
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))

    def test_administrative_can_post_message(self):
        response = self._post(self.administrative, 'post_message', {'message': 'Revisado'})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/expenses/{self.expense.id}?success=message_posted'))

    def test_outsider_cannot_post_message(self):
        response = self._post(self.outsider, 'post_message', {'message': 'Hola'})
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))

    def test_boss_rejects_with_reason(self):
        response = self._post(self.boss, 'reject', {'reason': 'Falta la factura'})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/expenses/{self.expense.id}?success=rejected'))
        self.expense.invalidate_recordset()
        self.assertEqual(self.expense.status, 'to_revise')

    def test_reject_without_reason_does_nothing(self):
        response = self._post(self.boss, 'reject', {'reason': ''})
        self.assertTrue(response.headers.get('Location', '').endswith(
            f'/my/expenses/{self.expense.id}?error=reason_required'))
        self.expense.invalidate_recordset()
        self.assertEqual(self.expense.status, 'approved_by_boss_group')

    def test_administrative_cannot_reject(self):
        response = self._post(self.administrative, 'reject', {'reason': 'No'})
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.expense.invalidate_recordset()
        self.assertEqual(self.expense.status, 'approved_by_boss_group')

    def test_new_expense_mail_to_boss_links_portal(self):
        self.authenticate(self.team_member.login, self.password)
        self.url_open(
            '/portal/hr_expensive_request/submit',
            data={
                'csrf_token': Request.csrf_token(self),
                'expensive_type': 'bienes_servicios',
                'user_id': str(self.team_member.id),
                'company_id': str(self.analytic.id),
                'is_more': '',
            },
            allow_redirects=False,
        )
        mail = self.env['mail.mail'].sudo().search(
            [('email_to', '=', self.boss.email)], order='id desc', limit=1)
        self.assertTrue(mail)
        self.assertIn('/my/expenses/', mail.body_html)
        self.assertNotIn('/web#', mail.body_html)
