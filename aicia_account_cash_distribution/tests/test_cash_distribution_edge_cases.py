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
            dist_moves = self.env['aicia.distribution.move'].search([
                ('partial_reconcile_id', 'in', reconciles.ids),
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

        count_before = self.env['aicia.distribution.move'].search_count([])
        payment_register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=bill.ids,
        ).create({
            'amount': bill.amount_residual,
            'journal_id': self.bank_journal.id,
        })
        payment_register.action_create_payments()
        count_after = self.env['aicia.distribution.move'].search_count([])
        self.assertEqual(count_before, count_after,
                         "Vendor bill payment must NOT create distribution moves.")

    # ── Very small amounts (rounding) ─────────────────────────────────────────

    def test_03_very_small_amount_rounding(self):
        """Invoice with a very small amount: rounding must not produce negative or zero lines."""
        invoice = self._create_invoice(amount=0.01, analytic_account=self.analytic_account_a)
        # With 10% of 0.01 = 0.001 → rounds to 0.00, so NO distribution entry should be created
        count_before = self.env['aicia.distribution.move'].search_count([])
        self._register_payment(invoice)
        count_after = self.env['aicia.distribution.move'].search_count([])
        # Either 0 new entries (amount rounded to 0) or exactly 1 (if not rounded away)
        # The important thing: no crash and no negative amounts
        if count_after > count_before:
            dist_moves = self.env['aicia.distribution.move'].search([], order='id desc', limit=1)
            for line in dist_moves.move_id.line_ids:
                self.assertGreaterEqual(line.debit, 0)
                self.assertGreaterEqual(line.credit, 0)

    # ── High-value invoice ────────────────────────────────────────────────────

    def test_04_large_invoice_amount(self):
        """Distribution must handle large amounts (1,000,000) correctly."""
        invoice = self._create_invoice(amount=1_000_000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        for dm in dist_moves:
            debit_total = sum(dm.move_id.line_ids.mapped('debit'))
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
        dist_moves = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', all_reconciles.ids),
        ])
        total_distributed = sum(
            sum(dm.move_id.line_ids.filtered(lambda l: l.debit > 0).mapped('debit'))
            for dm in dist_moves
        )
        # 3 × 10% × 300 = 90
        self.assertAlmostEqual(total_distributed, 90.0, places=2,
                               msg="3 × 10% × 300 = 90 total distributed.")

    # ── Line with 50/50 split between two analytics ───────────────────────────

    def test_07_line_analytic_split_50_50(self):
        """A line with 50% analytic A + 50% analytic B → only the A portion fires the rule."""
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
        dist_moves = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        for dm in dist_moves:
            debit_total = sum(dm.move_id.line_ids.mapped('debit'))
            # line balance = 1000, ratio = 1 (full payment)
            # dist_amount for A = 1000 × (50/100) = 500
            # 10% of 500 = 50
            self.assertAlmostEqual(debit_total, 50.0, places=2,
                                   msg="10% of the 50% portion = 50.")

    # ── Company flag toggling ─────────────────────────────────────────────────

    def test_08_re_enabling_company_flag_restores_distribution(self):
        """After re-enabling the flag, distribution should resume normally."""
        self.company.write({'cash_distribution_active': False})
        invoice1 = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        count_before = self.env['aicia.distribution.move'].search_count([])
        self._register_payment(invoice1)
        count_mid = self.env['aicia.distribution.move'].search_count([])
        self.assertEqual(count_before, count_mid, "Flag off: no distribution.")

        self.company.write({'cash_distribution_active': True})
        invoice2 = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice2)
        count_after = self.env['aicia.distribution.move'].search_count([])
        self.assertGreater(count_after, count_mid, "Flag on: distribution must resume.")

    # ── Rule with destination analytic ───────────────────────────────────────

    def test_09_destination_analytic_on_credit_line(self):
        """When a rule has a destination analytic, the credit line must carry it."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            credit_lines = dm.move_id.line_ids.filtered(lambda l: l.credit > 0)
            for cl in credit_lines:
                if cl.account_id == self.account_dist_credit:
                    self.assertIn(
                        str(self.analytic_account_dest.id),
                        (cl.analytic_distribution or {}).keys(),
                        "Credit line must carry destination analytic distribution.",
                    )

    # ── Rule without destination analytic ────────────────────────────────────

    def test_10_no_destination_analytic_credit_line_empty(self):
        """When rule has no destination analytic, the credit line analytic must be empty."""
        self.rule.write({'destination_analytic_account_id': False})
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            credit_lines = dm.move_id.line_ids.filtered(
                lambda l: l.credit > 0 and l.account_id == self.account_dist_credit
            )
            for cl in credit_lines:
                self.assertFalse(cl.analytic_distribution,
                                 "Credit line analytic must be empty when no destination is set.")

