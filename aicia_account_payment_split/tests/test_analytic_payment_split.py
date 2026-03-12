# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


class TestAnalyticPaymentSplit(TransactionCase):
    """Tests for the relation between analytic accounts and payment split templates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id

        # Diarios
        cls.bank_journal = cls.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", cls.company.id)],
            limit=1,
        )
        cls.misc_journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)],
            limit=1,
        )

        # Cuentas contables
        cls.debit_account = cls.env["account.account"].search(
            [
                ("company_ids", "in", cls.company.id),
                ("account_type", "=", "asset_current"),
            ],
            limit=1,
        )
        cls.credit_account = cls.env["account.account"].search(
            [
                ("company_ids", "in", cls.company.id),
                ("account_type", "=", "income"),
            ],
            limit=1,
        )

        # Partner
        cls.partner = cls.env["res.partner"].create({"name": "Test Partner Analytic Split"})

        # Analytic Plan (Required in Odoo 19)
        cls.analytic_plan = cls.env["account.analytic.plan"].search([], limit=1)
        if not cls.analytic_plan:
            cls.analytic_plan = cls.env["account.analytic.plan"].create({
                "name": "Default Plan",
            })

        # Analytic Account
        cls.analytic_account = cls.env["account.analytic.account"].create({
            "name": "Test Analytic Account",
            "company_id": cls.company.id,
            "plan_id": cls.analytic_plan.id,
        })

        # Template
        cls.template = cls.env["account.payment.split.template"].create({
            "name": "Analytic Template",
            "company_id": cls.company.id,
            "journal_id": cls.misc_journal.id,
            "debit_account_id": cls.debit_account.id,
            "split_base_mode": "lines_sum_to_100",
            "split_base_percentage": 10.0,
            "split_line_ids": [
                (0, 0, {
                    "name": "Line 1",
                    "credit_account_id": cls.credit_account.id,
                    "percentage": 100.0,
                })
            ],
        })

        # Assign template to analytic account
        cls.analytic_account.payment_split_template_id = cls.template.id

    def test_suggest_template_from_analytic_account(self):
        """Verify that the template is suggested from the analytic account of the invoice."""
        # Create an invoice with the analytic account
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "journal_id": self.env["account.journal"].search([("type", "=", "sale")], limit=1).id,
            "analytic_distribution": {str(self.analytic_account.id): 100.0},
            "invoice_line_ids": [
                (0, 0, {
                    "name": "Test Line",
                    "quantity": 1,
                    "price_unit": 100.0,
                })
            ],
        })
        invoice.action_post()

        # Create a payment (wizard style simulation or direct)
        payment_register = self.env["account.payment.register"].with_context(
            active_model="account.move",
            active_ids=invoice.ids,
        ).create({
            "journal_id": self.bank_journal.id,
        })
        
        # In Odoo, the onchange is triggered manually in tests or by the framework
        # We check the payment template suggestion logic
        payment_vals = payment_register._create_payment_vals_from_wizard(payment_register.batches[0])
        payment_vals["invoice_ids"] = [(6, 0, invoice.ids)]
        payment = self.env["account.payment"].create(payment_vals)
        
        # Trigger the suggestion
        payment._onchange_suggest_split_template()
        
        self.assertEqual(
            payment.split_template_id.id, 
            self.template.id, 
            "The template should have been suggested from the analytic account."
        )
