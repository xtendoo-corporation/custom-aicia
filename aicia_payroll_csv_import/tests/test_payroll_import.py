import base64
from datetime import date

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase


class TestAiciaPayrollImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env["account.journal"].search(
            [
                ("type", "=", "general"),
                ("company_id", "parent_of", cls.company.id),
            ],
            limit=1,
        )
        if not cls.journal:
            cls.journal = cls.env["account.journal"].create(
                {
                    "name": "Diario nóminas AICIA",
                    "code": "AICIA",
                    "type": "general",
                    "company_id": cls.company.id,
                }
            )

        cls.salary_account = cls._create_account("640000", "Sueldos y salarios", "expense")
        cls.ss_company_account = cls._create_account("642000", "SS empresa", "expense")
        cls.employee_payable_account = cls._create_account("465000", "Líquido nóminas", "liability_current")
        cls.irpf_account = cls._create_account("475100", "IRPF", "liability_current")
        cls.ss_payable_account = cls._create_account("476000", "Seguridad Social", "liability_current")
        cls.advance_account = cls._create_account("460000", "Anticipos", "asset_current")
        cls.deduction_account = cls._create_account("466000", "Otras deducciones", "liability_current")
        cls.diet_account = cls._create_account("640100", "Dietas", "expense")
        cls.km_account = cls._create_account("640101", "Kilometraje", "expense")
        cls.bonus_account = cls._create_account("640102", "Gratificaciones", "expense")
        cls.ct_expense_account = cls._create_account("623500", "Coste CT", "expense")
        cls.ct_payable_account = cls._create_account("410500", "Acreedor CT", "liability_current")
        cls.analytic_plan = cls.env["account.analytic.plan"].search([], limit=1)
        if not cls.analytic_plan:
            cls.analytic_plan = cls.env["account.analytic.plan"].create({"name": "Plan analítico pruebas"})
        cls.analytic_account_a = cls.env["account.analytic.account"].create(
            {
                "name": "Proyecto A",
                "company_id": cls.company.id,
                "plan_id": cls.analytic_plan.id,
            }
        )
        cls.analytic_account_b = cls.env["account.analytic.account"].create(
            {
                "name": "Proyecto B",
                "company_id": cls.company.id,
                "plan_id": cls.analytic_plan.id,
            }
        )

        config_values = {
            "name": "Configuración prueba AICIA",
            "company_id": cls.company.id,
            "journal_id": cls.journal.id,
            "salary_expense_account_id": cls.salary_account.id,
            "company_social_security_expense_account_id": cls.ss_company_account.id,
            "employee_payable_account_id": cls.employee_payable_account.id,
            "irpf_payable_account_id": cls.irpf_account.id,
            "social_security_payable_account_id": cls.ss_payable_account.id,
            "advance_account_id": cls.advance_account.id,
            "deduction_payable_account_id": cls.deduction_account.id,
            "diet_expense_account_id": cls.diet_account.id,
            "km_expense_account_id": cls.km_account.id,
            "bonus_expense_account_id": cls.bonus_account.id,
            "group_by_employee": False,
            "include_ct_costs": True,
            "ct_cost_expense_account_id": cls.ct_expense_account.id,
            "ct_cost_payable_account_id": cls.ct_payable_account.id,
        }
        cls.config = cls.env["aicia.payroll.config"].search([("company_id", "=", cls.company.id)], limit=1)
        if cls.config:
            cls.config.write(config_values)
        else:
            cls.config = cls.env["aicia.payroll.config"].create(config_values)

    @classmethod
    def _create_account(cls, code, name, account_type):
        account = cls.env["account.account"].search(
            [
                ("code", "=", code),
                ("company_ids", "parent_of", [cls.company.id]),
            ],
            limit=1,
        )
        if account:
            return account
        values = {
            "code": code,
            "name": name,
            "account_type": account_type,
            "company_ids": [Command.link(cls.company.id)],
        }
        if account_type in ("asset_receivable", "liability_payable"):
            values["reconcile"] = True
        return cls.env["account.account"].create(values)

    def _build_csv_payload(self):
        lines = [
            "EMPRESA: ASOC.INVEST.COOP.IND.ANDALUCIA",
            "CIF: G41099946",
            "",
            "FECHA PAGO;LIQUIDO;CONT;NIF;Nombre;IRPF;SS_TRABAJ;SS_EMPRES;DIETA;KM;GRATIFICAC;DEDUCCION;COST GEST;COST CT;COST DESP;ANTICIPOS",
        ]
        for index in range(77):
            lines.append(
                "30/04/2026;0,00;1;TEST%03d;Empleado %03d;0,00;0,00;0,00;0,00;0,00;0,00;0,00;0,6410256;0,6410256;0,00;0,00"
                % (index, index)
            )
        lines.append(
            "30/04/2026;103.847,46;1;TEST999;Empleado final;19.225,47;8.702,22;43.043,16;0,00;0,00;0,00;1.774,48;847,6410256;0,6410256;23,00;9,58"
        )
        return base64.b64encode("\n".join(lines).encode("cp1252"))

    def _build_employee_csv_payload(self, employee_name, nif):
        lines = [
            "EMPRESA: ASOC.INVEST.COOP.IND.ANDALUCIA",
            "CIF: G41099946",
            "",
            "FECHA PAGO;LIQUIDO;CONT;NIF;Nombre;IRPF;SS_TRABAJ;SS_EMPRES;DIETA;KM;GRATIFICAC;DEDUCCION;COST GEST;COST CT;COST DESP;ANTICIPOS",
            "30/04/2026;1000,00;1;%s;%s;100,00;50,00;200,00;0,00;0,00;0,00;0,00;0,00;0,00;0,00;0,00"
            % (nif, employee_name),
        ]
        return base64.b64encode("\n".join(lines).encode("cp1252"))

    def _build_multi_employee_csv_payload(
        self,
        first_employee_name="ABDALRAHEEM ABDULLAH, YOUSEF IJJEH",
        first_employee_nif="Z0915106X",
    ):
        lines = [
            "EMPRESA: ASOC.INVEST.COOP.IND.ANDALUCIA",
            "CIF: G41099946",
            "",
            "FECHA PAGO;LIQUIDO;CONT;NIF;Nombre;IRPF;SS_TRABAJ;SS_EMPRES;DIETA;KM;GRATIFICAC;DEDUCCION;COST GEST;COST CT;COST DESP;ANTICIPOS",
            "30/04/2026;1000,00;1;%s;%s;100,00;50,00;200,00;10,00;5,00;15,00;20,00;30,00;40,00;25,00;0,00"
            % (first_employee_nif, first_employee_name),
            "30/04/2026;900,00;1;12345678Z;Empleado Dos;90,00;45,00;180,00;0,00;0,00;0,00;0,00;20,00;10,00;5,00;0,00",
        ]
        return base64.b64encode("\n".join(lines).encode("cp1252"))

    def test_parse_csv_rounds_ct_total(self):
        payroll_import = self.env["aicia.payroll.import"].create(
            {
                "name": "Importación abril 2026",
                "company_id": self.company.id,
                "config_id": self.config.id,
                "csv_file": self._build_csv_payload(),
                "filename": "nominas_2026_04.csv",
            }
        )

        payroll_import.action_parse_csv()

        self.assertEqual(payroll_import.state, "parsed")
        self.assertEqual(payroll_import.employee_count, 78)
        self.assertEqual(payroll_import.payment_date, date(2026, 4, 30))
        self.assertEqual(payroll_import.period_label, "Abril 2026")
        self.assertEqual(payroll_import.source_company_name, "ASOC.INVEST.COOP.IND.ANDALUCIA")
        self.assertEqual(payroll_import.source_vat, "G41099946")
        self.assertEqual(payroll_import.total_liquid, 103847.46)
        self.assertEqual(payroll_import.total_irpf, 19225.47)
        self.assertEqual(payroll_import.total_ss_employee, 8702.22)
        self.assertEqual(payroll_import.total_ss_company, 43043.16)
        self.assertEqual(payroll_import.total_deduction, 1774.48)
        self.assertEqual(payroll_import.total_management_cost, 897.0)
        self.assertEqual(payroll_import.total_ct_cost, 50.0)
        self.assertEqual(payroll_import.total_travel_cost, 23.0)
        self.assertEqual(payroll_import.total_advances, 9.58)

    def test_create_aggregated_move_keeps_draft(self):
        payroll_import = self.env["aicia.payroll.import"].create(
            {
                "name": "Importación abril 2026",
                "company_id": self.company.id,
                "config_id": self.config.id,
                "csv_file": self._build_csv_payload(),
                "filename": "nominas_2026_04.csv",
            }
        )

        payroll_import.action_parse_csv()
        payroll_import.action_create_account_move()

        self.assertTrue(payroll_import.move_id)
        self.assertEqual(payroll_import.state, "move_created")
        self.assertEqual(payroll_import.move_id.state, "draft")
        self.assertEqual(payroll_import.move_id.move_type, "entry")
        self.assertEqual(payroll_import.move_id.ref, "Nóminas AICIA - Abril 2026")
        ct_expense_line = payroll_import.move_id.line_ids.filtered(
            lambda line: line.account_id == self.ct_expense_account and line.debit
        )
        self.assertTrue(ct_expense_line)
        self.assertEqual(ct_expense_line[0].debit, 50.0)

    def test_duplicate_checksum_is_blocked(self):
        payload = self._build_csv_payload()
        self.env["aicia.payroll.import"].create(
            {
                "name": "Importación 1",
                "company_id": self.company.id,
                "config_id": self.config.id,
                "csv_file": payload,
                "filename": "nominas_2026_04.csv",
            }
        )

        with self.assertRaises(ValidationError):
            self.env["aicia.payroll.import"].create(
                {
                    "name": "Importación 2",
                    "company_id": self.company.id,
                    "config_id": self.config.id,
                    "csv_file": payload,
                    "filename": "nominas_2026_04_duplicado.csv",
                }
            )

    def test_find_partner_from_label(self):
        partner = self.env["res.partner"].create(
            {
                "name": "ABDALRAHEEM ABDULLAH, YOUSEF IJJEH",
                "vat": "Z0915106X",
            }
        )
        payroll_import = self.env["aicia.payroll.import"].new(
            {
                "name": "Importación prueba partner",
                "company_id": self.company.id,
                "config_id": self.config.id,
            }
        )

        resolved_partner = payroll_import._find_partner_from_employee(
            line_name="ABDALRAHEEM ABDULLAH, YOUSEF IJJEH - Z0915106X - Salario bruto"
        )

        self.assertEqual(resolved_partner, partner)

    def test_create_employee_move_creates_one_move_per_employee(self):
        self.config.group_by_employee = True
        employee_name = "Empleado Analitica Prueba 001"
        employee_vat = "TESTEMP001"
        partner = self.env["res.partner"].create(
            {
                "name": employee_name,
                "vat": employee_vat,
            }
        )
        self.env["hr.employee"].create(
            {
                "name": partner.name,
                "identification_id": partner.vat,
                "work_contact_id": partner.id,
                "analytic_line_ids": [
                    Command.create(
                        {
                            "analytic_account_id": self.analytic_account_a.id,
                            "percentage": 60.0,
                        }
                    ),
                    Command.create(
                        {
                            "analytic_account_id": self.analytic_account_b.id,
                            "percentage": 40.0,
                        }
                    ),
                ],
            }
        )
        payroll_import = self.env["aicia.payroll.import"].create(
            {
                "name": "Importación abril 2026 por empleado",
                "company_id": self.company.id,
                "config_id": self.config.id,
                "csv_file": self._build_multi_employee_csv_payload(employee_name, employee_vat),
                "filename": "nominas_2026_04_empleado.csv",
            }
        )

        payroll_import.action_parse_csv()
        payroll_import.action_create_account_move()

        self.assertEqual(payroll_import.move_count, 2)
        self.assertEqual(len(payroll_import.move_ids), 2)
        self.assertTrue(all(move.state == "draft" for move in payroll_import.move_ids))

        partner_move = payroll_import.move_ids.filtered(lambda move: partner.name in (move.ref or ""))
        self.assertEqual(len(partner_move), 1)
        employee_lines = partner_move.line_ids.filtered(
            lambda line: line.name.startswith("%s - %s - " % (partner.name, partner.vat))
        )
        self.assertTrue(employee_lines)
        self.assertEqual(employee_lines.mapped("partner_id"), partner)
        salary_line = employee_lines.filtered(
            lambda line: line.name == "%s - %s - Salario bruto" % (partner.name, partner.vat)
        )
        self.assertTrue(salary_line)
        self.assertEqual(salary_line.partner_id, partner)
        self.assertEqual(
            salary_line.analytic_distribution,
            {
                str(self.analytic_account_a.id): 60.0,
                str(self.analytic_account_b.id): 40.0,
            },
        )
        ct_expense_line = employee_lines.filtered(
            lambda line: line.name == "%s - %s - Coste CT" % (partner.name, partner.vat)
        )
        self.assertTrue(ct_expense_line)
        self.assertEqual(
            ct_expense_line.analytic_distribution,
            {
                str(self.analytic_account_a.id): 60.0,
                str(self.analytic_account_b.id): 40.0,
            },
        )
        payable_line = employee_lines.filtered(
            lambda line: line.name == "%s - %s - Líquido" % (partner.name, partner.vat)
        )
        self.assertTrue(payable_line)
        self.assertFalse(payable_line.analytic_distribution)

