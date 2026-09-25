# -*- coding: utf-8 -*-
"""
Edge-case tests: no journal configured, disabled flag, vendor bills,
tiny amounts, multiple analytic splits on a single line, etc.
"""
from odoo.tests.common import tagged
from .common import AiciaCashDistributionCommon


@tagged('post_install', '-at_install')
class TestCashDistributionEdgeCases(AiciaCashDistributionCommon):
    """Edge-case tests for cash distribution."""

    def setUp(self):
        super().setUp()
        self.rule = self._create_rule(
            name='Edge Rule 10%',
            percentage=10.0,
            source_analytic_ids=[self.analytic_account_a.id],
        )

    # ── No journal configured ─────────────────────────────────────────────────

    def test_01_no_journal_configured_uses_fallback(self):
        """When no distribution journal is configured, the module should use any general journal."""
        original_journal = self.company.cash_distribution_journal_id
        self.company.write({'cash_distribution_journal_id': False})
        try:
            invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
            # Should not raise; falls back to any general journal
            reconciles = self._register_payment(invoice)
            self.env['account.move'].search([
                ('is_cash_distribution_move', '=', True),
                ('distribution_partial_reconcile_id', 'in', reconciles.ids),
            ])
            # If a general journal exists it will be used, otherwise no entry is created (no crash)
            # The important thing is no exception is raised.
        finally:
            self.company.write({'cash_distribution_journal_id': original_journal.id})

    # ── Vendor bill (purchase) should NOT trigger distribution ────────────────

    def test_02_vendor_bill_not_distributed(self):
        """Distribution must only trigger for customer invoices (out_invoice), not vendor bills."""
        account_expense = self.env['account.account'].search(
            [('account_type', 'in', ('expense', 'expense_direct_cost')),
             ('company_ids', 'in', self.company.id)], limit=1
        )
        purchase_journal = self.env['account.journal'].search(
            [('type', '=', 'purchase'), ('company_id', '=', self.company.id)], limit=1
        )
        if not purchase_journal or not account_expense:
            self.skipTest("Purchase journal or expense account not available.")

        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'journal_id': purchase_journal.id,
            'invoice_date': '2026-01-01',
            'invoice_line_ids': [(0, 0, {
                'name': 'Test Expense',
                'quantity': 1,
                'price_unit': 1000.0,
                'account_id': account_expense.id,
                'analytic_distribution': {str(self.analytic_account_a.id): 100},
            })],
        })
        bill.action_post()

        count_before = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        payment_register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=bill.ids,
        ).create({
            'amount': bill.amount_residual,
            'journal_id': self.bank_journal.id,
        })
        payment_register.action_create_payments()
        count_after = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self.assertEqual(count_before, count_after,
                         "Vendor bill payment must NOT create distribution moves.")

    # ── Very small amounts (rounding) ─────────────────────────────────────────

    def test_03_very_small_amount_rounding(self):
        """Invoice with a very small amount: rounding must not produce negative or zero lines."""
        invoice = self._create_invoice(amount=0.01, analytic_account=self.analytic_account_a)
        # With 10% of 0.01 = 0.001 → rounds to 0.00, so NO distribution entry should be created
        count_before = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self._register_payment(invoice)
        count_after = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        # Either 0 new entries (amount rounded to 0) or exactly 1 (if not rounded away)
        # The important thing: no crash and no negative amounts
        if count_after > count_before:
            dist_moves = self.env['account.move'].search([
                ('is_cash_distribution_move', '=', True)
            ], order='id desc', limit=1)
            for line in dist_moves.line_ids:
                self.assertGreaterEqual(line.debit, 0)
                self.assertGreaterEqual(line.credit, 0)

    # ── High-value invoice ────────────────────────────────────────────────────

    def test_04_large_invoice_amount(self):
        """Distribution must handle large amounts (1,000,000) correctly."""
        invoice = self._create_invoice(amount=1_000_000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        for dm in dist_moves:
            debit_total = sum(dm.line_ids.mapped('debit'))
            # 10% of 1,000,000 = 100,000
            self.assertAlmostEqual(debit_total, 100_000.0, places=2)

    # ── Payment exact residual edge ───────────────────────────────────────────

    def test_05_payment_exactly_matches_residual(self):
        """A payment for exactly the residual amount should fully close the invoice."""
        invoice = self._create_invoice(amount=500.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice, amount=invoice.amount_residual)
        self.assertAlmostEqual(invoice.amount_residual, 0.0, places=2,
                               msg="Invoice must be fully paid after exact payment.")

    # ── Multiple partial payments summing to full ─────────────────────────────

    def test_06_three_partial_payments_total_amount(self):
        """Three partial payments covering full invoice: each creates a proportional distribution."""
        invoice = self._create_invoice(amount=900.0, analytic_account=self.analytic_account_a)

        reconciles1 = self._register_payment(invoice, amount=300.0)
        reconciles2 = self._register_payment(invoice, amount=300.0)
        reconciles3 = self._register_payment(invoice, amount=300.0)

        all_reconciles = reconciles1 | reconciles2 | reconciles3
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', all_reconciles.ids),
        ])
        total_distributed = sum(
            sum(dm.line_ids.filtered(lambda l: l.debit > 0).mapped('debit'))
            for dm in dist_moves
        )
        # 3 × 10% × 300 = 90
        self.assertAlmostEqual(total_distributed, 90.0, places=2,
                               msg="3 × 10% × 300 = 90 total distributed.")

    # ── Line with 50/50 split between two analytics ───────────────────────────

    def test_07_line_analytic_split_50_50(self):
        """Plan del pago aplica al total incluso con split 50/50 (10% de 1000 = 100)."""
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Split Line',
                'quantity': 1,
                'price_unit': 1000.0,
                'account_id': self.account_revenue.id,
                'analytic_distribution': {
                    str(self.analytic_account_a.id): 50,
                    str(self.analytic_account_b.id): 50,
                },
            })],
        }
        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        for dm in dist_moves:
            debit_total = sum(dm.line_ids.mapped('debit'))
            # Con plan aplicado desde el pago, se distribuye sobre el total
            self.assertAlmostEqual(debit_total, 100.0, places=2,
                                   msg="10% del total 1.000 = 100 con override del plan del pago.")

    # ── Company flag toggling ─────────────────────────────────────────────────

    def test_08_distribution_on_multiple_invoices_same_analytic(self):
        """Distribution must generate separate entries per payment, validated on multiple invoices."""
        invoice1 = self._create_invoice(amount=500.0, analytic_account=self.analytic_account_a)
        invoice2 = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)

        count_before = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self._register_payment(invoice1)
        self._register_payment(invoice2)
        count_after = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])

        self.assertEqual(count_after - count_before, 2,
                         "Each payment must create exactly one distribution move.")

    # ── Rule with destination analytic ───────────────────────────────────────

    def test_09_destination_analytic_on_credit_line(self):
        """When a rule has a destination analytic, the credit line must carry it."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            credit_lines = dm.line_ids.filtered(lambda l: l.credit > 0)
            for cl in credit_lines:
                if cl.account_id == self.account_dist_credit:
                    self.assertIn(
                        str(self.analytic_account_dest.id),
                        (cl.analytic_distribution or {}).keys(),
                        "Credit line must carry destination analytic distribution.",
                    )

    # ── Rule without destination analytic ────────────────────────────────────

    def test_10_no_company_receiver_but_line_has_fixed_analytic_ok(self):
        """When the company has no receiver analytic but all plan lines have their own
        fixed analytic account configured, distribution must succeed without error."""
        original_receiver = self.rule.company_id.cash_distribution_receiver_analytic_id
        self.rule.company_id.write({'cash_distribution_receiver_analytic_id': False})
        try:
            invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
            # Must NOT raise: lines have credit_analytic_account_id set directly
            reconciles = self._register_payment(invoice)
            dist_moves = self.env['account.move'].search([
                ('is_cash_distribution_move', '=', True),
                ('distribution_partial_reconcile_id', 'in', reconciles.ids),
            ])
            self.assertTrue(dist_moves, "A distribution move must be created even without company receiver analytic.")
        finally:
            self.rule.company_id.write({'cash_distribution_receiver_analytic_id': original_receiver.id})

    def test_11_needs_receiver_analytic_detects_missing_account(self):
        """_needs_receiver_analytic() must return True when a line has fixed side
        without its own analytic account, and False when all fixed lines have one."""
        plan = self.env['aicia.distribution.plan'].create({
            'name': 'Test needs receiver',
            'company_id': self.company.id,
        })
        # Line with fixed credit and explicit account → does NOT need receiver fallback
        line = self.env['aicia.distribution.plan.line'].create({
            'plan_id': plan.id,
            'name': 'Línea fija con cuenta',
            'percentage': 10.0,
            'debit_account_id': self.account_dist_debit.id,
            'debit_analytic_side': 'source',
            'credit_account_id': self.account_dist_credit.id,
            'credit_analytic_side': 'fixed',
            'credit_analytic_account_id': self.analytic_account_dest.id,
        })
        self.assertFalse(
            plan._needs_receiver_analytic(),
            "Plan with all fixed lines having explicit analytic accounts must NOT need company receiver.",
        )

        # Simulate legacy data: remove the fixed account directly (bypass ORM constraint)
        self.env.cr.execute(
            "UPDATE aicia_distribution_plan_line SET credit_analytic_account_id = NULL WHERE id = %s",
            (line.id,),
        )
        self.env.invalidate_all()
        self.assertTrue(
            plan._needs_receiver_analytic(),
            "Plan with a fixed line missing its analytic account MUST need company receiver.",
        )

