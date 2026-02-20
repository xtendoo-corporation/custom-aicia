# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestPaymentSplit(TransactionCase):
    """Tests para el módulo aicia_account_payment_split."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
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
        cls.credit_account_1 = cls.env["account.account"].search(
            [
                ("company_ids", "in", cls.company.id),
                ("account_type", "=", "income"),
            ],
            limit=1,
        )
        cls.credit_account_2 = cls.env["account.account"].search(
            [
                ("company_ids", "in", cls.company.id),
                ("account_type", "=", "income"),
                ("id", "!=", cls.credit_account_1.id),
            ],
            limit=1,
        )
        if not cls.credit_account_2:
            cls.credit_account_2 = cls.credit_account_1

        # Partner
        cls.partner = cls.env["res.partner"].create({"name": "Test Partner Split"})

    def _create_template(self, mode="lines_sum_to_100", base_pct=10.0, lines=None):
        """Helper para crear una plantilla de reparto."""
        if lines is None:
            lines = [
                {
                    "name": "Línea A",
                    "credit_account_id": self.credit_account_1.id,
                    "percentage": 60.0,
                },
                {
                    "name": "Línea B",
                    "credit_account_id": self.credit_account_2.id,
                    "percentage": 40.0,
                },
            ]
        return self.env["account.payment.split.template"].create(
            {
                "name": "Plantilla Test",
                "company_id": self.company.id,
                "journal_id": self.misc_journal.id,
                "debit_account_id": self.debit_account.id,
                "split_base_mode": mode,
                "split_base_percentage": base_pct,
                "split_line_ids": [(0, 0, l) for l in lines],
            }
        )

    # ------------------------------------------------------------------
    # Tests de validaciones de plantilla
    # ------------------------------------------------------------------
    def test_template_percentage_out_of_range(self):
        """split_base_percentage fuera de 0-100 lanza error."""
        with self.assertRaises(ValidationError):
            self._create_template(base_pct=150.0)

    def test_template_lines_sum_to_100_wrong(self):
        """En modo lines_sum_to_100, líneas que no suman 100 lanzan error."""
        lines = [
            {
                "name": "A",
                "credit_account_id": self.credit_account_1.id,
                "percentage": 50.0,
            },
            {
                "name": "B",
                "credit_account_id": self.credit_account_2.id,
                "percentage": 30.0,
            },
        ]
        with self.assertRaises(ValidationError):
            self._create_template(mode="lines_sum_to_100", lines=lines)

    def test_template_lines_sum_to_base_wrong(self):
        """En modo lines_sum_to_base, líneas que no suman base lanzan error."""
        lines = [
            {
                "name": "A",
                "credit_account_id": self.credit_account_1.id,
                "percentage": 4.0,
            },
            {
                "name": "B",
                "credit_account_id": self.credit_account_2.id,
                "percentage": 3.0,
            },
        ]
        with self.assertRaises(ValidationError):
            self._create_template(mode="lines_sum_to_base", base_pct=10.0, lines=lines)

    def test_template_lines_sum_to_base_ok(self):
        """En modo lines_sum_to_base, líneas que suman base OK."""
        lines = [
            {
                "name": "A",
                "credit_account_id": self.credit_account_1.id,
                "percentage": 4.0,
            },
            {
                "name": "B",
                "credit_account_id": self.credit_account_2.id,
                "percentage": 3.0,
            },
            {
                "name": "C",
                "credit_account_id": self.credit_account_1.id,
                "percentage": 3.0,
            },
        ]
        tpl = self._create_template(
            mode="lines_sum_to_base", base_pct=10.0, lines=lines
        )
        self.assertTrue(tpl.id)

    def test_template_negative_line_percentage(self):
        """Porcentaje negativo en línea lanza error."""
        lines = [
            {
                "name": "A",
                "credit_account_id": self.credit_account_1.id,
                "percentage": -10.0,
            },
            {
                "name": "B",
                "credit_account_id": self.credit_account_2.id,
                "percentage": 110.0,
            },
        ]
        with self.assertRaises(ValidationError):
            self._create_template(lines=lines)

    def test_template_valid(self):
        """Plantilla válida se crea sin errores."""
        tpl = self._create_template()
        self.assertTrue(tpl.active)
        self.assertEqual(len(tpl.split_line_ids), 2)
        self.assertEqual(tpl.split_base_percentage, 10.0)
