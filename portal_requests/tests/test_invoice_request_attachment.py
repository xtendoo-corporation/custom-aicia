# -*- coding: utf-8 -*-
"""Test del adjunto opcional en el formulario de Solicitud de Facturas.

Mejora reportada: el formulario de creación de "Solicitud de Facturas"
(``portal_invoice_requests_template.xml``) no tenía forma de adjuntar el
"documento de emisión de factura" al crear la solicitud -- solo se podía
subir un adjunto después, desde la pantalla de detalle. Se añade un campo de
fichero opcional al formulario y su procesamiento en el controlador
(``invoice_request_submit``), replicando el mismo patrón ya usado en
Solicitud de Documentos (``portal_approval_request_controller.py``): un
input ``name="file"``, validado con ``ensure_pdf`` y guardado como
``ir.attachment`` ligado al registro creado.
"""
from odoo.http import Request
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestInvoiceRequestAttachment(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = 'invoice_attachment_test'
        self.user = self.env['res.users'].create({
            'name': 'Solicitante Factura Adjunto',
            'login': 'invoice_attachment_test',
            'password': self.password,
            'email': 'invoice_attachment_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Adjunto Factura',
            'code': 'INVATT',
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Adjunto Factura'})
        self.analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Adjunto Factura',
            'plan_id': plan.id,
            'work_group_id': self.team.id,
        })
        self.partner = self.env['res.partner'].create({'name': 'Cliente Adjunto Factura'})

    def _submit(self, files=None):
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
        kwargs = {'data': data, 'allow_redirects': False}
        if files:
            kwargs['files'] = files
        return self.url_open('/portal/invoice_request/submit', **kwargs)

    def _last_request(self):
        return self.env['portal.invoice.request'].sudo().search(
            [('user_id', '=', self.user.id)], order='id desc', limit=1
        )

    def _attachments_for(self, invoice_request):
        return self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'portal.invoice.request'),
            ('res_id', '=', invoice_request.id),
        ])

    def test_submit_with_valid_pdf_creates_attachment(self):
        response = self._submit(files={
            'file': ('factura.pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n', 'application/pdf'),
        })
        self.assertTrue(
            response.headers.get('Location', '').endswith('/my/invoices/thank-you')
        )
        invoice_request = self._last_request()
        attachments = self._attachments_for(invoice_request)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments.name, 'factura.pdf')

    def test_submit_without_file_creates_no_attachment(self):
        # El adjunto es opcional: la solicitud se crea igual sin él.
        response = self._submit()
        self.assertTrue(
            response.headers.get('Location', '').endswith('/my/invoices/thank-you')
        )
        invoice_request = self._last_request()
        self.assertEqual(len(self._attachments_for(invoice_request)), 0)

    def test_submit_with_non_pdf_file_is_rejected(self):
        requests_before = self.env['portal.invoice.request'].sudo().search_count([])
        response = self._submit(files={
            'file': ('factura.txt', b'esto no es un pdf', 'text/plain'),
        })
        self.assertNotEqual(
            response.headers.get('Location', ''), '/my/invoices/thank-you'
        )
        self.assertEqual(
            self.env['portal.invoice.request'].sudo().search_count([]), requests_before,
            "Un adjunto no-PDF debe impedir que se cree la solicitud "
            "(transacción revertida)",
        )
