# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestProjectClosure(TransactionCase):
    """Tests para el módulo aicia_account_project_closure.

    NOTA: Todos los tests filtran por analytic_account_ids para aislarse de
    datos preexistentes en la BD de test (TransactionCase no vacía la BD).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        cls.currency = cls.company.currency_id

        # ------------------------------------------------------------------
        # Diario general
        # ------------------------------------------------------------------
        cls.misc_journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)],
            limit=1,
        )
        if not cls.misc_journal:
            cls.misc_journal = cls.env["account.journal"].create(
                {
                    "name": "Miscelánea Test",
                    "code": "MIST",
                    "type": "general",
                    "company_id": cls.company.id,
                }
            )

        # ------------------------------------------------------------------
        # Cuentas contables
        # ------------------------------------------------------------------
        Account = cls.env["account.account"]

        # Cuenta de ingresos (7xx)
        cls.account_income = Account.search(
            [
                ("code", "=like", "7%"),
                ("company_ids", "in", cls.company.id),
            ],
            limit=1,
        )
        if not cls.account_income:
            cls.account_income = Account.create(
                {
                    "name": "Ingresos Test",
                    "code": "700000",
                    "account_type": "income",
                    "company_ids": [Command.set([cls.company.id])],
                }
            )

        # Cuenta de gastos (6xx)
        cls.account_expense = Account.search(
            [
                ("code", "=like", "6%"),
                ("company_ids", "in", cls.company.id),
            ],
            limit=1,
        )
        if not cls.account_expense:
            cls.account_expense = Account.create(
                {
                    "name": "Gastos Test",
                    "code": "600000",
                    "account_type": "expense",
                    "company_ids": [Command.set([cls.company.id])],
                }
            )

        # Cuenta 130 (beneficio)
        cls.account_130 = Account.search(
            [
                ("code", "=like", "130%"),
                ("company_ids", "in", cls.company.id),
            ],
            limit=1,
        )
        if not cls.account_130:
            cls.account_130 = Account.create(
                {
                    "name": "Subvenciones oficiales de capital",
                    "code": "130000",
                    "account_type": "equity",
                    "company_ids": [Command.set([cls.company.id])],
                }
            )

        # Cuenta 131 (pérdida)
        cls.account_131 = Account.search(
            [
                ("code", "=like", "131%"),
                ("company_ids", "in", cls.company.id),
            ],
            limit=1,
        )
        if not cls.account_131:
            cls.account_131 = Account.create(
                {
                    "name": "Donaciones y legados de capital",
                    "code": "131000",
                    "account_type": "equity",
                    "company_ids": [Command.set([cls.company.id])],
                }
            )

        # Cuenta 294 (provisión)
        cls.account_294 = Account.search(
            [
                ("code", "=like", "294%"),
                ("company_ids", "in", cls.company.id),
            ],
            limit=1,
        )
        if not cls.account_294:
            cls.account_294 = Account.create(
                {
                    "name": "Provisiones material científico",
                    "code": "294000",
                    "account_type": "asset_current",
                    "company_ids": [Command.set([cls.company.id])],
                }
            )

        # Cuenta auxiliar para cuadrar asientos (ej: banco/caja)
        cls.account_bank = Account.search(
            [
                ("account_type", "=", "asset_cash"),
                ("company_ids", "in", cls.company.id),
            ],
            limit=1,
        )
        if not cls.account_bank:
            cls.account_bank = Account.create(
                {
                    "name": "Banco Test",
                    "code": "572000",
                    "account_type": "asset_cash",
                    "company_ids": [Command.set([cls.company.id])],
                }
            )

        # ------------------------------------------------------------------
        # Cuentas analíticas (proyectos)
        # ------------------------------------------------------------------
        AnalyticPlan = cls.env["account.analytic.plan"]
        cls.plan = AnalyticPlan.search([], limit=1)
        if not cls.plan:
            cls.plan = AnalyticPlan.create({"name": "Plan Test"})

        cls.analytic_1 = cls.env["account.analytic.account"].create(
            {
                "name": "Proyecto ALFA",
                "plan_id": cls.plan.id,
            }
        )
        cls.analytic_2 = cls.env["account.analytic.account"].create(
            {
                "name": "Proyecto BETA",
                "plan_id": cls.plan.id,
            }
        )

        # ------------------------------------------------------------------
        # Fechas del periodo
        # ------------------------------------------------------------------
        cls.date_from = date(2025, 1, 1)
        cls.date_to = date(2025, 12, 31)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _create_posted_move(self, lines, move_date=None):
        """Crea y publica un asiento con las líneas indicadas.

        lines: lista de dicts con keys:
            account_id, debit, credit, analytic_distribution (opcional)
        move_date: fecha del asiento (default: 2025-06-15)
        """
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.misc_journal.id,
                "date": move_date or date(2025, 6, 15),
                "company_id": self.company.id,
                "line_ids": [Command.create(vals) for vals in lines],
            }
        )
        move.action_post()
        return move

    def _create_wizard(self, **kwargs):
        """Crea una instancia del wizard con valores por defecto.

        Por defecto filtra por analytic_1 y analytic_2 para aislar de la BD.
        """
        vals = {
            "company_id": self.company.id,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "journal_id": self.misc_journal.id,
            "account_profit_id": self.account_130.id,
            "account_loss_id": self.account_131.id,
            "account_provision_id": self.account_294.id,
            "include_accounts_prefixes": "6,7",
            # Por defecto, filtramos por nuestras 2 analíticas de test
            "analytic_account_ids": [
                Command.set([self.analytic_1.id, self.analytic_2.id])
            ],
        }
        vals.update(kwargs)
        return self.env["aicia.project.closure.wizard"].create(vals)

    # ------------------------------------------------------------------
    # Tests de previsualización
    # ------------------------------------------------------------------
    def test_preview_single_project_positive(self):
        """Preview calcula correctamente un resultado positivo (ingresos > gastos)."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 1000,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 1000,
                    "credit": 0,
                },
            ]
        )
        self._create_posted_move(
            [
                {
                    "account_id": self.account_expense.id,
                    "debit": 600,
                    "credit": 0,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 0,
                    "credit": 600,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()

        self.assertEqual(wizard.state, "preview")
        self.assertEqual(len(wizard.preview_line_ids), 1)

        line = wizard.preview_line_ids[0]
        self.assertEqual(line.analytic_account_id, self.analytic_1)
        self.assertAlmostEqual(line.income, 1000.0, places=2)
        self.assertAlmostEqual(line.expense, 600.0, places=2)
        self.assertAlmostEqual(line.result, 400.0, places=2)
        self.assertEqual(line.target_account_id, self.account_130)
        self.assertAlmostEqual(line.provision_amount, 400.0, places=2)

    def test_preview_single_project_negative(self):
        """Preview calcula correctamente un resultado negativo (gastos > ingresos)."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 300,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 300,
                    "credit": 0,
                },
            ]
        )
        self._create_posted_move(
            [
                {
                    "account_id": self.account_expense.id,
                    "debit": 800,
                    "credit": 0,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 0,
                    "credit": 800,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()

        self.assertEqual(len(wizard.preview_line_ids), 1)
        line = wizard.preview_line_ids[0]
        self.assertAlmostEqual(line.income, 300.0, places=2)
        self.assertAlmostEqual(line.expense, 800.0, places=2)
        self.assertAlmostEqual(line.result, -500.0, places=2)
        self.assertEqual(line.target_account_id, self.account_131)

    def test_preview_multiple_projects(self):
        """Preview con 2 proyectos distintos genera 2 líneas."""
        # Proyecto ALFA: ingreso 1000
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 1000,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 1000,
                    "credit": 0,
                },
            ]
        )
        # Proyecto BETA: gasto 500
        self._create_posted_move(
            [
                {
                    "account_id": self.account_expense.id,
                    "debit": 500,
                    "credit": 0,
                    "analytic_distribution": {str(self.analytic_2.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 0,
                    "credit": 500,
                },
            ]
        )

        wizard = self._create_wizard()
        wizard.action_preview()

        self.assertEqual(len(wizard.preview_line_ids), 2)
        analytic_ids = wizard.preview_line_ids.mapped("analytic_account_id").ids
        self.assertIn(self.analytic_1.id, analytic_ids)
        self.assertIn(self.analytic_2.id, analytic_ids)

    def test_preview_proportional_distribution(self):
        """Línea con analytic_distribution 60/40 reparte balance proporcionalmente."""
        # Ingreso de 1000 repartido 60% ALFA, 40% BETA
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 1000,
                    "analytic_distribution": {
                        str(self.analytic_1.id): 60,
                        str(self.analytic_2.id): 40,
                    },
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 1000,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard()
        wizard.action_preview()

        self.assertEqual(len(wizard.preview_line_ids), 2)

        line_alfa = wizard.preview_line_ids.filtered(
            lambda l: l.analytic_account_id == self.analytic_1
        )
        line_beta = wizard.preview_line_ids.filtered(
            lambda l: l.analytic_account_id == self.analytic_2
        )

        self.assertAlmostEqual(line_alfa.income, 600.0, places=2)
        self.assertAlmostEqual(line_beta.income, 400.0, places=2)

    def test_preview_no_analytic_ignored(self):
        """Líneas sin analytic_distribution no contribuyen a ningún proyecto.

        Se crea un ingreso SIN analítica y otro CON analítica.
        Solo debe aparecer en preview el proyecto con analítica.
        El importe del ingreso sin analítica no debe sumarse a ningún proyecto.
        """
        # Ingreso sin analítica → debe ignorarse
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )
        # Ingreso CON analítica (ALFA) → debe aparecer
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 200,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 200,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()

        self.assertEqual(len(wizard.preview_line_ids), 1)
        line = wizard.preview_line_ids[0]
        self.assertEqual(line.analytic_account_id, self.analytic_1)
        # Solo 200 (el ingreso sin analítica no se suma)
        self.assertAlmostEqual(line.income, 200.0, places=2)

    def test_preview_filter_by_analytic(self):
        """Si se seleccionan analíticas específicas, solo esas aparecen."""
        # Ingreso en ALFA
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 1000,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 1000,
                    "credit": 0,
                },
            ]
        )
        # Ingreso en BETA
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 2000,
                    "analytic_distribution": {str(self.analytic_2.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 2000,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()

        self.assertEqual(len(wizard.preview_line_ids), 1)
        self.assertEqual(wizard.preview_line_ids.analytic_account_id, self.analytic_1)

    def test_preview_outside_date_range(self):
        """Movimientos fuera del rango de fechas no se incluyen.

        Crea un movimiento en 2024 (fuera del rango 2025) con analítica de test.
        Filtra por esa analítica → no debe haber resultados → UserError.
        """
        # Movimiento fuera de rango (2024)
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.misc_journal.id,
                "date": date(2024, 6, 15),
                "company_id": self.company.id,
                "line_ids": [
                    Command.create({
                        "account_id": self.account_income.id,
                        "debit": 0,
                        "credit": 999,
                        "analytic_distribution": {str(self.analytic_1.id): 100},
                    }),
                    Command.create({
                        "account_id": self.account_bank.id,
                        "debit": 999,
                        "credit": 0,
                    }),
                ],
            }
        )
        move.action_post()

        # Filtrar por analytic_1 para aislar de datos preexistentes
        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        with self.assertRaises(UserError):
            wizard.action_preview()

    # ------------------------------------------------------------------
    # Tests de generación de asientos
    # ------------------------------------------------------------------
    def test_generate_positive_result(self):
        """Genera asiento correcto para resultado positivo."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 1000,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 1000,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        wizard.action_generate()

        self.assertEqual(wizard.state, "done")
        self.assertEqual(len(wizard.created_move_ids), 1)

        move = wizard.created_move_ids[0]
        self.assertTrue(move.aicia_closure)
        self.assertTrue(move.aicia_closure_ref)
        self.assertIn("AICIA", move.ref)
        self.assertEqual(move.state, "posted")

        # Verificar estructura de líneas
        lines = move.line_ids.sorted("debit")
        self.assertEqual(len(lines), 2)

        # Línea de crédito en 130 (resultado positivo → credit en 130)
        credit_line = lines.filtered(lambda l: l.credit > 0)
        self.assertEqual(credit_line.account_id, self.account_130)
        self.assertAlmostEqual(credit_line.credit, 1000.0, places=2)
        self.assertEqual(
            credit_line.analytic_distribution, {str(self.analytic_1.id): 100}
        )

        # Línea de débito en 294
        debit_line = lines.filtered(lambda l: l.debit > 0)
        self.assertEqual(debit_line.account_id, self.account_294)
        self.assertAlmostEqual(debit_line.debit, 1000.0, places=2)

    def test_generate_negative_result(self):
        """Genera asiento correcto para resultado negativo."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_expense.id,
                    "debit": 800,
                    "credit": 0,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 0,
                    "credit": 800,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        wizard.action_generate()

        move = wizard.created_move_ids[0]

        # Línea de débito en 131 (resultado negativo → debit en 131)
        debit_line = move.line_ids.filtered(
            lambda l: l.account_id == self.account_131
        )
        self.assertAlmostEqual(debit_line.debit, 800.0, places=2)

        # Línea de crédito en 294
        credit_line = move.line_ids.filtered(
            lambda l: l.account_id == self.account_294
        )
        self.assertAlmostEqual(credit_line.credit, 800.0, places=2)

    def test_duplicate_detection(self):
        """Al ejecutar 2 veces, la segunda detecta duplicado y no genera."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        # Primera ejecución: OK
        wizard1 = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard1.action_preview()
        wizard1.action_generate()
        self.assertEqual(len(wizard1.created_move_ids), 1)

        # Segunda ejecución: duplicado
        wizard2 = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard2.action_preview()

        # La línea debe estar marcada como duplicado
        self.assertTrue(wizard2.preview_line_ids[0].has_existing_entries)

        # Al intentar generar, debe dar error porque no hay líneas procesables
        with self.assertRaises(UserError):
            wizard2.action_generate()

    def test_back_button(self):
        """Volver limpia preview y regresa a draft."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        self.assertEqual(wizard.state, "preview")
        self.assertTrue(wizard.preview_line_ids)

        wizard.action_back()
        self.assertEqual(wizard.state, "draft")
        self.assertFalse(wizard.preview_line_ids)

    def test_zero_result_skipped(self):
        """Proyecto con resultado cero no genera asiento."""
        # Ingreso y gasto iguales → resultado 0
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )
        self._create_posted_move(
            [
                {
                    "account_id": self.account_expense.id,
                    "debit": 500,
                    "credit": 0,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 0,
                    "credit": 500,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()

        self.assertEqual(len(wizard.preview_line_ids), 1)
        line = wizard.preview_line_ids[0]
        self.assertAlmostEqual(line.result, 0.0, places=2)

        # Al intentar generar, no hay líneas procesables
        with self.assertRaises(UserError):
            wizard.action_generate()

    def test_date_validation(self):
        """Fechas invertidas lanzan ValidationError."""
        with self.assertRaises(ValidationError):
            self._create_wizard(
                date_from=date(2025, 12, 31),
                date_to=date(2025, 1, 1),
            )

    def test_closure_move_has_analytic_distribution(self):
        """Los asientos generados llevan analytic_distribution en ambas líneas."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 750,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 750,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        wizard.action_generate()

        move = wizard.created_move_ids[0]
        for line in move.line_ids:
            self.assertTrue(
                line.analytic_distribution,
                f"La línea '{line.name}' debería tener analytic_distribution",
            )
            self.assertEqual(
                line.analytic_distribution,
                {str(self.analytic_1.id): 100},
            )

    def test_multiple_projects_generate_separate_moves(self):
        """Cada proyecto genera un asiento separado."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 1000,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 1000,
                    "credit": 0,
                },
            ]
        )
        self._create_posted_move(
            [
                {
                    "account_id": self.account_expense.id,
                    "debit": 2000,
                    "credit": 0,
                    "analytic_distribution": {str(self.analytic_2.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 0,
                    "credit": 2000,
                },
            ]
        )

        wizard = self._create_wizard()
        wizard.action_preview()
        wizard.action_generate()

        self.assertEqual(len(wizard.created_move_ids), 2)

        # Verificar que son asientos distintos
        refs = wizard.created_move_ids.mapped("aicia_closure_ref")
        self.assertEqual(len(set(refs)), 2)

    def test_closure_ref_format(self):
        """La referencia de cierre tiene el formato esperado."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        wizard.action_generate()

        move = wizard.created_move_ids[0]
        expected_ref = f"AICIA-{self.analytic_1.id}-{self.date_from}-{self.date_to}"
        self.assertEqual(move.aicia_closure_ref, expected_ref)

    def test_action_view_moves_single(self):
        """action_view_moves devuelve form si hay un solo asiento."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        wizard.action_generate()

        action = wizard.action_view_moves()
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["res_id"], wizard.created_move_ids.id)

    def test_action_view_moves_multiple(self):
        """action_view_moves devuelve list si hay varios asientos."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 300,
                    "analytic_distribution": {str(self.analytic_2.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 300,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard()
        wizard.action_preview()
        wizard.action_generate()

        action = wizard.action_view_moves()
        self.assertEqual(action["view_mode"], "list,form")
        self.assertIn("domain", action)

    def test_action_view_moves_empty(self):
        """action_view_moves devuelve None si no hay asientos creados."""
        wizard = self._create_wizard()
        result = wizard.action_view_moves()
        self.assertIsNone(result)

    def test_generate_without_preview_raises(self):
        """Generar sin previsualizar primero lanza UserError."""
        wizard = self._create_wizard()
        with self.assertRaises(UserError):
            wizard.action_generate()

    def test_empty_prefixes_raises(self):
        """Prefijos vacíos lanzan UserError al previsualizar."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 100,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 100,
                    "credit": 0,
                },
            ]
        )
        wizard = self._create_wizard(include_accounts_prefixes="  ")
        with self.assertRaises(UserError):
            wizard.action_preview()

    def test_move_date_is_date_to(self):
        """El asiento de cierre usa date_to como fecha del asiento."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        wizard.action_generate()

        move = wizard.created_move_ids[0]
        self.assertEqual(move.date, self.date_to)

    def test_move_journal_is_wizard_journal(self):
        """El asiento usa el diario configurado en el wizard."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        wizard.action_generate()

        move = wizard.created_move_ids[0]
        self.assertEqual(move.journal_id, self.misc_journal)

    def test_preview_clears_previous_lines(self):
        """Previsualizar de nuevo limpia las líneas previas."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )

        # Primera previsualización
        wizard.action_preview()
        first_line_ids = wizard.preview_line_ids.ids
        self.assertEqual(len(first_line_ids), 1)

        # Volver y previsualizar de nuevo
        wizard.action_back()
        wizard.action_preview()
        second_line_ids = wizard.preview_line_ids.ids

        self.assertEqual(len(second_line_ids), 1)
        # Las líneas deben ser distintas (las primeras fueron eliminadas)
        self.assertNotEqual(first_line_ids, second_line_ids)

    def test_created_move_count(self):
        """Campo computed created_move_count funciona correctamente."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        self.assertEqual(wizard.created_move_count, 0)

        wizard.action_preview()
        wizard.action_generate()
        self.assertEqual(wizard.created_move_count, 1)

    def test_narration_contains_project_info(self):
        """La narración del asiento contiene info del proyecto y periodo."""
        self._create_posted_move(
            [
                {
                    "account_id": self.account_income.id,
                    "debit": 0,
                    "credit": 500,
                    "analytic_distribution": {str(self.analytic_1.id): 100},
                },
                {
                    "account_id": self.account_bank.id,
                    "debit": 500,
                    "credit": 0,
                },
            ]
        )

        wizard = self._create_wizard(
            analytic_account_ids=[Command.set([self.analytic_1.id])]
        )
        wizard.action_preview()
        wizard.action_generate()

        move = wizard.created_move_ids[0]
        self.assertIn("Proyecto ALFA", move.narration)
        self.assertIn(str(self.date_from), move.narration)
        self.assertIn(str(self.date_to), move.narration)
