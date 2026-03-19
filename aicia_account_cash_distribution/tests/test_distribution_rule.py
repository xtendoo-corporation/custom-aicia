# -*- coding: utf-8 -*-
"""
Test suite for aicia.distribution.plan CRUD and constraints.
"""
from odoo.exceptions import ValidationError
from .common import AiciaCashDistributionCommon


class TestDistributionRule(AiciaCashDistributionCommon):
    """Tests for the Distribution Plan model."""

    # ── Creation ─────────────────────────────────────────────────────────────

    def test_01_create_rule_minimal(self):
        """A plan with only required fields should be created successfully."""
        plan = self._create_rule(name='Minimal Plan', percentage=5.0)
        self.assertTrue(plan.id)
        self.assertEqual(plan.name, 'Minimal Plan')
        self.assertTrue(plan.active)
        self.assertEqual(len(plan.line_ids), 1)
        self.assertEqual(plan.line_ids[0].percentage, 5.0)

    def test_02_create_rule_with_source_analytic(self):
        """A plan with source analytic accounts filter should store them correctly."""
        plan = self._create_rule(
            name='Plan with Source',
            percentage=20.0,
            source_analytic_ids=[self.analytic_account_a.id],
        )
        self.assertIn(self.analytic_account_a, plan.source_analytic_account_ids)

    def test_03_create_rule_with_destination_analytic(self):
        """A plan with a receiver analytic account should store it correctly."""
        plan = self._create_rule(
            name='Plan with Receiver',
            percentage=15.0,
            dest_analytic=self.analytic_account_dest,
        )
        self.assertEqual(plan.receiver_analytic_account_id, self.analytic_account_dest)

    def test_04_plan_without_analytics_never_fires(self):
        """A plan with no analytics assigned never fires (no catch-all behavior)."""
        plan = self._create_rule(name='Unassigned Plan', percentage=8.0)
        # source_analytic_account_ids es One2many, vacío significa que ninguna
        # analítica tiene este plan asignado
        self.assertFalse(plan.source_analytic_account_ids)

    def test_05_create_multiple_rules(self):
        """Multiple plans for the same company should coexist."""
        plan1 = self._create_rule(name='Plan 1', percentage=10.0)
        plan2 = self._create_rule(name='Plan 2', percentage=20.0)
        plans = self.env['aicia.distribution.plan'].search([
            ('company_id', '=', self.company.id),
            ('name', 'in', ['Plan 1', 'Plan 2']),
        ])
        self.assertEqual(len(plans), 2)

    # ── Update ────────────────────────────────────────────────────────────────

    def test_06_update_rule_percentage(self):
        """Updating a plan line's percentage should persist correctly."""
        plan = self._create_rule(name='Updatable Plan', percentage=10.0)
        plan.line_ids[0].write({'percentage': 25.5})
        self.assertEqual(plan.line_ids[0].percentage, 25.5)

    def test_07_deactivate_rule(self):
        """A plan set to active=False should not appear in active searches."""
        plan = self._create_rule(name='Inactive Plan', percentage=5.0, active=True)
        plan.write({'active': False})
        self.assertFalse(plan.active)
        active_plans = self.env['aicia.distribution.plan'].search([
            ('name', '=', 'Inactive Plan'),
        ])
        self.assertFalse(active_plans)

    # ── Delete ────────────────────────────────────────────────────────────────

    def test_08_delete_rule(self):
        """Deleting a plan should remove it from the database."""
        plan = self._create_rule(name='Deletable Plan', percentage=3.0)
        plan_id = plan.id
        plan.unlink()
        self.assertFalse(self.env['aicia.distribution.plan'].browse(plan_id).exists())

    # ── Percentage edge values ────────────────────────────────────────────────

    def test_09_rule_percentage_zero(self):
        """A plan line with 0% percentage should be allowed (line simply does nothing)."""
        plan = self._create_rule(name='Zero Pct Plan', percentage=0.0)
        self.assertEqual(plan.line_ids[0].percentage, 0.0)

    def test_10_rule_percentage_100(self):
        """A plan line with 100% percentage should be created without error."""
        plan = self._create_rule(name='Full Pct Plan', percentage=100.0)
        self.assertEqual(plan.line_ids[0].percentage, 100.0)

    def test_11_rule_percentage_decimal_precision(self):
        """A plan line with many decimal places should work correctly."""
        plan = self._create_rule(name='Decimal Pct Plan', percentage=33.3333)
        self.assertAlmostEqual(plan.line_ids[0].percentage, 33.3333, places=4)

    # ── Company isolation ─────────────────────────────────────────────────────

    def test_12_rule_default_company(self):
        """Plan created without explicit company should default to current company."""
        plan = self.env['aicia.distribution.plan'].create({
            'name': 'Default Company Plan',
        })
        self.assertEqual(plan.company_id, self.company)

    # ── Multiple source analytic accounts ─────────────────────────────────────

    def test_13_rule_multiple_source_analytics(self):
        """A plan can filter on multiple source analytic accounts."""
        plan = self._create_rule(
            name='Multi-Source Plan',
            percentage=5.0,
            source_analytic_ids=[self.analytic_account_a.id, self.analytic_account_b.id],
        )
        self.assertEqual(len(plan.source_analytic_account_ids), 2)
        self.assertIn(self.analytic_account_a, plan.source_analytic_account_ids)
        self.assertIn(self.analytic_account_b, plan.source_analytic_account_ids)

