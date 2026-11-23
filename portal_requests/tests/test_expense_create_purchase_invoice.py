# -*- coding: utf-8 -*-
"""Factura de compra generada al aprobar una solicitud de gasto.

La factura se crea en borrador con el adjunto de la solicitud como adjunto
principal estándar (``message_main_attachment_id``), sin campos de módulos
de importación externos.
"""
import base64

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExpenseCreatePurchaseInvoice(TransactionCase):

    def setUp(self):
        super().setUp()
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Factura Gasto'})
        self.project = self.env['account.analytic.account'].create({
            'name': 'Proyecto Factura Gasto',
            'plan_id': plan.id,
        })
        self.user = self.env['res.users'].create({
            'name': 'Solicitante Factura Gasto',
            'login': 'expense_purchase_invoice_test',
            'email': 'expense_purchase_invoice_test@example.com',
        })
        self.request = self.env['portal.hr.expensive.request'].create({
            'user_id': self.user.id,
            'type': 'bienes_servicios',
            'project': self.project.id,
        })

    def _attach(self, name):
        return self.env['ir.attachment'].create({
            'name': name,
            'datas': base64.b64encode(b'%PDF-1.4 test'),
            'mimetype': 'application/pdf',
            'res_model': 'portal.hr.expensive.request',
            'res_id': self.request.id,
        })

    def test_invoice_gets_request_attachment_as_main(self):
        attachment = self._attach('factura_proveedor.pdf')
        self.request._create_purchase_invoice()
        invoice = self.request.invoice_created
        self.assertEqual(invoice.move_type, 'in_invoice')
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(attachment.res_model, 'account.move')
        self.assertEqual(attachment.res_id, invoice.id)
        self.assertEqual(invoice.message_main_attachment_id, attachment)

    def test_inventory_attachment_is_not_main_invoice_attachment(self):
        inventory = self._attach('inventario_listado.pdf')
        self.request._create_purchase_invoice()
        invoice = self.request.invoice_created
        self.assertTrue(invoice)
        self.assertNotEqual(invoice.message_main_attachment_id, inventory)
        self.assertEqual(inventory.res_model, 'portal.hr.expensive.request')

    def test_invoice_attachment_is_chosen_among_inventory_lists(self):
        invoice_document = self._attach('factura_proveedor.pdf')
        inventory = self._attach('inventario_listado.pdf')
        self.request._create_purchase_invoice()
        invoice = self.request.invoice_created
        self.assertEqual(invoice.message_main_attachment_id, invoice_document)
        self.assertEqual(invoice_document.res_id, invoice.id)
        self.assertEqual(inventory.res_model, 'portal.hr.expensive.request')

    def test_invoice_without_attachments(self):
        self.request._create_purchase_invoice()
        invoice = self.request.invoice_created
        self.assertEqual(invoice.move_type, 'in_invoice')
        self.assertFalse(invoice.message_main_attachment_id)
