# -*- coding: utf-8 -*-
"""
Common base class for all AICIA Cash Distribution tests.
Provides shared setup: company, journal, analytic accounts,
accounts and a helper to create invoices + rules.
"""
from odoo.tests.common import TransactionCase


class AiciaCashDistributionCommon(TransactionCase):
    """Shared fixtures for all cash-distribution tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

        # ── Company ──────────────────────────────────────────────────────────
        cls.company = cls.env.company

        # ── Journals ─────────────────────────────────────────────────────────
        cls.bank_journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1
        )
        if not cls.bank_journal:
            cls.bank_journal = cls.env['account.journal'].create({
                'name': 'Test Bank', 'code': 'TBNK', 'type': 'bank',
                'company_id': cls.company.id,
            })

        cls.misc_journal = cls.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', cls.company.id)], limit=1
        )
        if not cls.misc_journal:
            cls.misc_journal = cls.env['account.journal'].create({
                'name': 'Test Misc', 'code': 'TMISC', 'type': 'general',
                'company_id': cls.company.id,
            })

        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', cls.company.id)], limit=1
        )

        # ── Accounts — reuse existing to avoid NOT NULL issues from installed modules ──
        cls.account_revenue = cls.env['account.account'].search(
            [('account_type', '=', 'income'),
             ('company_ids', 'in', cls.company.id)],
            limit=1
        )
        cls.account_dist_debit = cls.env['account.account'].search(
            [('account_type', 'in', ('expense', 'expense_direct_cost')),
             ('company_ids', 'in', cls.company.id)],
            limit=1
        )
        cls.account_dist_credit = cls.env['account.account'].search(
            [('account_type', '=', 'income'),
             ('company_ids', 'in', cls.company.id),
             ('id', '!=', cls.account_revenue.id)],
            limit=1
        )
        if not cls.account_dist_credit:
            cls.account_dist_credit = cls.account_revenue

        cls.account_dist_debit2 = cls.env['account.account'].search(
            [('account_type', 'in', ('expense', 'expense_direct_cost')),
             ('company_ids', 'in', cls.company.id),
             ('id', '!=', cls.account_dist_debit.id)],
            limit=1
        )
        if not cls.account_dist_debit2:
            cls.account_dist_debit2 = cls.account_dist_debit

        cls.account_dist_credit2 = cls.env['account.account'].search(
            [('account_type', '=', 'income'),
             ('company_ids', 'in', cls.company.id),
             ('id', 'not in', [cls.account_revenue.id, cls.account_dist_credit.id])],
            limit=1
        )
        if not cls.account_dist_credit2:
            cls.account_dist_credit2 = cls.account_dist_credit

        # Sanity check
        assert cls.account_revenue, "No income account found in company"
        assert cls.account_dist_debit, "No expense account found in company"

        # ── Partner — reuse existing to avoid NOT NULL constraints of custom modules ──
        cls.partner = cls.env['res.partner'].search(
            [('customer_rank', '>', 0), ('company_id', 'in', [False, cls.company.id])],
            limit=1
        )
        if not cls.partner:
            cls.partner = cls.env['res.partner'].search(
                [('is_company', '=', True), ('company_id', 'in', [False, cls.company.id])],
                limit=1
            )
        if not cls.partner:
            cls.partner = cls.env['res.partner'].search(
                [('company_id', 'in', [False, cls.company.id])], limit=1
            )
        assert cls.partner, "No partner found in database"

        # ── Analytic Accounts ─────────────────────────────────────────────────
        analytic_plan = cls.env['account.analytic.plan'].search([], limit=1)
        if not analytic_plan:
            analytic_plan = cls.env['account.analytic.plan'].create({
                'name': 'Test Plan',
            })

        cls.analytic_account_a = cls.env['account.analytic.account'].create({
            'name': 'Analytic A', 'plan_id': analytic_plan.id,
        })
        cls.analytic_account_b = cls.env['account.analytic.account'].create({
            'name': 'Analytic B', 'plan_id': analytic_plan.id,
        })
        cls.analytic_account_dest = cls.env['account.analytic.account'].create({
            'name': 'Analytic Dest', 'plan_id': analytic_plan.id,
        })

        # ── Enable distribution for the company ──────────────────────────────
        cls.company.write({
            'cash_distribution_active': True,
            'cash_distribution_journal_id': cls.misc_journal.id,
            'cash_distribution_receiver_analytic_id': cls.analytic_account_dest.id,
        })

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _create_rule(self, name='Plan A', percentage=10.0,
                     source_analytic_ids=None, dest_analytic=None,
                     debit_account=None, credit_account=None,
                     rule_type='source', active=True, is_vat_line=False):
        """
        Create a distribution plan with one line.
        For compatibility with old tests, this creates a plan with a single line.
        """
        plan = self.env['aicia.distribution.plan'].create({
            'name': name,
            'company_id': self.company.id,
            'source_analytic_account_ids': [(6, 0, source_analytic_ids or [])],
            'receiver_analytic_account_id': (dest_analytic or self.analytic_account_dest).id,
            'active': active,
        })

        # Create a single line for the plan
        debit_analytic_side = 'receiver' if rule_type == 'dest' else 'source'
        credit_analytic_side = 'source' if rule_type == 'dest' else 'receiver'

        self.env['aicia.distribution.plan.line'].create({
            'plan_id': plan.id,
            'name': f'{name} Line',
            'is_vat_line': is_vat_line,
            'percentage': percentage,
            'debit_account_id': (debit_account or self.account_dist_debit).id,
            'debit_analytic_side': debit_analytic_side,
            'credit_account_id': (credit_account or self.account_dist_credit).id,
            'credit_analytic_side': credit_analytic_side,
        })

        return plan

    def _create_invoice(self, amount=1000.0, analytic_account=None,
                        analytic_on_header=False, move_type='out_invoice'):
        """Create and post a customer invoice."""
        line_vals = {
            'name': 'Test Service',
            'quantity': 1,
            'price_unit': amount,
            'account_id': self.account_revenue.id,
        }
        if analytic_account and not analytic_on_header:
            line_vals['analytic_distribution'] = {str(analytic_account.id): 100}

        invoice_vals = {
            'move_type': move_type,
            'partner_id': self.partner.id,
            'journal_id': self.sale_journal.id,
            'invoice_line_ids': [(0, 0, line_vals)],
        }
        if analytic_account and analytic_on_header:
            invoice_vals['analytic_distribution'] = {str(analytic_account.id): 100}

        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        return invoice

    def _register_payment(self, invoice, amount=None):
        """Register a payment for an invoice and return the reconcile records."""
        pay_amount = amount if amount is not None else invoice.amount_residual
        payment_register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'amount': pay_amount,
            'journal_id': self.bank_journal.id,
        })
        payment_register.action_create_payments()
        return invoice.line_ids.mapped('matched_debit_ids') | invoice.line_ids.mapped('matched_credit_ids')
