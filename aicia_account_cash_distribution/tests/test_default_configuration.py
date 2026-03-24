# -*- coding: utf-8 -*-
"""
Validación de la configuración por defecto creada en la instalación del módulo.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDefaultConfiguration(TransactionCase):
    def test_default_plan_and_company_flags(self):
        company = self.env.company
        plan = self.env['aicia.distribution.plan'].search([
            ('company_id', '=', company.id),
            ('name', '=', 'Distribución AICIA por defecto'),
        ], limit=1)
        self.assertTrue(plan, "Debe existir el plan de distribución por defecto.")

        vat_lines = plan.line_ids.filtered('is_vat_line')
        self.assertTrue(vat_lines, "Debe existir una línea de IVA al 100%.")
        vat_line = vat_lines[0]
        self.assertEqual(vat_line.debit_account_id, vat_line.credit_account_id)
        self.assertEqual(vat_line.debit_analytic_side, 'source')
        self.assertEqual(vat_line.credit_analytic_side, 'receiver')

        base_lines = plan.line_ids.filtered(lambda l: not l.is_vat_line)
        self.assertTrue(base_lines, "Debe existir una línea base del 10%.")
        base_line = base_lines[0]
        self.assertAlmostEqual(base_line.percentage, 10.0, places=4)
        self.assertEqual(base_line.debit_analytic_side, 'receiver')
        self.assertEqual(base_line.credit_analytic_side, 'source')

        self.assertTrue(company.cash_distribution_active, "La compañía debe quedar con distribución activa.")
        self.assertTrue(company.cash_distribution_receiver_analytic_id,
                        "La compañía debe tener analítica receptora configurada.")

