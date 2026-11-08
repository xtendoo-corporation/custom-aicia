# -*- coding: utf-8 -*-
"""Creación de la factura al aprobar una Solicitud de Factura.

La analítica de cabecera (``account.move.analytic_distribution``) la aporta
``aicia_account_move_analytic_account``; ``portal_requests`` no depende de
él, así que la creación de la factura no debe romper si ese campo no existe.
"""
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
