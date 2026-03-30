# -*- coding: utf-8 -*-
from odoo.tests.common import tagged
from .common import AiciaCashDistributionCommon
import json

@tagged('post_install', '-at_install')
class TestDistributionPlanDetection(AiciaCashDistributionCommon):
    """Tests for the detection logic of distribution plans in invoices and payments."""

    def test_01_detection_from_header_analytic_distribution_json(self):
        """Test detection when analytic_distribution is a dict in the header."""
        plan = self._create_rule(name='Header Plan', source_analytic_ids=[self.analytic_account_a.id])
        
        # Manually create invoice with header distribution if the field exists
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Test line',
                'price_unit': 100.0,
                'account_id': self.account_revenue.id,
            })],
        }
        if 'analytic_distribution' in self.env['account.move']._fields:
            invoice_vals['analytic_distribution'] = {str(self.analytic_account_a.id): 100}
            
        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        
        # Test detection function directly
        detected_plan = self.env['account.payment']._get_distribution_plan_from_invoice(invoice)
        # It should find it from header or lines (since my code checks both)
        # If it's Odoo 17 CE, it might only be in lines if header field is missing, 
        # but _create_invoice normally puts it in lines.
        self.assertEqual(detected_plan, plan, "Should detect plan from invoice.")

    def test_02_detection_from_header_analytic_distribution_string(self):
        """Test detection when analytic_distribution is a JSON string (robustness check)."""
        plan = self._create_rule(name='Header Plan JSON String', source_analytic_ids=[self.analytic_account_a.id])
        
        invoice = self._create_invoice(analytic_account=self.analytic_account_a)
        # Mock the field to be a string (if we can, otherwise just test the helper directly)
        dist_json_str = json.dumps({str(self.analytic_account_a.id): 100})
        
        # Test the helper with string input
        detected_plan = self.env['account.payment']._get_distribution_plan_from_distribution(dist_json_str)
        self.assertEqual(detected_plan, plan, "Should detect plan from JSON string.")

    def test_03_detection_from_analytic_code(self):
        """Test detection when analytic distribution uses account code as key (User's case)."""
        plan = self._create_rule(name='Code Plan', source_analytic_ids=[self.analytic_account_a.id])
        self.analytic_account_a.code = 'CODE2401'
        
        # Simulate distribution with code as key
        dist_with_code = {'CODE2401': 100}
        
        detected_plan = self.env['account.payment']._get_distribution_plan_from_distribution(dist_with_code)
        self.assertEqual(detected_plan, plan, "Should detect plan using analytic code as key.")

    def test_04_payment_register_wizard_detection(self):
        """Test that the payment register wizard correctly pre-fills the plan."""
        plan = self._create_rule(name='Wizard Plan', source_analytic_ids=[self.analytic_account_a.id])
        invoice = self._create_invoice(analytic_account=self.analytic_account_a)
        
        # Create wizard with invoice in context
        Register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        )
        wizard = Register.create({
            'journal_id': self.bank_journal.id,
        })
        
        self.assertEqual(wizard.distribution_plan_id, plan, "Wizard should automatically detect the plan from the invoice.")

    def test_05_payment_manual_reconciliation_sync(self):
        """Test that distribution_plan_id is synced when payment is reconciled with invoice later."""
        plan = self._create_rule(name='Sync Plan', source_analytic_ids=[self.analytic_account_a.id])
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        
        # Create payment without plan
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 1000.0,
            'journal_id': self.bank_journal.id,
        })
        payment.action_post()
        self.assertFalse(payment.distribution_plan_id, "Payment should start without a plan.")
        
        # Reconcile lines
        mv_line = payment.move_id.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        inv_line = invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        (mv_line | inv_line).reconcile()
        
        # Trigger manual sync
        payment._sync_distribution_plan_from_invoices()
        
        self.assertEqual(payment.distribution_plan_id, plan, "Payment should sync the plan from the reconciled invoice.")

    def test_06_complete_distribution_flow(self):
        """Verify the whole flow from invoice to distribution move."""
        # Setup plan for analytic A
        plan = self._create_rule(name='Complete Flow Plan', source_analytic_ids=[self.analytic_account_a.id])
        
        # Create invoice with standard ID-based distribution
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.sale_journal.id,
            'invoice_line_ids': [
                (0, 0, {
                    'name': 'Service with standard distribution',
                    'quantity': 1,
                    'price_unit': 1000.0,
                    'account_id': self.account_revenue.id,
                    'analytic_distribution': {str(self.analytic_account_a.id): 100},
                })
            ],
        }
        if 'analytic_distribution' in self.env['account.move']._fields:
            invoice_vals['analytic_distribution'] = {str(self.analytic_account_a.id): 100}

        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        
        # Register payment via wizard
        Register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        )
        wizard = Register.create({
            'journal_id': self.bank_journal.id,
        })
        self.assertEqual(wizard.distribution_plan_id, plan, "Wizard must detect plan.")
        
        # Create payment
        wizard.action_create_payments()
        
        # Check if payment has the plan
        payment = self.env['account.payment'].search([('reconciled_invoice_ids', 'in', invoice.ids)], limit=1)
        self.assertTrue(payment, "Payment record must exist.")
        self.assertEqual(payment.distribution_plan_id, plan, "Payment must inherit the plan.")
        
        # VERIFY DISTRIBUTION MOVE
        dist_move = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_payment_id', '=', payment.id),
        ], limit=1)
        self.assertTrue(dist_move, "A distribution move MUST be created for this payment.")
        self.assertEqual(dist_move.partner_id, self.partner, "Distribution move should have the same partner.")

    def test_07_unit_extract_analytic_ids_from_code(self):
        """Unit test for the robust code-parsing helper (without triggering field validation)."""
        self.analytic_account_a.code = 'UNITCODE2401'
        
        # Case 1: ID directly
        ids, codes = self.env['account.payment']._extract_analytic_ids_from_distribution({str(self.analytic_account_a.id): 100})
        self.assertIn(self.analytic_account_a.id, ids)
        
        # Case 2: Code directly
        ids, codes = self.env['account.payment']._extract_analytic_ids_from_distribution({'UNITCODE2401': 100})
        self.assertIn('UNITCODE2401', codes)
        
        # Case 3: Mixed string
        ids, codes = self.env['account.payment']._extract_analytic_ids_from_distribution(f"{self.analytic_account_a.id}, UNITCODE2401")
        self.assertIn(self.analytic_account_a.id, ids)
        self.assertIn('UNITCODE2401', codes)
        
        # Case 4: Resolve to accounts
        plan = self._create_rule(name='Unit Plan', source_analytic_ids=[self.analytic_account_a.id])
        detected_plan = self.env['account.payment']._get_distribution_plan_from_distribution({'UNITCODE2401': 100})
        self.assertEqual(detected_plan, plan, "Should resolve code key to the actual plan.")

    def test_08_error_on_empty_plan(self):
        """Verify that posting a payment with a plan that has no lines raises a UserError."""
        from odoo.exceptions import UserError
        # Create a plan without lines
        empty_plan = self.env['aicia.distribution.plan'].create({
            'name': 'Empty Plan',
            'company_id': self.company.id,
        })
        invoice = self._create_invoice(analytic_account=self.analytic_account_a)
        
        # We use the wizard to correctly link and create the payment
        Register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        )
        wizard = Register.create({
            'journal_id': self.bank_journal.id,
            'distribution_plan_id': empty_plan.id,
        })
        
        # The error should be raised during action_post validation (before reconciliation)
        with self.assertRaisesRegex(UserError, "no tiene líneas configuradas"):
            wizard.action_create_payments()

    def test_09_error_on_missing_analytic_in_invoice(self):
        """Verify that posting a payment with a plan but an invoice without analytic raises a UserError."""
        from odoo.exceptions import UserError
        plan = self._create_rule(name='Valid Plan', source_analytic_ids=[self.analytic_account_a.id])
        
        # Invoice WITHOUT analytic
        invoice_no_analytic = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'No analytic',
                'quantity': 1,
                'price_unit': 1000.0,
                'account_id': self.account_revenue.id,
            })],
        })
        invoice_no_analytic.action_post()
        
        # Link invoice manually via wizard (standard Odoo 17)
        Register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice_no_analytic.ids,
        )
        wizard = Register.create({
            'journal_id': self.bank_journal.id,
            'distribution_plan_id': plan.id,
        })
        
        with self.assertRaisesRegex(UserError, "no tiene ninguna distribución analítica configurada"):
            wizard.action_create_payments()
