# -*- coding: utf-8 -*-
"""
Reversal tests: verify that unlinking a partial reconcile correctly
cancels / reverses the generated distribution journal entries.
"""
from odoo.tests.common import tagged
from .common import AiciaCashDistributionCommon


@tagged('post_install', '-at_install')
class TestCashDistributionReversal(AiciaCashDistributionCommon):
    """Tests for reversal/cleanup when reconciliation is undone."""

    def setUp(self):
        super().setUp()
        self.rule = self._create_rule(
            name='Reversal Rule 10%',
            percentage=10.0,
            source_analytic_ids=[self.analytic_account_a.id],
        )

    def _pay_and_get_dist_moves(self, amount=1000.0, pay_amount=None):
        """Helper: create invoice, pay, return (invoice, reconciles, dist_moves)."""
        invoice = self._create_invoice(amount=amount, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice, amount=pay_amount)
        dist_moves = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', reconciles.ids),
        ])
        return invoice, reconciles, dist_moves

    # ── Basic reversal ────────────────────────────────────────────────────────

    def test_01_reversal_removes_distribution_log(self):
        """When a reconcile is undone, the distribution move log must be removed."""
        invoice, reconciles, dist_moves = self._pay_and_get_dist_moves()
        self.assertTrue(dist_moves, "Prerequisite: distribution move must exist before reversal.")
        dm_ids = dist_moves.ids
        # Undo the reconciliation
        reconciles.unlink()
        # Logs must be gone
        remaining = self.env['aicia.distribution.move'].browse(dm_ids).exists()
        self.assertFalse(remaining,
                         "Distribution move log must be deleted when reconcile is unlinked.")

    def test_02_reversal_cancels_journal_entry(self):
        """When a reconcile is undone, the linked journal entry must be cancelled."""
        invoice, reconciles, dist_moves = self._pay_and_get_dist_moves()
        move_ids = dist_moves.mapped('move_id').ids
        reconciles.unlink()
        # The journal entry should be in 'cancel' state (not 'posted')
        moves = self.env['account.move'].browse(move_ids)
        for move in moves:
            self.assertNotEqual(move.state, 'posted',
                                "Journal entry must not remain 'posted' after reconcile removal.")

    def test_03_reversal_partial_payment(self):
        """Partial payment reversal: only that partial reconcile's distribution is removed."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        rec1 = self._register_payment(invoice, amount=400.0)
        rec2 = self._register_payment(invoice, amount=400.0)

        dm1 = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', rec1.ids),
        ])
        dm2 = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', rec2.ids),
        ])
        self.assertTrue(dm1, "First partial payment must create distribution.")
        self.assertTrue(dm2, "Second partial payment must create distribution.")

        # Undo only the first reconcile
        dm1_ids = dm1.ids
        rec1.unlink()
        remaining_dm1 = self.env['aicia.distribution.move'].browse(dm1_ids).exists()
        self.assertFalse(remaining_dm1,
                         "First distribution log must be removed after first reconcile is unlinked.")
        # Second distribution must remain intact
        self.assertTrue(dm2.exists(),
                        "Second distribution log must remain after only first reconcile is removed.")

    def test_04_re_reconcile_after_reversal_creates_new_distribution(self):
        """After undoing a payment and re-paying, a fresh distribution must be created."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        rec1 = self._register_payment(invoice)
        dm1 = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', rec1.ids),
        ])
        dm1_ids = set(dm1.ids)

        # Undo
        rec1.unlink()
        # The invoice should be open again
        self.assertAlmostEqual(invoice.amount_residual, 1000.0, places=2,
                               msg="Invoice must be fully open again after payment reversal.")

        # Re-pay
        rec2 = self._register_payment(invoice)
        dm2 = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', rec2.ids),
        ])
        # New distribution logs must have been created (different IDs)
        new_ids = set(dm2.ids)
        self.assertTrue(new_ids, "New distribution must be created after re-payment.")
        self.assertTrue(
            new_ids.isdisjoint(dm1_ids),
            "Re-payment must create brand-new distribution log records.",
        )

    def test_05_reversal_does_not_affect_other_invoices(self):
        """Reversing one invoice's reconcile must not affect other invoices' distributions."""
        invoice1 = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        invoice2 = self._create_invoice(amount=500.0, analytic_account=self.analytic_account_a)

        rec1 = self._register_payment(invoice1)
        rec2 = self._register_payment(invoice2)

        dm2 = self.env['aicia.distribution.move'].search([
            ('partial_reconcile_id', 'in', rec2.ids),
        ])
        dm2_ids = dm2.ids

        # Undo only invoice1
        rec1.unlink()

        # Invoice2 distributions must be intact
        self.assertTrue(
            self.env['aicia.distribution.move'].browse(dm2_ids).exists(),
            "Distributions for invoice2 must not be affected by reversal of invoice1.",
        )

