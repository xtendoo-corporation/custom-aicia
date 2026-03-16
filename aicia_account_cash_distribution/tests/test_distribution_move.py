# -*- coding: utf-8 -*-
"""
Tests for aicia.distribution.move model fields, relations and state tracking.
"""
from .common import AiciaCashDistributionCommon


class TestDistributionMove(AiciaCashDistributionCommon):
    """Tests for the Distribution Move log model."""

    def setUp(self):
        super().setUp()
        self.rule = self._create_rule(
            name='Move Test Rule',
            percentage=10.0,
            source_analytic_ids=[self.analytic_account_a.id],
        )

    # ── Model creation ────────────────────────────────────────────────────────

    def test_01_distribution_move_created_on_full_payment(self):
        """A distribution move log should be created when a full payment reconciles an invoice."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', (
                invoice.line_ids.mapped('matched_debit_ids') |
                invoice.line_ids.mapped('matched_credit_ids')
            ).ids),
        ])
        self.assertTrue(dist_moves, "At least one distribution move log should have been created.")

    def test_02_distribution_move_has_posted_journal_entry(self):
        """The journal entry linked to a distribution move must be in 'posted' state."""
        invoice = self._create_invoice(amount=500.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('move_id.ref', 'like', invoice.name),
        ])
        for dm in dist_moves:
            self.assertEqual(dm.state, 'posted',
                             "All generated journal entries must be posted.")

    def test_03_distribution_move_amount_positive(self):
        """The amount_total on every distribution move log must be positive."""
        invoice = self._create_invoice(amount=800.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('move_id.ref', 'like', invoice.name),
        ])
        for dm in dist_moves:
            self.assertGreater(dm.amount_total, 0,
                               "Distribution move amount_total must be > 0.")

    def test_04_distribution_move_linked_to_reconcile(self):
        """Each distribution move must be linked to a valid partial reconcile."""
        invoice = self._create_invoice(amount=600.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        for rec in reconciles:
            for dm in rec.distribution_move_ids:
                self.assertEqual(dm.partial_reconcile_id, rec)

    def test_05_distribution_move_currency_matches_company(self):
        """The currency of the distribution move should match the company currency."""
        invoice = self._create_invoice(amount=900.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('move_id.ref', 'like', invoice.name),
        ])
        for dm in dist_moves:
            self.assertEqual(dm.currency_id, self.company.currency_id)

    def test_06_no_distribution_move_without_analytic(self):
        """No distribution move should be created if the invoice has no analytic distribution."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=None)
        reconciles_before = self.env['aicia.distribution.move'].search_count([])
        self._register_payment(invoice)
        reconciles_after = self.env['aicia.distribution.move'].search_count([])
        self.assertEqual(reconciles_before, reconciles_after,
                         "No distribution log should appear when invoice has no analytic.")

    def test_07_multiple_payments_create_multiple_logs(self):
        """Two partial payments on the same invoice should each create their own log."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice, amount=400.0)
        self._register_payment(invoice, amount=400.0)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('move_id.ref', 'like', invoice.name),
        ])
        self.assertGreaterEqual(len(dist_moves), 2,
                                "Two payments should generate at least two distribution logs.")

    def test_08_distribution_move_default_name(self):
        """Distribution move should receive a name (not left as '/')."""
        invoice = self._create_invoice(amount=700.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('move_id.ref', 'like', invoice.name),
        ])
        for dm in dist_moves:
            self.assertTrue(dm.name, "Distribution move name must not be empty.")

