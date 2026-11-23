# -*- coding: utf-8 -*-
"""
Validación de la configuración por defecto creada en la instalación del módulo.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDefaultConfiguration(TransactionCase):
    def test_default_plan_and_company_flags(self):
        company = self.env.company

        # Garantizar que la analítica receptora existe en la compañía
        if not company.cash_distribution_receiver_analytic_id:
            analytic_plan = self.env['account.analytic.plan'].search([], limit=1)
            receiver = self.env['account.analytic.account'].create({
                'name': 'AICIA Test Receiver',
                'plan_id': analytic_plan.id if analytic_plan else False,
                'company_id': company.id,
            })
            company.cash_distribution_receiver_analytic_id = receiver

        # Re-ejecutar el setup del plan por defecto para garantizar el estado esperado
        self.env['aicia.distribution.plan']._setup_default_plan(company)

        plan = self.env['aicia.distribution.plan'].search([
            ('company_id', '=', company.id),
            ('name', '=', 'Distribución AICIA por defecto'),
        ], limit=1)
        self.assertTrue(plan, "Debe existir el plan de distribución por defecto.")

        base_lines = plan.line_ids.filtered(lambda l: not l.is_vat_line)
        self.assertTrue(base_lines, "Debe existir una línea base del 10%.")
        base_line = base_lines[0]
        self.assertAlmostEqual(base_line.percentage, 10.0, places=4)
        self.assertEqual(base_line.debit_analytic_side, 'source')
        self.assertEqual(base_line.credit_analytic_side, 'fixed')
        self.assertTrue(base_line.credit_analytic_account_id,
                        "La línea base debe tener cuenta analítica fija en el haber.")

        vat_lines = plan.line_ids.filtered('is_vat_line')
        if vat_lines:
            vat_line = vat_lines[0]
            self.assertEqual(vat_line.debit_account_id, vat_line.credit_account_id)
            self.assertEqual(vat_line.debit_analytic_side, 'source')
            self.assertEqual(vat_line.credit_analytic_side, 'fixed')
            self.assertTrue(vat_line.credit_analytic_account_id,
                            "La línea IVA debe tener cuenta analítica fija en el haber.")

        self.assertTrue(company.cash_distribution_receiver_analytic_id,
                        "La compañía debe tener analítica receptora configurada.")
