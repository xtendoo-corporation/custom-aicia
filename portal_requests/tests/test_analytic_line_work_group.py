# -*- coding: utf-8 -*-
"""Grupo de Trabajo en los apuntes analíticos.

``work_group_id`` de ``account.analytic.line`` es un related almacenado de la
cuenta analítica: permite agrupar y filtrar los apuntes por equipo y comprobar
que el saldo de un equipo coincide con la suma de los saldos de sus proyectos.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAnalyticLineWorkGroup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        project_plan, _other_plans = cls.env['account.analytic.plan']._get_all_plans()
        cls.group_a = cls.env['portal.work.group'].create(
            {'name': 'Equipo A', 'code': 'EQA'}
        )
        cls.group_b = cls.env['portal.work.group'].create(
            {'name': 'Equipo B', 'code': 'EQB'}
        )
        cls.account_a1 = cls._create_account('Proyecto A1', project_plan, cls.group_a)
        cls.account_a2 = cls._create_account('Proyecto A2', project_plan, cls.group_a)
        cls.account_b = cls._create_account('Proyecto B', project_plan, cls.group_b)
        cls.account_no_group = cls._create_account('Proyecto sin equipo', project_plan)
        cls.lines_a1 = cls._create_lines(cls.account_a1, [100.0, -40.0])
        cls.lines_a2 = cls._create_lines(cls.account_a2, [25.5])
        cls.lines_b = cls._create_lines(cls.account_b, [-300.0, 10.0])
        cls.lines_no_group = cls._create_lines(cls.account_no_group, [7.0])
        cls.all_lines = (
            cls.lines_a1 | cls.lines_a2 | cls.lines_b | cls.lines_no_group
        )

    @classmethod
    def _create_account(cls, name, plan, work_group=None):
        return cls.env['account.analytic.account'].create({
            'name': name,
            'plan_id': plan.id,
            'work_group_id': work_group.id if work_group else False,
        })

    @classmethod
    def _create_lines(cls, account, amounts):
        return cls.env['account.analytic.line'].create([
            {
                'name': f'Apunte {account.name} {position}',
                'account_id': account.id,
                'amount': amount,
            }
            for position, amount in enumerate(amounts)
        ])

    def _stored_lines_of_group(self, work_group):
        """Busca por el valor almacenado, no por el de la caché."""
        self.env.flush_all()
        self.env.invalidate_all()
        return self.env['account.analytic.line'].search([
            ('id', 'in', self.all_lines.ids),
            ('work_group_id', '=', work_group.id if work_group else False),
        ])

    def test_work_group_is_propagated_to_lines(self):
        self.assertEqual(self.lines_a1.work_group_id, self.group_a)
        self.assertEqual(self.lines_a2.work_group_id, self.group_a)
        self.assertEqual(self.lines_b.work_group_id, self.group_b)
        self.assertFalse(self.lines_no_group.work_group_id)
        self.assertEqual(
            self._stored_lines_of_group(self.group_a),
            self.lines_a1 | self.lines_a2,
        )
        self.assertEqual(self._stored_lines_of_group(None), self.lines_no_group)

    def test_changing_account_work_group_updates_existing_lines(self):
        self.account_a1.work_group_id = self.group_b

        self.assertEqual(self.lines_a1.work_group_id, self.group_b)
        self.assertEqual(self._stored_lines_of_group(self.group_a), self.lines_a2)
        self.assertEqual(
            self._stored_lines_of_group(self.group_b),
            self.lines_a1 | self.lines_b,
        )

    def test_removing_account_work_group_clears_existing_lines(self):
        self.account_b.work_group_id = False

        self.assertFalse(self.lines_b.work_group_id)
        self.assertFalse(self._stored_lines_of_group(self.group_b))
        self.assertEqual(
            self._stored_lines_of_group(None),
            self.lines_b | self.lines_no_group,
        )

    def test_moving_line_to_another_account_updates_work_group(self):
        line = self.lines_a2
        line.account_id = self.account_b

        self.assertEqual(line.work_group_id, self.group_b)
        self.assertIn(line, self._stored_lines_of_group(self.group_b))

    def test_balance_by_work_group_equals_sum_of_its_accounts(self):
        analytic_line = self.env['account.analytic.line']
        domain = [('id', 'in', self.all_lines.ids)]
        balance_by_group = dict(analytic_line._read_group(
            domain, groupby=['work_group_id'], aggregates=['amount:sum'],
        ))
        balance_by_account = dict(analytic_line._read_group(
            domain, groupby=['account_id'], aggregates=['amount:sum'],
        ))

        self.assertAlmostEqual(balance_by_group[self.group_a], 85.5)
        self.assertAlmostEqual(balance_by_group[self.group_b], -290.0)
        no_group = self.env['portal.work.group']
        self.assertAlmostEqual(balance_by_group[no_group], 7.0)
        for work_group, group_balance in balance_by_group.items():
            accounts_balance = sum(
                balance
                for account, balance in balance_by_account.items()
                if account.work_group_id == work_group
            )
            self.assertAlmostEqual(group_balance, accounts_balance)
        self.assertAlmostEqual(
            sum(balance_by_group.values()), sum(self.all_lines.mapped('amount'))
        )
