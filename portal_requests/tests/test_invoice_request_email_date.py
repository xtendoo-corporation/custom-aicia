# -*- coding: utf-8 -*-
"""Test de que el correo al Responsable de Clientes incluye la fecha de la
solicitud de factura.

Bug reportado: el correo que recibe el Responsable de Clientes al solicitar
una emisión de factura no incluía la fecha de la solicitud. Se cubren los
dos puntos del código donde se construye ese correo:

- ``controllers/portal_invoice_requests_controller.py::send_request_email``,
  usado cuando la solicitud llega directa (Jefe de Equipo/Administrativo).
- ``models/portal_inovice_requests_model.py::_send_invoice_request_mail``
  (rama ``approved_by_boss_group``), usado cuando el Jefe de Equipo aprueba
  la solicitud de un miembro normal del equipo.

El segundo test llama a ``_send_invoice_request_mail`` directamente (en vez
de pasar por ``action_approve``) para aislar el cambio del cuerpo del correo
de un problema de resolución de destinatarios ya existente y ajeno a este
fix: el dominio usado en ``action_approve`` para localizar al Responsable de
Clientes (``('work_group_ids', 'in', group_intern_partner_responsible.id)``)
compara un campo Many2many a ``portal.work.group`` contra el id de un
``res.groups``, dos modelos distintos, por lo que en la práctica no localiza
a nadie -- un bug real detectado durante esta investigación, pendiente de
reportar/arreglar aparte.
"""
from odoo.http import Request
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInvoiceRequestEmailDateDirect(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = 'invoice_email_date_test'
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Email Fecha',
            'login': 'invoice_email_date_boss_test',
            'password': self.password,
            'email': 'invoice_email_date_boss_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_equip_boss').id,
                self.env.ref('base.group_portal').id,
            ])],
        })
        self.client_responsible = self.env['res.users'].create({
            'name': 'Responsable de Clientes Email Fecha',
            'login': 'invoice_email_date_resp_test',
            'email': 'invoice_email_date_resp_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_intern_partner_responsible').id,
            ])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Email Fecha',
            'code': 'INVEMAILDATE',
            'user_ids': [(6, 0, [self.boss.id])],
            'equip_boss': self.boss.id,
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Email Fecha'})
        self.analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Email Fecha',
            'plan_id': plan.id,
            'work_group_id': self.team.id,
        })
        self.partner = self.env['res.partner'].create({'name': 'Cliente Email Fecha'})

    def test_direct_request_email_to_client_responsible_includes_date(self):
        self.authenticate(self.boss.login, self.password)
        self.url_open(
            '/portal/invoice_request/submit',
            data={
                'csrf_token': Request.csrf_token(self),
                'company_id': str(self.analytic.id),
                'partner_id': str(self.partner.id),
                'amount': '100.0',
                'notes': 'Concepto de prueba',
                'move_type': 'out_invoice',
                'date': '2026-03-15',
            },
            allow_redirects=False,
        )
        mail = self.env['mail.mail'].sudo().search(
            [('email_to', '=', self.client_responsible.email)], order='id desc', limit=1
        )
        self.assertTrue(mail, "Debe haberse enviado un correo al Responsable de Clientes")
        self.assertIn('15-03-2026', mail.body_html)


@tagged('post_install', '-at_install')
class TestInvoiceRequestEmailDateOnApproval(TransactionCase):

    def setUp(self):
        super().setUp()
        self.team_member = self.env['res.users'].create({
            'name': 'Miembro de Equipo Email Fecha',
            'login': 'invoice_email_date_member_test',
            'email': 'invoice_email_date_member_test@example.com',
        })
        self.client_responsible = self.env['res.users'].create({
            'name': 'Responsable de Clientes Email Fecha Aprobacion',
            'login': 'invoice_email_date_resp_approve_test',
            'email': 'invoice_email_date_resp_approve_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_intern_partner_responsible').id,
            ])],
        })
        # Segundo miembro del grupo: para comprobar que se notifica a TODO
        # el grupo, no solo a un usuario concreto.
        self.other_client_responsible = self.env['res.users'].create({
            'name': 'Responsable de Clientes Email Fecha Aprobacion 2',
            'login': 'invoice_email_date_resp_approve_test_2',
            'email': 'invoice_email_date_resp_approve_test_2@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_intern_partner_responsible').id,
            ])],
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Email Fecha Aprobacion'})
        self.analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Email Fecha Aprobacion',
            'plan_id': plan.id,
        })
        self.partner = self.env['res.partner'].create({'name': 'Cliente Email Fecha Aprobacion'})
        self.invoice_request = self.env['portal.invoice.request'].create({
            'user_id': self.team_member.id,
            'analytic_id': self.analytic.id,
            'partner_id': self.partner.id,
            'amount': 200.0,
            'move_type': 'out_invoice',
            'date': '2026-04-20',
            'status': 'approved_by_boss_group',
        })

    def test_approved_by_boss_group_email_body_includes_date(self):
        self.invoice_request._send_invoice_request_mail(
            'approved_by_boss_group', self.client_responsible, 'factura',
            self.team_member.name, self.analytic.name, self.partner.name,
        )
        mail = self.env['mail.mail'].sudo().search(
            [('email_to', '=', self.client_responsible.email)], order='id desc', limit=1
        )
        self.assertTrue(mail, "Debe haberse enviado un correo al Responsable de Clientes")
        self.assertIn('20-04-2026', mail.body_html)

    def test_action_approve_notifies_whole_client_responsible_group(self):
        # Bug real detectado durante la revisión del punto anterior: el
        # dominio usado aquí comparaba 'work_group_ids' (M2M a
        # portal.work.group) contra el id de un res.groups, por lo que en la
        # práctica no localizaba a nadie. Se corrige a `group.user_ids` y se
        # comprueba con DOS miembros del grupo que se notifica a todos, no
        # solo a uno.
        self.invoice_request.action_approve()

        self.assertEqual(self.invoice_request.status, 'approved_by_client_responsible')
        for recipient in (self.client_responsible, self.other_client_responsible):
            mail = self.env['mail.mail'].sudo().search(
                [('email_to', '=', recipient.email)], order='id desc', limit=1
            )
            self.assertTrue(
                mail,
                f"Debe notificarse a {recipient.name} como miembro del "
                "grupo Responsable de Clientes",
            )
            self.assertIn('20-04-2026', mail.body_html)
