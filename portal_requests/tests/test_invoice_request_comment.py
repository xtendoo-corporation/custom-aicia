# -*- coding: utf-8 -*-
"""Campo "Comentario" en la Solicitud de Factura.

Petición del cliente: además del Concepto (que pasa a la línea de la
factura), la solicitud necesita un campo de comentario libre que se
mantenga durante todo el proceso (creación, revisión, aprobación) y que,
al crearse la factura, se añada como nota en su chatter.
"""
from odoo.http import Request
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInvoiceRequestCommentSubmit(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = 'invoice_comment_test'
        self.user = self.env['res.users'].create({
            'name': 'Solicitante Factura Comentario',
            'login': 'invoice_comment_test',
            'password': self.password,
            'email': 'invoice_comment_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Comentario Factura',
            'code': 'INVCOMMENT',
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Comentario Factura'})
        self.analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Comentario Factura',
            'plan_id': plan.id,
            'work_group_id': self.team.id,
        })
        self.partner = self.env['res.partner'].create({'name': 'Cliente Comentario Factura'})

    def _submit(self, comment=None):
        self.authenticate(self.user.login, self.password)
        data = {
            'csrf_token': Request.csrf_token(self),
            'company_id': str(self.analytic.id),
            'partner_id': str(self.partner.id),
            'amount': '50.0',
            'notes': 'Concepto de prueba',
            'move_type': 'out_invoice',
            'date': '2026-01-01',
        }
        if comment is not None:
            data['comment'] = comment
        return self.url_open('/portal/invoice_request/submit', data=data, allow_redirects=False)

    def _last_request(self):
        return self.env['portal.invoice.request'].sudo().search(
            [('user_id', '=', self.user.id)], order='id desc', limit=1
        )

    def test_submit_stores_comment(self):
        response = self._submit(comment='Ojo, el cliente pidió que se facture con retraso.')
        self.assertTrue(
            response.headers.get('Location', '').endswith('/my/invoices/thank-you')
        )
        invoice_request = self._last_request()
        self.assertEqual(invoice_request.comment, 'Ojo, el cliente pidió que se facture con retraso.')

    def test_submit_without_comment_is_optional(self):
        response = self._submit()
        self.assertTrue(
            response.headers.get('Location', '').endswith('/my/invoices/thank-you')
        )
        invoice_request = self._last_request()
        self.assertFalse(invoice_request.comment)


@tagged('post_install', '-at_install')
class TestInvoiceRequestCommentOnInvoice(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user = self.env['res.users'].create({
            'name': 'Solicitante Factura Comentario Nota',
            'login': 'invoice_comment_note_test',
            'email': 'invoice_comment_note_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Comentario Nota Factura',
            'code': 'INVCOMMENTNOTE',
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Comentario Nota Factura'})
        self.analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Comentario Nota Factura',
            'plan_id': plan.id,
            'work_group_id': self.team.id,
        })
        self.partner = self.env['res.partner'].create({'name': 'Cliente Comentario Nota Factura'})
        self.env['account.tax'].search([('name', '=', '21% S')], limit=1) \
            or self.env['account.tax'].create({'name': '21% S', 'amount': 21, 'type_tax_use': 'sale'})
        self.env['account.journal'].search([('name', '=', 'Facturas de cliente')], limit=1) \
            or self.env['account.journal'].create({
                'name': 'Facturas de cliente', 'type': 'sale', 'code': 'INVCN',
            })

    def _create_request(self, comment=None):
        return self.env['portal.invoice.request'].create({
            'user_id': self.user.id,
            'analytic_id': self.analytic.id,
            'partner_id': self.partner.id,
            'amount': 100.0,
            'notes': 'Concepto de la factura',
            'comment': comment,
            'move_type': 'out_invoice',
            'date': '2026-01-01',
        })

    def test_create_invoice_posts_comment_as_note(self):
        invoice_request = self._create_request(comment='Comentario interno de la solicitud.')
        invoice_request.create_invoice()
        note = invoice_request.invoice_created.message_ids.filtered(
            lambda m: m.subtype_id == self.env.ref('mail.mt_note') and m.body == '<p>Comentario interno de la solicitud.</p>'
        )
        self.assertTrue(note, "El comentario debe quedar publicado como nota en la factura creada")

    def test_create_invoice_without_comment_posts_no_extra_note(self):
        invoice_request = self._create_request(comment=None)
        notes_before = len(invoice_request.invoice_created.message_ids) if invoice_request.invoice_created else 0
        invoice_request.create_invoice()
        note = invoice_request.invoice_created.message_ids.filtered(
            lambda m: m.subtype_id == self.env.ref('mail.mt_note')
        )
        self.assertFalse(note, "Sin comentario no debe publicarse ninguna nota en la factura")

    def test_comment_persists_through_status_changes(self):
        invoice_request = self._create_request(comment='Se mantiene durante todo el proceso.')
        invoice_request.write({'status': 'to_revise'})
        invoice_request.write({'status': 'approved_by_boss_group'})
        invoice_request.write({'status': 'approved_by_client_responsible'})
        self.assertEqual(invoice_request.comment, 'Se mantiene durante todo el proceso.')
