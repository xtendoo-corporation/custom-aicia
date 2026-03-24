# -*- coding: utf-8 -*-
"""
Tests for asientos de distribución (account.move con flag is_cash_distribution_move).
"""
from .common import AiciaCashDistributionCommon


class TestDistributionMove(AiciaCashDistributionCommon):
    """Tests for los asientos de distribución (sin modelo intermedio)."""

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
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', (
                invoice.line_ids.mapped('matched_debit_ids') |
                invoice.line_ids.mapped('matched_credit_ids')
            ).ids),
        ])
        self.assertTrue(dist_moves, "At least one distribution move log should have been created.")

    def test_02_distribution_move_has_posted_journal_entry(self):
        """The journal entry linked to a distribution move must be in 'posted' state."""
        invoice = self._create_invoice(amount=500.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('ref', 'like', invoice.name),
        ])
        for dm in dist_moves:
            self.assertEqual(dm.state, 'posted',
                             "All generated journal entries must be posted.")

    def test_03_distribution_move_amount_positive(self):
        """Sum of debit lines on distribution move must be positive."""
        invoice = self._create_invoice(amount=800.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('ref', 'like', invoice.name),
        ])
        for dm in dist_moves:
            self.assertGreater(
                sum(dm.line_ids.mapped('debit')),
                0,
                "Distribution move total debit must be > 0.",
            )

    def test_04_distribution_move_linked_to_reconcile(self):
        """Each distribution move must be linked to a valid partial reconcile."""
        invoice = self._create_invoice(amount=600.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        for rec in reconciles:
            self.assertTrue(rec.distribution_move_id)
            self.assertEqual(rec.distribution_move_id.distribution_partial_reconcile_id, rec)

    def test_05_distribution_move_currency_matches_company(self):
        """The currency of the distribution move should match the company currency."""
        invoice = self._create_invoice(amount=900.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('ref', 'like', invoice.name),
        ])
        for dm in dist_moves:
            self.assertEqual(dm.currency_id, self.company.currency_id)

    def test_06_no_distribution_move_without_analytic(self):
        """No distribution move should be created if the invoice has no analytic distribution."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=None)
        reconciles_before = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self._register_payment(invoice)
        reconciles_after = self.env['account.move'].search_count([('is_cash_distribution_move', '=', True)])
        self.assertEqual(reconciles_before, reconciles_after,
                         "No distribution log should appear when invoice has no analytic.")

    def test_07_multiple_payments_create_multiple_logs(self):
        """Two partial payments on the same invoice should each create their own log."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice, amount=400.0)
        self._register_payment(invoice, amount=400.0)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('ref', 'like', invoice.name),
        ])
        self.assertGreaterEqual(len(dist_moves), 2,
                                "Two payments should generate at least two distribution logs.")

    def test_08_distribution_move_default_name(self):
        """Distribution move should receive a name (not left as '/')."""
        invoice = self._create_invoice(amount=700.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('ref', 'like', invoice.name),
        ])
        for dm in dist_moves:
            self.assertTrue(dm.name, "Distribution move name must not be empty.")

    def test_09_source_analytic_account_ids_populated(self):
        """Distribution move must store the source analytic account that triggered it."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves)
        for dm in dist_moves:
            self.assertIn(
                self.analytic_account_a,
                dm.distribution_source_analytic_ids,
                "Source analytic account_a must be stored in the distribution move.",
            )

    def test_10_analytic_account_distribution_move_count(self):
        """The analytic account distribution_move_count must reflect generated logs."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        count_before = self.analytic_account_a.distribution_move_count
        self._register_payment(invoice)
        self.analytic_account_a.invalidate_recordset(['distribution_move_count'])
        count_after = self.analytic_account_a.distribution_move_count
        self.assertGreater(count_after, count_before,
                           "distribution_move_count must increase after a payment distribution.")

    def test_11_analytic_account_links_to_distribution_moves(self):
        """The analytic account's distribution_move_ids must include the generated log."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        reconciles = self._register_payment(invoice)
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        for dm in dist_moves:
            self.assertIn(
                dm,
                self.analytic_account_a.distribution_move_ids,
                "Distribution move must appear in analytic_account_a.distribution_move_ids.",
            )

    def test_12_payment_register_autofills_distribution_plan(self):
        """The payment wizard should autofill the distribution plan from the invoice analytic."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'amount': invoice.amount_residual,
            'journal_id': self.bank_journal.id,
        })
        self.assertEqual(
            wizard.distribution_plan_id,
            self.rule,
            "The payment register wizard must autofill the plan from the invoice analytic.",
        )

    def test_13_created_payment_stores_distribution_plan(self):
        """The created inbound payment must keep the distribution plan chosen in the wizard."""
        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        self._register_payment(invoice)
        payments = self._get_invoice_payments(invoice)
        self.assertTrue(payments, "A payment should have been created for the invoice.")
        self.assertIn(
            self.rule,
            payments.mapped('distribution_plan_id'),
            "The generated payment must store the detected distribution plan.",
        )

    def test_14_manual_plan_on_wizard_overrides_detected_plan_and_is_applied(self):
        """A manually chosen plan on the wizard must be copied to the payment and executed."""
        manual_plan = self.env['aicia.distribution.plan'].create({
            'name': 'Manual Wizard Plan',
            'company_id': self.company.id,
            'receiver_analytic_account_id': self.analytic_account_dest.id,
            'active': True,
        })
        self.env['aicia.distribution.plan.line'].create({
            'plan_id': manual_plan.id,
            'name': 'Manual Line 7%',
            'percentage': 7.0,
            'debit_account_id': self.account_dist_debit.id,
            'debit_analytic_side': 'source',
            'credit_account_id': self.account_dist_credit.id,
            'credit_analytic_side': 'receiver',
        })

        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'amount': invoice.amount_residual,
            'journal_id': self.bank_journal.id,
            'distribution_plan_id': manual_plan.id,
        })
        wizard.action_create_payments()

        payments = self._get_invoice_payments(invoice)
        self.assertTrue(payments)
        self.assertIn(
            manual_plan,
            payments.mapped('distribution_plan_id'),
            "Manual plan from wizard must be copied to the generated payment.",
        )

        reconciles = invoice.line_ids.mapped('matched_debit_ids') | invoice.line_ids.mapped('matched_credit_ids')
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])
        self.assertTrue(dist_moves, "A distribution move should be generated.")
        self.assertIn(
            manual_plan,
            dist_moves.mapped('distribution_applied_plan_ids'),
            "The manually selected payment plan must be the one applied on reconciliation.",
        )

    def test_15_customer_refund_does_not_show_or_copy_distribution_plan(self):
        """Distribution plan is only for sales invoices, not customer refunds."""
        invoice = self._create_invoice(
            amount=1000.0,
            analytic_account=self.analytic_account_a,
            move_type='out_refund',
        )
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'amount': invoice.amount_residual,
            'journal_id': self.bank_journal.id,
        })
        self.assertEqual(wizard.partner_type, 'customer')
        self.assertFalse(wizard.show_distribution_plan_id)
        self.assertFalse(wizard.distribution_plan_id)

        wizard.action_create_payments()
        payments = self._get_invoice_payments(invoice)
        self.assertTrue(payments)
        self.assertFalse(payments.mapped('distribution_plan_id'))

    def test_16_header_analytic_plan_has_priority_over_invoice_lines(self):
        """If header and lines disagree, the payment must use the plan from the header analytic."""
        if 'analytic_distribution' not in self.env['account.move']._fields:
            self.skipTest("La cabecera analítica no está disponible en este entorno.")

        rule_b = self._create_rule(
            name='Move Test Rule B',
            percentage=5.0,
            source_analytic_ids=[self.analytic_account_b.id],
            debit_account=self.account_dist_debit2,
            credit_account=self.account_dist_credit2,
        )
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.sale_journal.id,
            'analytic_distribution': {str(self.analytic_account_a.id): 100},
            'invoice_line_ids': [(0, 0, {
                'name': 'Header must win',
                'quantity': 1,
                'price_unit': 1000.0,
                'account_id': self.account_revenue.id,
                'analytic_distribution': {str(self.analytic_account_b.id): 100},
            })],
        })
        invoice.action_post()

        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'amount': invoice.amount_residual,
            'journal_id': self.bank_journal.id,
        })

        self.assertEqual(wizard.distribution_plan_id, self.rule)
        self.assertNotEqual(wizard.distribution_plan_id, rule_b)

        wizard.action_create_payments()
        payments = self._get_invoice_payments(invoice)
        self.assertTrue(payments)
        self.assertIn(
            self.rule,
            payments.mapped('distribution_plan_id'),
            "El pago debe guardar el plan de la analítica definida en cabecera.",
        )

    def test_17_multiple_invoices_with_distinct_header_plans_do_not_autofill(self):
        """Grouped payments must stay empty when header analytics point to different plans."""
        if 'analytic_distribution' not in self.env['account.move']._fields:
            self.skipTest("La cabecera analítica no está disponible en este entorno.")

        self._create_rule(
            name='Move Test Rule B',
            percentage=5.0,
            source_analytic_ids=[self.analytic_account_b.id],
            debit_account=self.account_dist_debit2,
            credit_account=self.account_dist_credit2,
        )
        invoice_a = self._create_invoice(
            amount=1000.0,
            analytic_account=self.analytic_account_a,
            analytic_on_header=True,
        )
        invoice_b = self._create_invoice(
            amount=500.0,
            analytic_account=self.analytic_account_b,
            analytic_on_header=True,
        )

        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=(invoice_a + invoice_b).ids,
        ).create({
            'amount': invoice_a.amount_residual + invoice_b.amount_residual,
            'journal_id': self.bank_journal.id,
            'group_payment': True,
        })

        self.assertFalse(
            wizard.distribution_plan_id,
            "No debe autocompletarse un plan si las facturas tienen planes de cabecera distintos.",
        )

    def test_18_payment_plan_overrides_even_if_not_bound_to_invoice_analytic(self):
        """If the user selects a plan on the payment, it must generate distribution even when the plan is bound to other analytics."""

        # Simula factura sin plan en la analítica y plan manual ligado a otra analítica
        self.analytic_account_a.write({'distribution_plan_id': False})

        manual_plan = self.env['aicia.distribution.plan'].create({
            'name': 'Manual Override Plan',
            'company_id': self.company.id,
            'receiver_analytic_account_id': self.analytic_account_dest.id,
            'active': True,
            'source_analytic_account_ids': [(6, 0, [self.analytic_account_b.id])],
        })
        self.env['aicia.distribution.plan.line'].create({
            'plan_id': manual_plan.id,
            'name': 'Manual Line 12%',
            'percentage': 12.0,
            'debit_account_id': self.account_dist_debit.id,
            'debit_analytic_side': 'source',
            'credit_account_id': self.account_dist_credit.id,
            'credit_analytic_side': 'receiver',
        })

        invoice = self._create_invoice(amount=1000.0, analytic_account=self.analytic_account_a)
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'amount': invoice.amount_residual,
            'journal_id': self.bank_journal.id,
            'distribution_plan_id': manual_plan.id,
        })
        wizard.action_create_payments()

        reconciles = invoice.line_ids.mapped('matched_debit_ids') | invoice.line_ids.mapped('matched_credit_ids')
        dist_moves = self.env['account.move'].search([
            ('is_cash_distribution_move', '=', True),
            ('distribution_partial_reconcile_id', 'in', reconciles.ids),
        ])

        self.assertTrue(dist_moves, "El plan seleccionado en el pago debe generar el apunte de distribución.")
        self.assertIn(
            manual_plan,
            dist_moves.mapped('distribution_applied_plan_ids'),
            "El apunte de distribución debe reflejar el plan manual seleccionado en el pago, aunque no coincida con la analítica de la factura.",
        )

