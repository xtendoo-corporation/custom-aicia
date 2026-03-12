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
        cls.secondary_analytic_account = cls.env["account.analytic.account"].create({
            "name": "Secondary Analytic Account",
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

        self.assertEqual(
            payment_register.split_template_id,
            self.template,
            "The wizard should suggest the template from invoice analytic_distribution.",
        )

        payment_vals = payment_register._create_payment_vals_from_wizard(payment_register.batches[0])
        self.assertEqual(
            payment_vals.get("split_template_id"),
            self.template.id,
            "The wizard must propagate the suggested template to the created payment.",
        )

        payment_vals["invoice_ids"] = [(6, 0, invoice.ids)]
        payment = self.env["account.payment"].create(payment_vals)

        self.assertEqual(
            payment.split_template_id.id,
            self.template.id,
            "The template should have been suggested from the analytic account."
        )

    def test_suggest_template_from_composite_analytic_distribution(self):
        """The wizard should resolve templates even when analytic_distribution uses composite keys."""
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "journal_id": self.env["account.journal"].search([("type", "=", "sale")], limit=1).id,
            "analytic_distribution": {
                "%s,%s" % (self.analytic_account.id, self.secondary_analytic_account.id): 100.0
            },
            "invoice_line_ids": [
                (0, 0, {
                    "name": "Composite Test Line",
                    "quantity": 1,
                    "price_unit": 100.0,
                })
            ],
        })
        invoice.action_post()

        payment_register = self.env["account.payment.register"].with_context(
            active_model="account.move",
            active_ids=invoice.ids,
        ).create({
            "journal_id": self.bank_journal.id,
        })

        self.assertEqual(
            payment_register.split_template_id,
            self.template,
            "Composite analytic_distribution keys should still resolve the related template.",
        )

    def test_posted_payment_inherits_invoice_analytic_distribution(self):
        """Posted payments and split moves should inherit the invoice analytic distribution."""
        invoice_distribution = {str(self.analytic_account.id): 100.0}
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "journal_id": self.env["account.journal"].search([("type", "=", "sale")], limit=1).id,
            "analytic_distribution": invoice_distribution,
            "invoice_line_ids": [
                (0, 0, {
                    "name": "Posted Payment Test Line",
                    "quantity": 1,
                    "price_unit": 100.0,
                })
            ],
        })
        invoice.action_post()

        payment_register = self.env["account.payment.register"].with_context(
            active_model="account.move",
            active_ids=invoice.ids,
        ).create({
            "journal_id": self.bank_journal.id,
        })
        payment_vals = payment_register._create_payment_vals_from_wizard(
            payment_register.batches[0]
        )
        payment_vals["invoice_ids"] = [(6, 0, invoice.ids)]

        payment = self.env["account.payment"].create(payment_vals)
        payment.action_post()

        self.assertEqual(
            payment.move_id.analytic_distribution,
            invoice_distribution,
            "The payment journal entry should inherit the invoice analytic distribution.",
        )
        self.assertTrue(payment.split_move_id, "A split move should be created after posting the payment.")
        self.assertEqual(
            payment.split_move_id.analytic_distribution,
            invoice_distribution,
            "The split move should inherit the invoice analytic distribution as fallback.",
        )

        payment_move_lines = payment.move_id.line_ids.filtered(
            lambda line: line.display_type not in ("line_section", "line_note")
        )
        self.assertTrue(payment_move_lines, "The payment journal entry should contain accounting lines.")
        self.assertTrue(
            all(line.analytic_distribution == invoice_distribution for line in payment_move_lines),
            "All payment lines should inherit the invoice analytic distribution.",
        )

        split_move_lines = payment.split_move_id.line_ids.filtered(
            lambda line: line.display_type not in ("line_section", "line_note")
        )
        self.assertTrue(split_move_lines, "The split move should contain accounting lines.")
        self.assertTrue(
            all(line.analytic_distribution == invoice_distribution for line in split_move_lines),
            "Split move lines without explicit analytic data should inherit the invoice distribution.",
        )

    def test_wizard_action_create_payments_syncs_invoice_analytic_distribution(self):
        """The real register payment wizard flow should sync the invoice analytic distribution."""
        invoice_distribution = {str(self.analytic_account.id): 100.0}
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "journal_id": self.env["account.journal"].search([("type", "=", "sale")], limit=1).id,
            "analytic_distribution": invoice_distribution,
            "invoice_line_ids": [
                (0, 0, {
                    "name": "Wizard Payment Test Line",
                    "quantity": 1,
                    "price_unit": 181.5,
                })
            ],
        })
        invoice.action_post()

        receivable_lines = invoice.line_ids.filtered(
            lambda line: line.account_type == "asset_receivable" and not line.reconciled
        )
        payment_register = self.env["account.payment.register"].with_context(
            active_model="account.move",
            active_ids=invoice.ids,
        ).create({
            "line_ids": [(6, 0, receivable_lines.ids)],
            "journal_id": self.bank_journal.id,
        })

        action = payment_register.action_create_payments()
        payment = self.env["account.payment"].browse(action.get("res_id"))

        self.assertTrue(payment, "The wizard should create a payment record.")
        self.assertEqual(
            payment.reconciled_invoice_ids,
            invoice,
            "The payment should be reconciled with the invoice after the wizard flow.",
        )
        self.assertEqual(
            payment.move_id.analytic_distribution,
            invoice_distribution,
            "The payment journal entry should inherit the invoice analytic distribution after reconciliation.",
        )
        self.assertEqual(
            payment.split_move_id.analytic_distribution,
            invoice_distribution,
            "The split move should inherit the invoice analytic distribution in the real wizard flow.",
        )

