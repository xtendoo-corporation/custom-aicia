# -*- coding: utf-8 -*-
"""Creación de la factura al aprobar una Solicitud de Factura.

La analítica de cabecera (``account.move.analytic_distribution``) la aporta
``aicia_account_move_analytic_account``; ``portal_requests`` no depende de
él, así que la creación de la factura no debe romper si ese campo no existe.
"""
import base64
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInvoiceRequestCreateInvoice(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user = self.env['res.users'].create({
            'name': 'Solicitante Crear Factura',
            'login': 'invoice_create_invoice_test',
            'email': 'invoice_create_invoice_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        team = self.env['portal.work.group'].create({
            'name': 'Equipo Crear Factura',
            'code': 'INVCREATE',
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Crear Factura'})
        self.analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Crear Factura',
            'plan_id': plan.id,
            'work_group_id': team.id,
        })
        self.partner = self.env['res.partner'].create({'name': 'Cliente Crear Factura'})
        self.env['account.tax'].search([('name', '=', '21% S')], limit=1) \
            or self.env['account.tax'].create({'name': '21% S', 'amount': 21, 'type_tax_use': 'sale'})
        self.env['account.journal'].search([('name', '=', 'Facturas de cliente')], limit=1) \
            or self.env['account.journal'].create({
                'name': 'Facturas de cliente', 'type': 'sale', 'code': 'INVCC',
            })
        self.invoice_request = self.env['portal.invoice.request'].create({
            'user_id': self.user.id,
            'analytic_id': self.analytic.id,
            'partner_id': self.partner.id,
            'amount': 100.0,
            'notes': 'Concepto crear factura',
            'move_type': 'out_invoice',
            'date': '2026-01-01',
        })

    def _assert_invoice_with_line_analytic(self):
        invoice = self.invoice_request.invoice_created
        self.assertTrue(invoice)
        self.assertEqual(invoice.move_type, 'out_invoice')
        line = invoice.invoice_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.price_unit, 100.0)
        self.assertEqual(line.analytic_distribution, {str(self.analytic.id): 100})

    def test_create_invoice_sets_line_analytic(self):
        self.invoice_request.create_invoice()
        self._assert_invoice_with_line_analytic()

    def test_create_invoice_without_header_analytic_field(self):
        move_cls = type(self.env['account.move'])
        fields_without_header_analytic = {
            name: field for name, field in move_cls._fields.items()
            if name != 'analytic_distribution'
        }
        with patch.object(move_cls, '_fields', fields_without_header_analytic):
            self.invoice_request.create_invoice()
        self._assert_invoice_with_line_analytic()


@tagged('post_install', '-at_install')
class TestInvoiceRequestCopyAttachments(TransactionCase):
    """Los adjuntos de la solicitud pasan a la factura al crearla."""

    def setUp(self):
        super().setUp()
        # create_invoice busca impuesto y diario por nombre; se apartan los
        # existentes (posiblemente de otra compañía) y se crean los de la
        # compañía actual para que la prueba no dependa de la BD.
        self.env['account.tax'].search([('name', '=', '21% S')]).write(
            {'name': '21% S (apartado)'})
        self.env['account.journal'].search(
            [('name', '=', 'Facturas de cliente')]).write(
            {'name': 'Facturas de cliente (apartado)'})
        self.env['account.tax'].create({
            'name': '21% S', 'amount': 21, 'type_tax_use': 'sale',
        })
        self.env['account.journal'].create({
            'name': 'Facturas de cliente', 'type': 'sale', 'code': 'INVCA',
        })
        self.user = self.env['res.users'].create({
            'name': 'Solicitante Adjuntos Factura',
            'login': 'invoice_copy_attachments_test',
            'email': 'invoice_copy_attachments_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        team = self.env['portal.work.group'].create({
            'name': 'Equipo Copia Adjuntos',
            'code': 'INVCOPY',
        })
        plan = self.env['account.analytic.plan'].create({'name': 'Plan Copia Adjuntos'})
        analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Copia Adjuntos',
            'plan_id': plan.id,
            'work_group_id': team.id,
        })
        self.invoice_request = self.env['portal.invoice.request'].create({
            'user_id': self.user.id,
            'analytic_id': analytic.id,
            'partner_id': self.env['res.partner'].create({'name': 'Cliente Copia'}).id,
            'amount': 100.0,
            'notes': 'Concepto copia adjuntos',
            'move_type': 'out_invoice',
            'date': '2026-01-01',
        })

    def _attach(self, name, content):
        return self.env['ir.attachment'].create({
            'name': name,
            'datas': base64.b64encode(content),
            'res_model': 'portal.invoice.request',
            'res_id': self.invoice_request.id,
            'mimetype': 'application/pdf',
        })

    def _move_attachments(self):
        return self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.invoice_request.invoice_created.id),
        ])

    def test_create_invoice_copies_request_attachment(self):
        source = self._attach('emision.pdf', b'%PDF-emision')
        self.invoice_request.create_invoice()
        copy = self._move_attachments()
        self.assertEqual(len(copy), 1)
        self.assertEqual(copy.name, 'emision.pdf')
        self.assertEqual(copy.mimetype, 'application/pdf')
        self.assertEqual(copy.raw, b'%PDF-emision')
        self.assertTrue(source.exists())
        self.assertEqual(source.res_model, 'portal.invoice.request')

    def test_copy_attachments_is_idempotent(self):
        self._attach('emision.pdf', b'%PDF-emision')
        self.invoice_request.create_invoice()
        invoice = self.invoice_request.invoice_created
        self.assertFalse(self.invoice_request._copy_attachments_to_move(invoice))
        self.assertEqual(len(self._move_attachments()), 1)

    def test_copy_attachments_adds_only_new_ones(self):
        self._attach('emision.pdf', b'%PDF-emision')
        self.invoice_request.create_invoice()
        invoice = self.invoice_request.invoice_created
        self._attach('emision.pdf', b'%PDF-otro-contenido')
        self._attach('justificante.pdf', b'%PDF-justificante')
        created = self.invoice_request._copy_attachments_to_move(invoice)
        self.assertEqual(len(created), 2)
        self.assertEqual(len(self._move_attachments()), 3)

    def test_create_invoice_without_attachments(self):
        self.invoice_request.create_invoice()
        self.assertFalse(self._move_attachments())

    def test_copy_attachments_as_portal_user_uses_sudo_only_for_copy(self):
        self._attach('emision.pdf', b'%PDF-emision')
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.invoice_request.partner_id.id,
        })
        request_as_portal = self.invoice_request.with_user(self.user)
        created = request_as_portal._copy_attachments_to_move(invoice)
        self.assertEqual(created.raw, b'%PDF-emision')
        self.assertEqual(created.res_model, 'account.move')
        self.assertEqual(created.res_id, invoice.id)
