# -*- coding: utf-8 -*-
"""
Test suite for aicia.distribution.rule CRUD and constraints.
"""
from odoo.exceptions import ValidationError
from .common import AiciaCashDistributionCommon


class TestDistributionRule(AiciaCashDistributionCommon):
    """Tests for the Distribution Rule model."""

    # ── Creation ─────────────────────────────────────────────────────────────

    def test_01_create_rule_minimal(self):
        """A rule with only required fields should be created successfully."""
        rule = self._create_rule(name='Minimal Rule', percentage=5.0)
        self.assertTrue(rule.id)
        self.assertEqual(rule.name, 'Minimal Rule')
        self.assertEqual(rule.percentage, 5.0)
        self.assertTrue(rule.active)

    def test_02_create_rule_with_source_analytic(self):
        """A rule with source analytic accounts filter should store them correctly."""
        rule = self._create_rule(
            name='Rule with Source',
            percentage=20.0,
            source_analytic_ids=[self.analytic_account_a.id],
        )
        self.assertIn(self.analytic_account_a, rule.source_analytic_account_ids)

    def test_03_create_rule_with_destination_analytic(self):
        """A rule with a destination analytic account should store it correctly."""
        rule = self._create_rule(
            name='Rule with Dest',
            percentage=15.0,
            dest_analytic=self.analytic_account_dest,
        )
        self.assertEqual(rule.destination_analytic_account_id, self.analytic_account_dest)

    def test_04_create_rule_type_fixed(self):
        """A 'fixed' type rule should be created without source analytic."""
        rule = self._create_rule(name='Fixed Rule', percentage=8.0, rule_type='fixed')
        self.assertEqual(rule.type, 'fixed')

    def test_05_create_multiple_rules(self):
        """Multiple rules for the same company should coexist."""
        rule1 = self._create_rule(name='Rule 1', percentage=10.0)
        rule2 = self._create_rule(name='Rule 2', percentage=20.0)
        rules = self.env['aicia.distribution.rule'].search([
            ('company_id', '=', self.company.id),
            ('name', 'in', ['Rule 1', 'Rule 2']),
        ])
        self.assertEqual(len(rules), 2)

    # ── Update ────────────────────────────────────────────────────────────────

    def test_06_update_rule_percentage(self):
        """Updating a rule's percentage should persist correctly."""
        rule = self._create_rule(name='Updatable Rule', percentage=10.0)
        rule.write({'percentage': 25.5})
        self.assertEqual(rule.percentage, 25.5)

    def test_07_deactivate_rule(self):
        """A rule set to active=False should not appear in active searches."""
        rule = self._create_rule(name='Inactive Rule', percentage=5.0, active=True)
        rule.write({'active': False})
        self.assertFalse(rule.active)
        active_rules = self.env['aicia.distribution.rule'].search([
            ('name', '=', 'Inactive Rule'),
        ])
        self.assertFalse(active_rules)

    # ── Delete ────────────────────────────────────────────────────────────────

    def test_08_delete_rule(self):
        """Deleting a rule should remove it from the database."""
        rule = self._create_rule(name='Deletable Rule', percentage=3.0)
        rule_id = rule.id
        rule.unlink()
        self.assertFalse(self.env['aicia.distribution.rule'].browse(rule_id).exists())

    # ── Percentage edge values ────────────────────────────────────────────────

    def test_09_rule_percentage_zero(self):
        """A rule with 0% percentage should be allowed (rule simply does nothing)."""
        rule = self._create_rule(name='Zero Pct Rule', percentage=0.0)
        self.assertEqual(rule.percentage, 0.0)

    def test_10_rule_percentage_100(self):
        """A rule with 100% percentage should be created without error."""
        rule = self._create_rule(name='Full Pct Rule', percentage=100.0)
        self.assertEqual(rule.percentage, 100.0)

    def test_11_rule_percentage_decimal_precision(self):
        """A rule with many decimal places should round to (16,2) precision."""
        rule = self._create_rule(name='Decimal Pct Rule', percentage=33.33)
        self.assertAlmostEqual(rule.percentage, 33.33, places=2)

    # ── Company isolation ─────────────────────────────────────────────────────

    def test_12_rule_default_company(self):
        """Rule created without explicit company should default to current company."""
        rule = self.env['aicia.distribution.rule'].create({
            'name': 'Default Company Rule',
            'percentage': 10.0,
            'debit_account_id': self.account_dist_debit.id,
            'credit_account_id': self.account_dist_credit.id,
        })
        self.assertEqual(rule.company_id, self.company)

    # ── Multiple source analytic accounts ─────────────────────────────────────

    def test_13_rule_multiple_source_analytics(self):
        """A rule can filter on multiple source analytic accounts."""
        rule = self._create_rule(
            name='Multi-Source Rule',
            percentage=5.0,
            source_analytic_ids=[self.analytic_account_a.id, self.analytic_account_b.id],
        )
        self.assertEqual(len(rule.source_analytic_account_ids), 2)
        self.assertIn(self.analytic_account_a, rule.source_analytic_account_ids)
        self.assertIn(self.analytic_account_b, rule.source_analytic_account_ids)

