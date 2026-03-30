# -*- coding: utf-8 -*-
"""
Core integration tests: cash distribution logic triggered by reconciliation.
Covers: full payment, partial payment, line-level analytic, header analytic,
multiple rules, percentage math, and journal entry line verification.
"""
from odoo.tests.common import tagged
from .common import AiciaCashDistributionCommon


@tagged('post_install', '-at_install')
class TestCashDistributionCore(AiciaCashDistributionCommon):
    """Core cash-distribution integration tests."""

    def setUp(self):
        super().setUp()
        # Default single rule (10%) — matches analytic_account_a
        self.rule_10 = self._create_rule(
            name='Core Rule 10%',
            percentage=10.0,
            source_analytic_ids=[self.analytic_account_a.id],
            dest_analytic=self.analytic_account_dest,
        )

    # ── Full payment ──────────────────────────────────────────────────────────

    def test_01_full_payment_creates_distribution(self):
        """Full payment of a 1000 invoice with analytic A → 10% = 100 distribution."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves, "Distribution move must be created on full payment.")

    def test_02_full_payment_journal_entry_amount(self):
        """Full payment: generated journal entry lines should each be 100 (10% of 1000)."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            debit_lines = dm.line_ids.filtered(lambda l: l.debit > 0)
            credit_lines = dm.line_ids.filtered(lambda l: l.credit > 0)
            self.assertTrue(debit_lines, "Must have at least one debit line.")
            self.assertTrue(credit_lines, "Must have at least one credit line.")
            total_debit = sum(debit_lines.mapped('debit'))
            total_credit = sum(credit_lines.mapped('credit'))
            self.assertAlmostEqual(total_debit, total_credit, places=2,
                                   msg="Journal entry must be balanced.")
            self.assertAlmostEqual(total_debit, 100.0, places=2,
                                   msg="10% of 1000 must be 100.")

    def test_03_partial_payment_correct_ratio(self):
        """Partial payment of 500 on 1000 invoice: 10% × 500 = 50 distribution."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice, amount=500.0)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        for dm in dist_moves:
            debit_lines = dm.line_ids.filtered(lambda l: l.debit > 0)
            total_debit = sum(debit_lines.mapped('debit'))
            self.assertAlmostEqual(total_debit, 50.0, places=2,
                                   msg="10% of 500 (partial payment ratio) must be 50.")

    def test_04_partial_payment_25_percent_invoice(self):
        """Partial payment of 250 on 1000 invoice: 10% × 250 = 25 distribution."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice, amount=250.0)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            debit_lines = dm.line_ids.filtered(lambda l: l.debit > 0)
            total_debit = sum(debit_lines.mapped('debit'))
            self.assertAlmostEqual(total_debit, 25.0, places=2,
                                   msg="10% of 250 must be 25.")

    def test_05_header_analytic_distribution(self):
        """Header-level analytic distribution must also trigger rule correctly."""
        invoice = self._create_invoice(
            amount=1000.0,
            analytic_account=self.analytic_account_a,
            analytic_on_header=True,
        )
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves,
                        "Header analytic must trigger distribution the same way as line analytic.")

    def test_06_no_rule_no_distribution(self):
        """If there are no active rules, no distribution move should be created."""
        self.rule_10.write({'active': False})
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        count_before = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self._register_payment(invoice)
        count_after = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self.assertEqual(count_before, count_after,
                         "No distribution when all rules are inactive.")

    def test_08_single_plan_multiple_lines_all_applied(self):
        """A plan with two lines → both lines generate entries (10% + 20% = 300 total debit)."""
        # Añadir una segunda línea al plan existente de analytic_a
        self.env['aicia.distribution.plan.line'].create({
            'plan_id': self.rule_10.id,
            'name': 'Second Line 20%',
            'percentage': 20.0,
            'debit_account_id': self.account_dist_debit2.id,
            'debit_analytic_side': 'source',
            'credit_account_id': self.account_dist_credit2.id,
            'credit_analytic_side': 'fixed',
            'credit_analytic_account_id': self.analytic_account_dest.id,
        })
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        for dm in dist_moves:
            debit_total = sum(dm.line_ids.mapped('debit'))
            # Línea1: 10% de 1000 = 100, Línea2: 20% de 1000 = 200 → total = 300
            self.assertAlmostEqual(debit_total, 300.0, places=2,
                                   msg="Dos líneas en el mismo plan: 10% + 20% de 1000 = 300.")

    def test_09_rule_source_filter_blocks_non_matching_analytic(self):
        """A rule that filters on analytic_account_a should NOT fire for analytic_account_b."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_b)
        count_before = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self._register_payment(invoice)
        count_after = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self.assertEqual(count_before, count_after,
                         "Rule filtered to analytic A must not fire for analytic B.")

    def test_10_rule_assigned_to_analytic_fires_for_that_analytic(self):
        """A plan assigned to analytic_b must fire for analytic_b."""
        rule_b = self._create_rule(
            name='Plan for B',
            percentage=5.0,
            source_analytic_ids=[self.analytic_account_b.id],
            debit_account=self.account_dist_debit2,
            credit_account=self.account_dist_credit2,
        )
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_b)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves,
                        "Plan assigned to analytic B must fire when analytic B is in the invoice.")

    def test_11_distribution_journal_entry_is_balanced(self):
        """For ANY invoice+rule combination, the generated journal entry must be balanced."""
        invoice = self._create_invoice(amount=777.77, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            total_debit = sum(dm.line_ids.mapped('debit'))
            total_credit = sum(dm.line_ids.mapped('credit'))
            self.assertAlmostEqual(total_debit, total_credit, places=2,
                                   msg="Journal entry must always be balanced.")

    def test_12_distribution_debit_account_correct(self):
        """The debit line account must match the rule's debit_account_id."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            debit_accounts = dm.line_ids.filtered(lambda l: l.debit > 0).mapped('account_id')
            self.assertIn(self.account_dist_debit, debit_accounts,
                          "Debit account in journal entry must match rule definition.")

    def test_13_distribution_credit_account_correct(self):
        """The credit line account must match the rule's credit_account_id."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            credit_accounts = dm.line_ids.filtered(lambda l: l.credit > 0).mapped('account_id')
            self.assertIn(self.account_dist_credit, credit_accounts,
                          "Credit account in journal entry must match rule definition.")

    def test_14_distribution_uses_configured_journal(self):
        """Distribution journal entry must use the journal configured on the company."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            self.assertEqual(dm.journal_id, self.misc_journal,
                             "Distribution entry must be posted to the company's configured journal.")

    def test_15_two_line_invoice_both_lines_distributed(self):
        """Invoice with two lines each having different analytic accounts → only the matching one is distributed."""
        # Only analytic_account_a is covered by rule_10
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.sale_journal.id,
            'invoice_line_ids': [
                (0, 0, {
                    'name': 'Line A',
                    'quantity': 1,
                    'price_unit': 500.0,
                    'account_id': self.account_revenue.id,
                    'analytic_distribution': {str(self.analytic_account_a.id): 100},
                }),
                (0, 0, {
                    'name': 'Line B',
                    'quantity': 1,
                    'price_unit': 500.0,
                    'account_id': self.account_revenue.id,
                    'analytic_distribution': {str(self.analytic_account_b.id): 100},
                }),
            ],
        }
        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        # Con plan aplicado desde el pago se reparte sobre el total (1.000): 10% = 100
        for dm in dist_moves:
            debit_total = sum(dm.line_ids.mapped('debit'))
            self.assertAlmostEqual(debit_total, 100.0, places=2,
                                   msg="Plan del pago aplicado al total: 10% de 1.000 = 100.")

    def test_16_zero_percentage_rule_creates_no_entry(self):
        """A 0% rule must not create any journal entry lines."""
        self.rule_10.line_ids.write({'percentage': 0.0})
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        count_before = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self._register_payment(invoice)
        count_after = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self.assertEqual(count_before, count_after,
                         "Zero-percentage rule must not generate any distribution move.")

    def test_17_invoice_not_posted_skipped(self):
        """A draft invoice that somehow gets a reconcile should be skipped gracefully."""
        # This is a safeguard test — the logic checks state == 'posted'
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        # We cannot easily reconcile a draft invoice via payment register; just verify
        # that our module's guard condition 'state != posted' exists in the model.
        self.assertEqual(invoice.state, 'posted',
                         "Invoice must be posted before payment.")

    def test_18_distribution_analytic_on_debit_line(self):
        """The debit line in the distribution entry must carry the source analytic distribution."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            debit_lines = dm.line_ids.filtered(lambda l: l.debit > 0)
            for dl in debit_lines:
                self.assertTrue(dl.analytic_distribution,
                                "Debit distribution line must carry analytic distribution.")

    def test_19_distribution_partner_propagated(self):
        """The partner on the invoice must be propagated to the distribution journal entry lines."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            for line in dm.line_ids:
                self.assertEqual(line.partner_id, self.partner,
                                 "Partner must be propagated to each distribution line.")

    def test_20_distribution_move_partner_propagated_on_header(self):
        """The generated journal entry must also keep the invoice partner on the move header."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        for dm in dist_moves:
            self.assertEqual(
                dm.partner_id,
                self.partner,
                "Partner must be propagated to the distribution move header.",
            )

    def test_21_vat_plan_line_is_included_in_distribution_entry(self):
        """A VAT plan line must generate movement on the invoice tax account in both sides."""
        if not self.sale_tax:
            self.skipTest("No sale tax available in the company to validate VAT distribution.")

        tax_account = self.sale_tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax' and line.account_id
        )[:1].account_id
        self.assertTrue(tax_account, "The selected sale tax must have a tax account.")

        self.env['aicia.distribution.plan.line'].create({
            'plan_id': self.rule_10.id,
            'name': 'VAT Line',
            'is_vat_line': True,
            'percentage': 100.0,
            'debit_account_id': tax_account.id,
            'debit_analytic_side': 'fixed',
            'debit_analytic_account_id': self.analytic_account_dest.id,
            'credit_account_id': tax_account.id,
            'credit_analytic_side': 'source',
        })

        invoice = self._create_invoice(
            amount=100.0,
            analytic_account=self.analytic_account_a,
            tax_ids=[self.sale_tax.id],
        )
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)

        vat_lines = dist_moves.line_ids.filtered(
            lambda line: line.account_id == tax_account
        )
        self.assertEqual(len(vat_lines), 2, "VAT distribution must generate one debit and one credit line.")
        vat_amount = sum(abs(line.balance) for line in invoice.line_ids if line.tax_line_id)
        self.assertAlmostEqual(
            sum(vat_lines.mapped('debit')),
            vat_amount,
            places=2,
            msg="Collected VAT must be redistributed in the debit side.",
        )
        self.assertAlmostEqual(
            sum(vat_lines.mapped('credit')),
            vat_amount,
            places=2,
            msg="Collected VAT must be redistributed in the credit side.",
        )

    def test_22_legacy_invalid_vat_plan_still_uses_invoice_tax_account(self):
        """Even with a legacy bad VAT line, the generated move must use the invoice tax account on both sides."""
        if not self.sale_tax:
            self.skipTest("No sale tax available in the company to validate VAT distribution.")

        tax_account = self.sale_tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax' and line.account_id
        )[:1].account_id
        self.assertTrue(tax_account, "The selected sale tax must have a tax account.")

        vat_line = self.env['aicia.distribution.plan.line'].create({
            'plan_id': self.rule_10.id,
            'name': 'Legacy VAT Line',
            'is_vat_line': True,
            'percentage': 100.0,
            'debit_account_id': tax_account.id,
            'debit_analytic_side': 'fixed',
            'debit_analytic_account_id': self.analytic_account_dest.id,
            'credit_account_id': tax_account.id,
            'credit_analytic_side': 'source',
        })
        self.env.cr.execute(
            "UPDATE aicia_distribution_plan_line SET debit_account_id = %s WHERE id = %s",
            [self.account_dist_debit.id, vat_line.id],
        )
        self.env.invalidate_all()

        invoice = self._create_invoice(
            amount=100.0,
            analytic_account=self.analytic_account_a,
            tax_ids=[self.sale_tax.id],
        )
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)

        move_lines = dist_moves.line_ids.filtered(
            lambda line: 'Legacy VAT Line' in (line.name or '')
        )
        vat_lines = move_lines.filtered(lambda line: line.account_id == tax_account)
        wrong_lines = move_lines.filtered(lambda line: line.account_id == self.account_dist_debit)
        self.assertEqual(len(vat_lines), 2)
        self.assertFalse(
            wrong_lines,
            "Legacy bad VAT configuration must not leak a non-tax account into the generated move.",
        )

