# -*- coding: utf-8 -*-
from odoo.tests.common import HttpCase, tagged

@tagged('-at_install', 'post_install')
class TestPortalPayments(HttpCase):
    def test_portal_payments_access(self):
        # Crear usuario portal y datos de prueba
        portal_user = self.env['res.users'].create({
            'name': 'Portal User',
            'login': 'portal_user_test',
            'email': 'portal_user_test@example.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        # Crear proyecto y factura pagada
        analytic = self.env['account.analytic.account'].create({
            'name': 'Proyecto Test',
            'responsible_id': portal_user.id,
        })
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.env.ref('base.res_partner_1').id,
            'state': 'posted',
            'payment_state': 'paid',
            'analytic_distribution': {str(analytic.id): 100},
        })
        payment = self.env['account.payment'].create({
            'amount': 100,
            'partner_id': self.env.ref('base.res_partner_1').id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'state': 'posted',
            'invoice_ids': [(6, 0, [invoice.id])],
        })
        # Simular login y acceso a la página de pagos
        self.authenticate('portal_user_test', 'admin')
        response = self.url_open('/my/payments')
        self.assertEqual(response.status_code, 200)
        self.assertIn(payment.name, response.text)
        # Acceso al detalle
        response = self.url_open(f'/my/payments/{payment.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(payment.amount), response.text)

