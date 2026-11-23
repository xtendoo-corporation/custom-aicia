# -*- coding: utf-8 -*-
"""Acceso a cuentas analíticas según el grupo del usuario.

``rule_analytic_account_responsible`` limita a los usuarios internos a las
cuentas de las que son responsables. Los administradores (``base.group_system``)
deben tener acceso total sin ser el superusuario técnico, mientras que los
usuarios internos y portal siguen limitados a sus propias cuentas.
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAnalyticAccountAdminAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        plan = cls.env['account.analytic.plan'].create({'name': 'Plan Acceso Admin'})
        cls.admin = cls.env['res.users'].create({
            'name': 'Administrador Analítica',
            'login': 'analytic_admin_access_test',
            'email': 'analytic_admin_access_test@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_system').id])],
        })
        cls.internal = cls.env['res.users'].create({
            'name': 'Interno Analítica',
            'login': 'analytic_internal_access_test',
            'email': 'analytic_internal_access_test@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.portal = cls.env['res.users'].create({
            'name': 'Portal Analítica',
            'login': 'analytic_portal_access_test',
            'email': 'analytic_portal_access_test@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })
        cls.foreign_account = cls.env['account.analytic.account'].create({
            'name': 'Cuenta Ajena',
            'plan_id': plan.id,
        })
        cls.internal_account = cls.env['account.analytic.account'].create({
            'name': 'Cuenta del Interno',
            'plan_id': plan.id,
            'responsible_id': cls.internal.id,
        })
        cls.portal_account = cls.env['account.analytic.account'].create({
            'name': 'Cuenta del Portal',
            'plan_id': plan.id,
            'responsible_id': cls.portal.id,
        })

    def test_admin_rule_targets_system_group_with_full_access(self):
        rule = self.env.ref('portal_requests.rule_analytic_account_admin_full_access')
        self.assertEqual(rule.groups, self.env.ref('base.group_system'))
        self.assertEqual(rule.domain_force, "[(1, '=', 1)]")
        self.assertTrue(all((rule.perm_read, rule.perm_write, rule.perm_create, rule.perm_unlink)))

    def test_admin_reads_and_writes_account_without_being_responsible(self):
        account = self.foreign_account.with_user(self.admin)
        self.assertFalse(self.admin._is_superuser())
        self.assertEqual(account.name, 'Cuenta Ajena')
        account.write({'name': 'Cuenta Ajena Editada'})
        self.assertEqual(self.foreign_account.name, 'Cuenta Ajena Editada')
        accounts = self.env['account.analytic.account'].with_user(self.admin).search(
            [('id', 'in', (self.foreign_account | self.internal_account | self.portal_account).ids)]
        )
        self.assertEqual(len(accounts), 3)

    def test_internal_user_limited_to_own_accounts(self):
        accounts = self.env['account.analytic.account'].with_user(self.internal).search(
            [('id', 'in', (self.foreign_account | self.internal_account).ids)]
        )
        self.assertEqual(accounts, self.internal_account)
        with self.assertRaises(AccessError):
            self.foreign_account.with_user(self.internal).read(['name'])

    def test_portal_user_limited_to_own_accounts(self):
        accounts = self.env['account.analytic.account'].with_user(self.portal).search(
            [('id', 'in', (self.foreign_account | self.portal_account).ids)]
        )
        self.assertNotIn(self.foreign_account, accounts)
        with self.assertRaises(AccessError):
            self.foreign_account.with_user(self.portal).read(['name'])
