# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""La analítica de la cabecera solo se copia a las líneas de producto.

Si se copiara también a la línea de cuenta a pagar/cobrar y a la de impuestos, sus apuntes
analíticos (de importe contrario al del gasto/ingreso) anularían el coste o ingreso del proyecto.
"""
from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestAnalyticPropagation(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = cls.env['account.analytic.plan'].create({'name': 'Plan Propagación'})
        cls.plan2 = cls.env['account.analytic.plan'].create({'name': 'Plan Propagación 2'})
        cls.project = cls.env['account.analytic.account'].create({'name': 'Proyecto A', 'plan_id': cls.plan.id})
        cls.other = cls.env['account.analytic.account'].create({'name': 'Proyecto B', 'plan_id': cls.plan2.id})

    def _invoice(self, move_type='in_invoice', header=True, price=100.0):
        vals = {
            'move_type': move_type,
            'partner_id': self.partner_a.id,
            'invoice_date': '2026-11-02',
            'invoice_line_ids': [Command.create({
                'name': 'Servicio', 'quantity': 1, 'price_unit': price,
                'tax_ids': [Command.set((self.tax_purchase_a if move_type == 'in_invoice' else self.tax_sale_a).ids)],
            })],
        }
        if header:
            vals['analytic_distribution'] = {str(self.project.id): 100.0}
        return self.env['account.move'].create(vals)

    def _by_type(self, move, display_type):
        return move.line_ids.filtered(lambda line: line.display_type == display_type)

    def test_only_product_lines_get_the_header_analytic(self):
        for move_type in ('in_invoice', 'out_invoice'):
            move = self._invoice(move_type)
            self.assertEqual(self._by_type(move, 'product').analytic_distribution, {str(self.project.id): 100.0})
            self.assertFalse(self._by_type(move, 'payment_term').analytic_distribution, move_type)
            self.assertFalse(self._by_type(move, 'tax').analytic_distribution, move_type)

    def test_posted_invoice_analytic_lines_only_for_the_expense(self):
        move = self._invoice('in_invoice', price=100.0)
        move.action_post()
        analytic_lines = move.line_ids.analytic_line_ids
        self.assertEqual(len(analytic_lines), 1)
        self.assertEqual(analytic_lines[self.plan._column_name()], self.project)
        self.assertAlmostEqual(analytic_lines.amount, -100.0)

    def test_posted_customer_invoice_keeps_the_income(self):
        move = self._invoice('out_invoice', price=100.0)
        move.action_post()
        self.assertAlmostEqual(sum(move.line_ids.analytic_line_ids.mapped('amount')), 100.0)

    def test_line_added_later_gets_the_analytic(self):
        move = self._invoice('in_invoice')
        move.write({'invoice_line_ids': [Command.create({'name': 'Otro', 'quantity': 1, 'price_unit': 10.0})]})
        products = self._by_type(move, 'product')
        self.assertEqual(len(products), 2)
        self.assertEqual(set(map(str, products.mapped('analytic_distribution'))), {str({str(self.project.id): 100.0})})
        self.assertFalse(self._by_type(move, 'payment_term').analytic_distribution)

    def test_changing_header_updates_only_product_lines(self):
        move = self._invoice('in_invoice', header=False)
        move.write({'analytic_distribution': {str(self.project.id): 100.0}})
        self.assertEqual(self._by_type(move, 'product').analytic_distribution, {str(self.project.id): 100.0})
        self.assertFalse(self._by_type(move, 'payment_term').analytic_distribution)
        self.assertFalse(self._by_type(move, 'tax').analytic_distribution)

    def test_journal_item_count_counts_each_line_once(self):
        move = self._invoice('in_invoice')
        self.project.invalidate_recordset()
        self.assertEqual(self.project.journal_item_count, 1)

    def test_journal_item_count_with_combined_keys_and_several_accounts(self):
        move = self._invoice('in_invoice', header=False)
        product = self._by_type(move, 'product')
        product.analytic_distribution = {f'{self.project.id},{self.other.id}': 100.0}
        accounts = self.project | self.other
        accounts.invalidate_recordset()
        self.assertEqual(self.project.journal_item_count, 1)
        self.assertEqual(self.other.journal_item_count, 1)
        # En un único cálculo para varias cuentas.
        self.assertEqual(accounts.mapped('journal_item_count'), [1, 1])

    def test_action_view_journal_items_domain(self):
        move = self._invoice('in_invoice')
        action = self.project.action_view_journal_items()
        self.assertEqual(action['domain'], [('id', 'in', self._by_type(move, 'product').ids)])
