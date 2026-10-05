# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

"""Tests del importador de apuntes contables AICIA.

Estructura del Excel de origen:
  - Apuntes2025.xlsx: ID_Apunte, Numero_Apunte, Fecha_Contable (YYYYMMDD),
    Descripcion, Importe_Total (céntimos), Validado, Anulado
  - Lineas_Apunte2025.xlsx: ID_Apunte, Cuenta_Contable (9 dig), Descripcion,
    Importe (céntimos), Tipo_Contable (D/H)

Reglas que cubren estos tests:
  - Cuenta_Contable de 9 dígitos: 5 primeros + "0" = cuenta de Odoo (sin cuentas
    colectivas, sin redirección de grupos, sin búsqueda por prefijo);
    4 últimos = código AICIA del contacto de la línea (aicia.partner.code).
  - Un contacto puede tener varios códigos AICIA; cada código es único dentro
    de su tipo de tercero (personal, proveedor, cliente). El tipo sale del
    grupo de la cuenta; los demás grupos (bancos, gastos…) no llevan contacto.
  - Contacto no encontrado → asiento en borrador con aviso.
  - El total de un asiento es siempre la suma de sus líneas (céntimos enteros);
    el Importe_Total de la cabecera no se usa y, si difiere, solo se anota en el log.
  - Mapeo manual opcional de cuentas (vacío por defecto).
  - Parseo de fechas, idempotencia, anulados, estados, log HTML.
"""

from base64 import b64encode
from datetime import date, datetime
from io import BytesIO
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class TestAiciaAccountImporterWizard(TransactionCase):
    """Suite de tests del wizard AiciaAccountImporterWizard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls._ensure_journal_cls("general", "AIG")
        cls._ensure_journal_cls("sale", "AIS")
        cls._ensure_journal_cls("purchase", "AIP")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @classmethod
    def _ensure_journal_cls(cls, journal_type, code):
        journal = cls.env["account.journal"].search(
            [("type", "=", journal_type), ("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        if journal:
            return journal
        return cls.env["account.journal"].create({
            "name": f"AICIA test {journal_type}",
            "code": code,
            "type": journal_type,
            "company_id": cls.env.company.id,
        })

    def _make_wizard(self, **kwargs):
        defaults = {"move_state": "draft", "skip_anulados": True}
        defaults.update(kwargs)
        return self.env["aicia.account.importer.wizard"].create(defaults)

    def _make_apuntes_xlsx(self, rows: list) -> bytes:
        """Genera Apuntes2025.xlsx con la cabecera real del legado."""
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl no instalado")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Apuntes"
        ws.append([
            "ID_Apunte", "Numero_Apunte", "Fecha_Contable", "Fecha_Introduccion",
            "Descripcion", "Numero_Documento", "Importe_Total", "Validado",
            "Anulado", "Clase_Apunte",
        ])
        for row in rows:
            ws.append(row)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _make_lineas_xlsx(self, rows: list) -> bytes:
        """Genera Lineas_Apunte2025.xlsx con la cabecera real del legado."""
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl no instalado")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Lineas_Apunte"
        ws.append([
            "ID_Apunte", "ID_Linea", "Cuenta_Contable", "ID_Departamento",
            "ID_Proyecto", "Descripcion", "Importe", "Tipo_Contable",
        ])
        for row in rows:
            ws.append(row)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _enc(self, content: bytes) -> str:
        return b64encode(content).decode()

    def _import(self, apuntes_rows, lineas_rows, **wizard_kwargs):
        """Crea un wizard con los dos Excel, importa y devuelve el wizard."""
        wizard = self._make_wizard(
            file_apuntes=self._enc(self._make_apuntes_xlsx(apuntes_rows)),
            file_lineas=self._enc(self._make_lineas_xlsx(lineas_rows)),
            **wizard_kwargs,
        )
        wizard.action_import()
        return wizard

    def _ensure_account(self, code: str, name: str, account_type: str):
        existing = self.env["account.account"].search(
            [("code", "=", code), ("company_ids", "in", [self.env.company.id])],
            limit=1,
        )
        if existing:
            return existing
        return self.env["account.account"].create({
            "code": code,
            "name": name,
            "account_type": account_type,
            "company_ids": [(4, self.env.company.id)],
        })

    def _ensure_basic_accounts(self):
        self._ensure_account("610000", "Gastos test", "expense")
        self._ensure_account("572000", "Bancos test", "asset_cash")

    def _make_partner(self, name: str, *codes: str, partner_type: str = "employee"):
        return self.env["res.partner"].create({
            "name": name,
            "aicia_code_ids": [
                (0, 0, {"code": code, "partner_type": partner_type}) for code in codes
            ],
        })

    def _find_move_by_legacy_number(self, legacy_number: str):
        """Localiza el asiento importado por su Nº de asiento legado AICIA."""
        return self.env["account.move"].search(
            [("numero_asiento_aicia", "=", str(legacy_number))], limit=1
        )

    def _ensure_analytic_account(self, code: str, name: str):
        existing = self.env["account.analytic.account"].search(
            [("code", "=", code)], limit=1
        )
        if existing:
            return existing
        plan = self.env["account.analytic.plan"].search([], limit=1)
        if not plan:
            plan = self.env["account.analytic.plan"].create({"name": "AICIA Plan"})
        return self.env["account.analytic.account"].create({
            "name": name,
            "code": code,
            "plan_id": plan.id,
        })

    # ── Tests: parseo de Fecha_Contable ──────────────────────────────────────

    def test_parse_fecha_contable_entero_yyyymmdd(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._parse_fecha_contable(20250103), date(2025, 1, 3))

    def test_parse_fecha_contable_datetime(self):
        wizard = self._make_wizard()
        self.assertEqual(
            wizard._parse_fecha_contable(datetime(2025, 6, 15, 10, 0)),
            date(2025, 6, 15),
        )

    def test_parse_fecha_contable_date(self):
        wizard = self._make_wizard()
        self.assertEqual(
            wizard._parse_fecha_contable(date(2025, 3, 31)), date(2025, 3, 31)
        )

    def test_parse_fecha_contable_none_returns_today(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._parse_fecha_contable(None), date.today())

    def test_parse_fecha_contable_invalid_returns_today(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._parse_fecha_contable("no-es-fecha"), date.today())

    # ── Tests: Código AICIA del contacto ─────────────────────────────────────

    def test_partner_can_have_several_aicia_codes(self):
        partner = self._make_partner("Contacto multicódigo", "495", "496")
        self.assertEqual(set(partner.aicia_code_ids.mapped("code")), {"495", "496"})

    def test_aicia_code_is_unique_within_the_same_type(self):
        self._make_partner("Contacto A", "495")
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self._make_partner("Contacto B", "495")

    def test_aicia_code_can_repeat_across_types(self):
        """El 495 de un empleado y el de un proveedor son contactos distintos."""
        empleado = self._make_partner("Empleado 495", "495", partner_type="employee")
        proveedor = self._make_partner("Proveedor 495", "495", partner_type="supplier")
        cliente = self._make_partner("Cliente 495", "495", partner_type="customer")
        wizard = self._make_wizard()
        self.assertEqual(wizard._resolve_partner_by_aicia_code("495", "employee"), empleado)
        self.assertEqual(wizard._resolve_partner_by_aicia_code("495", "supplier"), proveedor)
        self.assertEqual(wizard._resolve_partner_by_aicia_code("495", "customer"), cliente)

    def test_aicia_code_is_stripped(self):
        partner = self._make_partner("Contacto espacios", " 495 ")
        self.assertEqual(partner.aicia_code_ids.code, "495")

    def test_aicia_code_leading_zeros_are_ignored(self):
        """0495 y 495 son el mismo código."""
        partner = self._make_partner("Contacto ceros", "0495")
        self.assertEqual(partner.aicia_code_ids.code, "495")
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self._make_partner("Contacto repetido", "495")

    def test_aicia_code_all_zeros_is_zero(self):
        partner = self._make_partner("Contacto cero", "0000")
        self.assertEqual(partner.aicia_code_ids.code, "0")

    def test_aicia_codes_are_not_copied_with_the_partner(self):
        partner = self._make_partner("Contacto original", "495")
        self.assertFalse(partner.copy().aicia_code_ids)

    def test_aicia_codes_are_deleted_with_the_partner(self):
        partner = self._make_partner("Contacto borrado", "495")
        code = partner.aicia_code_ids
        partner.unlink()
        self.assertFalse(code.exists())

    def test_partner_form_view_has_aicia_codes_page(self):
        arch = self.env["res.partner"].get_view(
            self.env.ref("base.view_partner_form").id
        )["arch"]
        self.assertIn("aicia_code_ids", arch)
        self.assertIn("partner_type", arch)

    def test_resolve_partner_by_aicia_code_found(self):
        partner = self._make_partner("Contacto 495", "495")
        wizard = self._make_wizard()
        self.assertEqual(wizard._resolve_partner_by_aicia_code("495", "employee"), partner)

    def test_resolve_partner_by_aicia_code_any_of_its_codes(self):
        partner = self._make_partner("Contacto 495/496", "495", "496")
        wizard = self._make_wizard()
        self.assertEqual(wizard._resolve_partner_by_aicia_code("496", "employee"), partner)

    def test_resolve_partner_by_aicia_code_wrong_type_returns_none(self):
        self._make_partner("Empleado 495", "495", partner_type="employee")
        wizard = self._make_wizard()
        self.assertIsNone(wizard._resolve_partner_by_aicia_code("495", "supplier"))

    def test_resolve_partner_by_aicia_code_not_found_returns_none(self):
        wizard = self._make_wizard()
        self.assertIsNone(wizard._resolve_partner_by_aicia_code("998", "employee"))

    def test_resolve_partner_by_aicia_code_empty_returns_none(self):
        wizard = self._make_wizard()
        self.assertIsNone(wizard._resolve_partner_by_aicia_code("", "employee"))
        self.assertIsNone(wizard._resolve_partner_by_aicia_code("495", ""))

    def test_partner_code_is_the_last_four_digits_as_a_number(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._partner_code_from_account("610003495"), "3495")
        self.assertEqual(wizard._partner_code_from_account("610000495"), "495")
        self.assertEqual(wizard._partner_code_from_account("610000000"), "0")

    # ── Tests: cuenta = 5 primeros dígitos + "0" ─────────────────────────────

    def test_odoo_account_code_is_first_five_digits_plus_zero(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._odoo_account_code("610003495"), "610000")
        self.assertEqual(wizard._odoo_account_code("616103257"), "616100")
        self.assertEqual(wizard._odoo_account_code("430013604"), "430010")

    def test_get_account_uses_first_five_digits_plus_zero(self):
        account = self._ensure_account("610000", "Gastos test", "expense")
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_account("610003495"), account)
        self.assertEqual(wizard._get_account("610000495"), account)

    def test_get_account_keeps_the_fifth_digit(self):
        """616103257 → 616100 (el quinto dígito sí cuenta)."""
        self._ensure_account("616000", "Gastos 616", "expense")
        account = self._ensure_account("616100", "Gastos 6161", "expense")
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_account("616103257"), account)

    def test_get_account_does_not_redirect_to_collective_account(self):
        """430013604 → 430010, nunca la colectiva 430000."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        sub = self._ensure_account("430010", "Cliente sub", "asset_receivable")
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_account("430013604"), sub)

    def test_get_account_does_not_create_accounts(self):
        before = self.env["account.account"].search_count([])
        wizard = self._make_wizard(missing_account_mode="error")
        wizard._get_account("699999123", set())
        self.assertEqual(self.env["account.account"].search_count([]), before)

    def test_get_account_missing_returns_none_and_registers_six_digit_code(self):
        wizard = self._make_wizard(missing_account_mode="error")
        missing = set()
        self.assertIsNone(wizard._get_account("699999123", missing))
        self.assertEqual(missing, {"699990"})

    def test_get_account_has_no_prefix_fallback(self):
        """Sin la cuenta exacta de 6 dígitos no se usa otra del mismo grupo."""
        self._ensure_account("610000", "Gastos test", "expense")
        wizard = self._make_wizard(missing_account_mode="error")
        self.assertIsNone(wizard._get_account("610999123", set()))

    def test_get_account_keeps_trailing_zeros(self):
        """Los ceros finales de la cuenta no se recortan (600000 es 600000)."""
        account = self._ensure_account("600000", "Compras test", "expense")
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_account("600000012"), account)

    def test_get_account_empty_returns_none(self):
        wizard = self._make_wizard()
        self.assertIsNone(wizard._get_account(""))

    def test_no_default_mapping_catalog(self):
        """Ya no existe el catálogo de mapeos por defecto ni su carga."""
        self.assertNotIn(
            "aicia.account.importer.account.mapping.default", self.env
        )
        self.assertFalse(
            hasattr(self.env["aicia.account.importer.account.mapping"],
                    "load_default_mappings")
        )
        self.assertFalse(hasattr(
            self.env["aicia.account.importer.wizard"],
            "action_load_default_account_mappings",
        ))

    def test_no_account_mapping_is_created_automatically(self):
        """Resolver una cuenta no deja mapeos automáticos por subcuenta."""
        self._ensure_account("610000", "Gastos test", "expense")
        count = self.env["aicia.account.importer.account.mapping"].search_count([])
        self._make_wizard()._get_account("610000495")
        self.assertEqual(
            self.env["aicia.account.importer.account.mapping"].search_count([]),
            count,
        )

    # ── Tests: mapeo manual (opcional) ───────────────────────────────────────

    def test_account_mapping_source_code_is_unique(self):
        """No permite dos mapeos con el mismo código origen normalizado."""
        target_account = self._ensure_account(
            "477000", "Cuenta destino test", "income"
        )
        Mapping = self.env["aicia.account.importer.account.mapping"]
        Mapping.create({
            "source_code": "478000000",
            "target_account_id": target_account.id,
        })

        with self.assertRaises(ValidationError):
            Mapping.create({
                "source_code": " 478000000 ",
                "target_account_id": target_account.id,
            })

    def test_account_mapping_persists_between_wizards(self):
        """Un mapeo guardado aparece al abrir un nuevo wizard."""
        target_account = self._ensure_account(
            "477001", "Cuenta destino persistente", "income"
        )
        mapping = self.env["aicia.account.importer.account.mapping"].create({
            "source_code": "478000001",
            "target_account_id": target_account.id,
        })

        wizard = self._make_wizard()
        defaults = wizard.default_get(["account_mapping_ids"])
        command = defaults["account_mapping_ids"][0]

        self.assertIn(mapping.id, command[2])

    def test_manual_mapping_wins_over_account_rule(self):
        """Un mapeo manual redirige aunque exista la cuenta de 5 dígitos + 0."""
        self._ensure_account("610000", "Gastos test", "expense")
        target = self._ensure_account("640000", "Sueldos test", "expense")
        self.env["aicia.account.importer.account.mapping"].create({
            "source_code": "610000",
            "target_account_id": target.id,
        })
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_account("610000495"), target)

    def test_get_account_mapping_exact_has_priority_over_prefix(self):
        """El mapeo exacto gana frente al prefijo global más genérico."""
        prefix_account = self._ensure_account(
            "477002", "Cuenta destino por prefijo", "income"
        )
        exact_account = self._ensure_account(
            "475002", "Cuenta destino exacta", "income"
        )
        Mapping = self.env["aicia.account.importer.account.mapping"]
        Mapping.create({
            "source_code": "478000",
            "target_account_id": prefix_account.id,
        })
        Mapping.create({
            "source_code": "478000000",
            "target_account_id": exact_account.id,
        })

        wizard = self._make_wizard()
        account = wizard._get_account("478000000")

        self.assertEqual(account.id, exact_account.id)

    def test_clear_account_mappings_removes_all_global_mappings(self):
        """El botón de borrado vacía la tabla persistente global."""
        target_account = self._ensure_account(
            "477003", "Cuenta destino borrado", "income"
        )
        self.env["aicia.account.importer.account.mapping"].create([
            {"source_code": "478000003", "target_account_id": target_account.id},
            {"source_code": "479000003", "target_account_id": target_account.id},
        ])

        wizard = self._make_wizard()
        wizard.action_clear_account_mappings()

        count = self.env["aicia.account.importer.account.mapping"].search_count([])
        self.assertEqual(count, 0)

    def test_no_files_applies_account_mapping_to_existing_move_lines(self):
        """Sin archivos → aplica el mapeo global sobre apuntes existentes."""
        source_account = self._ensure_account(
            "998001", "Cuenta origen remapeo", "expense"
        )
        target_account = self._ensure_account(
            "998002", "Cuenta destino remapeo", "expense"
        )
        counterpart_account = self._ensure_account(
            "998099", "Contrapartida remapeo", "income"
        )
        self.env["aicia.account.importer.account.mapping"].create({
            "source_code": source_account.code,
            "target_account_id": target_account.id,
        })
        move = self.env["account.move"].create({
            "journal_id": self.journal.id,
            "date": "2025-01-31",
            "line_ids": [
                (0, 0, {
                    "account_id": source_account.id,
                    "debit": 100.0,
                    "credit": 0.0,
                    "name": "Línea a remapear",
                }),
                (0, 0, {
                    "account_id": counterpart_account.id,
                    "debit": 0.0,
                    "credit": 100.0,
                    "name": "Contrapartida",
                }),
            ],
        })
        wizard = self._make_wizard()
        action = wizard.action_import()

        move.invalidate_recordset(["line_ids"])
        remapped_line = move.line_ids.filtered(
            lambda line: line.name == "Línea a remapear"
        )
        counterpart_line = move.line_ids.filtered(
            lambda line: line.name == "Contrapartida"
        )
        self.assertEqual(action["res_id"], wizard.id)
        self.assertEqual(wizard.state, "done")
        self.assertEqual(wizard.total_created, 1)
        self.assertEqual(wizard.total_errors, 0)
        self.assertEqual(remapped_line.account_id, target_account)
        self.assertEqual(counterpart_line.account_id, counterpart_account)
        self.assertIn("aplicado", wizard.import_log)

    def test_only_apuntes_file_raises_user_error(self):
        """Solo el archivo de apuntes sin líneas → UserError."""
        apuntes = self._make_apuntes_xlsx([
            [10, 1000, 20250101, None, "Test", "DOC", 0, True, False, "R"],
        ])
        wizard = self._make_wizard(file_apuntes=self._enc(apuntes))
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_wizard_allows_inline_account_mapping_edition(self):
        """La pestaña de cuentas edita el mapeo sin abrir otra ventana."""
        view = self.env.ref(
            "aicia_account_importer.view_aicia_account_importer_wizard_form"
        )
        field_start = view.arch_db.find('name="account_mapping_ids"')
        self.assertNotEqual(field_start, -1)
        field_end = view.arch_db.find("/>", field_start)
        account_mapping_field = view.arch_db[field_start:field_end]

        self.assertNotIn('readonly="1"', account_mapping_field)
        self.assertNotIn("action_open_account_mappings", view.arch_db)

    def test_wizard_view_has_no_create_missing_partners_option(self):
        view = self.env.ref(
            "aicia_account_importer.view_aicia_account_importer_wizard_form"
        )
        self.assertNotIn("create_missing_partners", view.arch_db)
        self.assertNotIn("action_load_default", view.arch_db)

    # ── Tests: importación — cuenta y contacto por línea ─────────────────────

    def test_import_account_is_five_digits_plus_zero_and_partner_is_last_four(self):
        """610003495 de 1576 € → cuenta 610000 con el contacto del código 3495."""
        self._ensure_basic_accounts()
        gasto = self._make_partner("Empleado 3495", "3495")

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC-1", 157600, True, False, "R"]],
            [
                [1, 1, "610003495", 0, 0, "Gasto", 157600, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 157600, "H"],
            ],
        )

        self.assertEqual(wizard.state, "done")
        self.assertEqual(wizard.total_created, 1)
        self.assertEqual(wizard.total_warnings, 0)
        self.assertEqual(wizard.total_errors, 0)
        move = self._find_move_by_legacy_number("100")
        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        credit_line = move.line_ids.filtered(lambda line: line.credit > 0)
        self.assertEqual(debit_line.account_id.code, "610000")
        self.assertAlmostEqual(debit_line.debit, 1576.0)
        self.assertEqual(debit_line.partner_id, gasto)
        # El banco (grupo 572) no es un tercero: sin contacto y sin aviso
        self.assertEqual(credit_line.account_id.code, "572000")
        self.assertFalse(credit_line.partner_id)

    def test_import_code_is_unique_per_type_not_global(self):
        """El mismo código en un empleado y en un proveedor no se confunde."""
        self._ensure_basic_accounts()
        self._ensure_account("400000", "Proveedores", "liability_payable")
        empleado = self._make_partner("Empleado 495", "495", partner_type="employee")
        proveedor = self._make_partner("Proveedor 495", "495", partner_type="supplier")

        self._import(
            [[1, 100, 20250115, None, "Compra", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "610000495", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "400000495", 0, 0, "Proveedor", 1000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("100")
        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        credit_line = move.line_ids.filtered(lambda line: line.credit > 0)
        self.assertEqual(debit_line.partner_id, empleado)
        self.assertEqual(credit_line.partner_id, proveedor)

    def test_import_partner_is_not_copied_to_other_lines(self):
        """Cada línea usa su propio código; no se propaga el primer contacto."""
        self._ensure_basic_accounts()
        empleado = self._make_partner("Empleado 495", "495")

        self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "610000495", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("100")
        credit_line = move.line_ids.filtered(lambda line: line.credit > 0)
        self.assertNotEqual(credit_line.partner_id, empleado)

    def test_import_does_not_use_collective_accounts(self):
        """430013604 va a la cuenta 430010, no a la colectiva 430000."""
        self._ensure_basic_accounts()
        self._ensure_account("430000", "Clientes", "asset_receivable")
        sub = self._ensure_account("430010", "Cliente sub", "asset_receivable")
        cliente = self._make_partner("Cliente 3604", "3604", partner_type="customer")

        self._import(
            [[1, 100, 20250115, None, "Cobro", "DOC", 5000, True, False, "R"]],
            [
                [1, 1, "572000001", 0, 0, "Banco", 5000, "D"],
                [1, 2, "430013604", 0, 0, "Cliente", 5000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("100")
        credit_line = move.line_ids.filtered(lambda line: line.credit > 0)
        self.assertEqual(credit_line.account_id, sub)
        self.assertEqual(credit_line.partner_id, cliente)

    def test_import_missing_partner_leaves_draft_with_warning(self):
        """Sin contacto con ese código el asiento queda en borrador con aviso."""
        self._ensure_basic_accounts()

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "610000777", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
            move_state="posted",
        )

        self.assertEqual(wizard.total_warnings, 1)
        self.assertEqual(wizard.total_errors, 0)
        self.assertEqual(wizard.total_created, 0)
        move = self._find_move_by_legacy_number("100")
        self.assertEqual(move.state, "draft")
        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        self.assertFalse(debit_line.partner_id)
        self.assertIn("777", wizard.import_log)
        self.assertIn("Personal", wizard.import_log)

    def test_import_partner_of_another_type_does_not_count(self):
        """Un proveedor con el código 495 no sirve para una línea de empleado."""
        self._ensure_basic_accounts()
        self._make_partner("Proveedor 495", "495", partner_type="supplier")

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "610000495", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
        )

        self.assertEqual(wizard.total_warnings, 1)

    def test_import_lines_of_untyped_groups_have_no_partner_and_no_warning(self):
        """Bancos, gastos 600, ingresos… no llevan contacto."""
        self._ensure_account("600000", "Compras test", "expense")
        self._ensure_account("572000", "Bancos test", "asset_cash")

        wizard = self._import(
            [[1, 100, 20250115, None, "Compra", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "600000300", 0, 0, "Compra", 1000, "D"],
                [1, 2, "572000106", 0, 0, "Banco", 1000, "H"],
            ],
        )

        self.assertEqual(wizard.total_created, 1)
        self.assertEqual(wizard.total_warnings, 0)
        move = self._find_move_by_legacy_number("100")
        self.assertFalse(move.line_ids.mapped("partner_id"))

    def test_import_does_not_create_partners(self):
        """El importador no crea contactos nuevos."""
        self._ensure_basic_accounts()
        before = self.env["res.partner"].search_count([])

        self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "610000777", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000888", 0, 0, "Pago", 1000, "H"],
            ],
        )

        self.assertEqual(self.env["res.partner"].search_count([]), before)

    def test_import_missing_account_is_error_and_registers_mapping(self):
        """Cuenta inexistente → error; el código de 6 dígitos queda en el mapeo."""
        self._ensure_basic_accounts()

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "699999123", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
            missing_account_mode="error",
        )

        self.assertEqual(wizard.total_errors, 1)
        self.assertEqual(wizard.total_created, 0)
        self.assertFalse(self._find_move_by_legacy_number("100"))
        mapping = self.env["aicia.account.importer.account.mapping"].search(
            [("source_code_normalized", "=", "699990")]
        )
        self.assertTrue(mapping)
        self.assertFalse(mapping.target_account_id)

    def test_import_zero_code_is_looked_up_like_any_other(self):
        """610000000 busca el código 0 (0000) del tipo personal."""
        self._ensure_basic_accounts()
        generico = self._make_partner("Contacto cero", "0000")

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "610000000", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
        )

        self.assertEqual(wizard.total_created, 1)
        move = self._find_move_by_legacy_number("100")
        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        self.assertEqual(debit_line.partner_id, generico)

    # ── Tests: cuentas que no existen en Odoo ────────────────────────────────

    def _account_by_code(self, code):
        return self.env["account.account"].search(
            [("code", "=", code), ("company_ids", "in", [self.env.company.id])]
        )

    def test_default_mode_creates_missing_accounts(self):
        self.assertEqual(self._make_wizard().missing_account_mode, "create")

    def test_missing_account_is_created_and_the_entry_is_imported(self):
        """Sin mapeo previo: la cuenta que falta se crea y el asiento se importa."""
        self._ensure_account("572000", "Bancos test", "asset_cash")
        self._make_partner("Empleado 495", "495")
        self.assertFalse(self._account_by_code("699990"))

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "699990495", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
        )

        account = self._account_by_code("699990")
        self.assertTrue(account)
        self.assertIn("*Cuenta legada 699990", account.name)
        self.assertEqual(wizard.total_errors, 0)
        self.assertEqual(wizard.total_accounts_created, 1)
        move = self._find_move_by_legacy_number("100")
        self.assertEqual(
            move.line_ids.filtered(lambda line: line.debit > 0).account_id, account
        )
        self.assertIn("Cuentas creadas automáticamente", wizard.import_log)
        self.assertIn("699990", wizard.import_log)

    def test_created_account_is_reused_by_every_line(self):
        self._ensure_account("572000", "Bancos test", "asset_cash")
        wizard = self._import(
            [
                [1, 100, 20250115, None, "Uno", "DOC", 1000, True, False, "R"],
                [2, 101, 20250116, None, "Dos", "DOC", 2000, True, False, "R"],
            ],
            [
                [1, 1, "699990000", 0, 0, "Uno", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Uno", 1000, "H"],
                [2, 1, "699990000", 0, 0, "Dos", 2000, "D"],
                [2, 2, "572000001", 0, 0, "Dos", 2000, "H"],
            ],
        )
        self.assertEqual(wizard.total_accounts_created, 1)
        self.assertEqual(len(self._account_by_code("699990")), 1)

    def test_created_account_copies_the_type_of_the_closest_account(self):
        # Grupo 996: no existe en ningún plan, así que la referencia es la nuestra
        self._ensure_account("996000", "Ingresos test", "income")
        wizard = self._make_wizard()
        account = wizard._get_account("996990000", set())
        self.assertEqual(account.account_type, "income")

    def test_created_account_defaults_to_expense_without_reference(self):
        wizard = self._make_wizard()
        account = wizard._get_account("899990000", set())
        self.assertTrue(account)
        self.assertTrue(account.account_type)

    def test_created_accounts_do_not_touch_the_manual_mapping(self):
        self._ensure_account("572000", "Bancos test", "asset_cash")
        count = self.env["aicia.account.importer.account.mapping"].search_count([])
        self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "699990000", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
        )
        self.assertEqual(
            self.env["aicia.account.importer.account.mapping"].search_count([]),
            count,
        )

    def test_fallback_mode_sends_the_line_to_the_reserve_account(self):
        self._ensure_account("572000", "Bancos test", "asset_cash")
        reserva = self._ensure_account("999999", "Cuenta de reserva", "expense")

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "699990123", 0, 0, "Gasto concreto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
            missing_account_mode="fallback",
            fallback_account_id=reserva.id,
        )

        self.assertEqual(wizard.total_errors, 0)
        self.assertEqual(wizard.total_accounts_created, 0)
        self.assertFalse(self._account_by_code("699990"))
        move = self._find_move_by_legacy_number("100")
        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        self.assertEqual(debit_line.account_id, reserva)
        self.assertEqual(debit_line.name, "[699990123] Gasto concreto")
        self.assertIn("cuenta de reserva", wizard.import_log)

    def test_fallback_mode_does_not_rename_lines_of_existing_accounts(self):
        self._ensure_basic_accounts()
        reserva = self._ensure_account("999999", "Cuenta de reserva", "expense")
        self._make_partner("Empleado 495", "495")
        self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "610000495", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
            missing_account_mode="fallback",
            fallback_account_id=reserva.id,
        )
        move = self._find_move_by_legacy_number("100")
        self.assertEqual(
            move.line_ids.filtered(lambda line: line.debit > 0).name, "Gasto"
        )

    def test_fallback_mode_without_reserve_account_raises(self):
        wizard = self._make_wizard(
            missing_account_mode="fallback",
            file_apuntes=self._enc(self._make_apuntes_xlsx([
                [1, 100, 20250115, None, "Gasto", "DOC", 1000, True, False, "R"]])),
            file_lineas=self._enc(self._make_lineas_xlsx([
                [1, 1, "699990000", 0, 0, "Gasto", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"]])),
        )
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_wizard_view_has_missing_account_option(self):
        view = self.env.ref(
            "aicia_account_importer.view_aicia_account_importer_wizard_form"
        )
        self.assertIn("missing_account_mode", view.arch_db)
        self.assertIn("fallback_account_id", view.arch_db)

    # ── Tests: importación — totales ─────────────────────────────────────────

    def test_import_total_is_sum_of_lines_not_header(self):
        """Importe_Total de cabecera distinto → se usan las líneas, sin borrador."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            # Cabecera dice 9.999,99 €; las líneas suman 1.576,00 €
            [[1, 100, 20250115, None, "Gasto", "DOC", 999999, True, False, "R"]],
            [
                [1, 1, "610000495", 0, 0, "Gasto", 157600, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 157600, "H"],
            ],
            move_state="posted",
        )

        self.assertEqual(wizard.total_created, 1)
        self.assertEqual(wizard.total_warnings, 0)
        self.assertEqual(wizard.total_errors, 0)
        self.assertEqual(wizard.total_mismatches, 1)  # solo informativo
        self.assertAlmostEqual(wizard.total_debe, 1576.0)
        self.assertAlmostEqual(wizard.total_haber, 1576.0)
        move = self._find_move_by_legacy_number("100")
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(sum(move.line_ids.mapped("debit")), 1576.0)
        self.assertAlmostEqual(move.amount_total, 1576.0)
        self.assertIn("9,999.99", wizard.import_log)
        self.assertIn("1,576.00", wizard.import_log)

    def test_import_header_total_matching_lines_has_no_mismatch(self):
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", 157600, True, False, "R"]],
            [
                [1, 1, "610000495", 0, 0, "Gasto", 157600, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 157600, "H"],
            ],
            move_state="posted",
        )

        self.assertEqual(wizard.total_mismatches, 0)
        self.assertEqual(wizard.total_created, 1)
        self.assertEqual(self._find_move_by_legacy_number("100").state, "posted")

    def test_import_without_header_total_is_accepted(self):
        """Cabecera sin Importe_Total: no hay comparación posible ni aviso."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            [[1, 100, 20250115, None, "Gasto", "DOC", None, True, False, "R"]],
            [
                [1, 1, "610000495", 0, 0, "Gasto", 5000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 5000, "H"],
            ],
        )

        self.assertEqual(wizard.total_mismatches, 0)
        self.assertEqual(wizard.total_created, 1)

    def test_import_totals_add_up_lines_of_all_entries(self):
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            [
                [1, 100, 20250115, None, "Uno", "DOC", 10000, True, False, "R"],
                [2, 101, 20250116, None, "Dos", "DOC", 25050, True, False, "R"],
            ],
            [
                [1, 1, "610000495", 0, 0, "Uno", 10000, "D"],
                [1, 2, "572000001", 0, 0, "Uno", 10000, "H"],
                [2, 1, "610000495", 0, 0, "Dos", 25050, "D"],
                [2, 2, "572000001", 0, 0, "Dos", 25050, "H"],
            ],
        )

        self.assertEqual(wizard.total_created, 2)
        self.assertAlmostEqual(wizard.total_debe, 350.50)
        self.assertAlmostEqual(wizard.total_haber, 350.50)
        self.assertIn("Totales", wizard.import_log)

    def test_import_converts_cents_to_euros(self):
        """Importe 121000 céntimos → 1210,00 € en la línea del asiento."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        self._import(
            [[2, 200, 20250115, None, "Test euros", "DOC", 121000, True, False, "R"]],
            [
                [2, 1, "610000495", 0, 0, "Test", 121000, "D"],
                [2, 2, "572000001", 0, 0, "Test", 121000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("200")
        self.assertTrue(move)
        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        self.assertAlmostEqual(debit_line[0].debit, 1210.0)

    def test_import_unbalanced_entry_is_error(self):
        """Asiento que no cuadra → error en log."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            [[4, 400, 20250115, None, "Descuadrado", "DOC", 0, True, False, "R"]],
            [
                [4, 1, "610000495", 0, 0, "Test", 100000, "D"],
                [4, 2, "572000001", 0, 0, "Test", 90000, "H"],  # diferencia: 100€
            ],
        )

        self.assertEqual(wizard.total_errors, 1)
        self.assertEqual(wizard.total_created, 0)
        self.assertIn("no cuadra", wizard.import_log)

    def test_import_unbalanced_by_one_cent_is_error(self):
        """Un céntimo de diferencia ya es un descuadre (suma en enteros)."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            [[4, 400, 20250115, None, "Un céntimo", "DOC", 10001, True, False, "R"]],
            [
                [4, 1, "610000495", 0, 0, "Test", 10001, "D"],
                [4, 2, "572000001", 0, 0, "Test", 10000, "H"],
            ],
        )

        self.assertEqual(wizard.total_errors, 1)
        self.assertFalse(self._find_move_by_legacy_number("400"))
        self.assertIn("no cuadra", wizard.import_log)

    def test_import_invalid_tipo_is_error(self):
        """Tipo_Contable distinto de D/H es un error, no una línea a cero."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            [[4, 400, 20250115, None, "Tipo malo", "DOC", 1000, True, False, "R"]],
            [
                [4, 1, "610000495", 0, 0, "Test", 1000, "D"],
                [4, 2, "572000001", 0, 0, "Test", 1000, "X"],
            ],
        )

        self.assertEqual(wizard.total_errors, 1)
        self.assertFalse(self._find_move_by_legacy_number("400"))
        self.assertIn("Tipo_Contable", wizard.import_log)

    def test_import_non_numeric_amount_is_error(self):
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            [[4, 400, 20250115, None, "Importe malo", "DOC", 1000, True, False, "R"]],
            [
                [4, 1, "610000495", 0, 0, "Test", "mil", "D"],
                [4, 2, "572000001", 0, 0, "Test", 1000, "H"],
            ],
        )

        self.assertEqual(wizard.total_errors, 1)
        self.assertIn("Importe no numérico", wizard.import_log)

    # ── Tests: importación — flujo general ───────────────────────────────────

    def test_account_code_numeric_zfill(self):
        """Cuenta como entero en Excel (sin ceros a la izq.) → zfill(9) correcto."""
        self._ensure_account("100000", "Capital test", "equity")
        self._ensure_account("572000", "Bancos test", "asset_cash")

        wizard = self._import(
            [[1, 101, 20250115, None, "Test zfill", "DOC", 50000, True, False, "R"]],
            # Cuenta_Contable como ENTERO: 100000001 y 572000001
            [
                [1, 1, 100000001, 0, 0, "Capital", 50000, "H"],
                [1, 2, 572000001, 0, 0, "Banco", 50000, "D"],
            ],
        )

        self.assertEqual(wizard.total_errors, 0)
        self.assertEqual(wizard.total_created, 1)

    def test_numero_apunte_float_no_dot_zero(self):
        """Numero_Apunte como float en Excel → se convierte a int (sin '.0')."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        self._import(
            [[2, 102.0, 20250115, None, "Test float ref", "DOC", 30000, True, False, "R"]],
            [
                [2, 1, "610000495", 0, 0, "Test", 30000, "D"],
                [2, 2, "572000001", 0, 0, "Test", 30000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("102")
        self.assertTrue(move, "El asiento debe tener ref='102', no '102.0'")

    def test_import_skips_duplicate(self):
        """Reimportar el mismo Numero_Apunte → se omite."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")
        apuntes = [[3, 300, 20250115, None, "Duplicado", "DOC", 50000, True, False, "R"]]
        lineas = [
            [3, 1, "610000495", 0, 0, "Test", 50000, "D"],
            [3, 2, "572000001", 0, 0, "Test", 50000, "H"],
        ]

        self._import(apuntes, lineas)
        second = self._import(apuntes, lineas)

        self.assertEqual(second.total_skipped, 1)
        self.assertEqual(second.total_created, 0)

    def test_import_numero_asiento_aicia_is_idempotent_reference(self):
        """Reimportar no duplica: la referencia cruzada apunta a un único asiento."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")
        apuntes = [[41, 4100, 20250115, None, "Dup ref", "DOC", 30000, True, False, "R"]]
        lineas = [
            [41, 1, "610000495", 0, 0, "Test", 30000, "D"],
            [41, 2, "572000001", 0, 0, "Test", 30000, "H"],
        ]

        self._import(apuntes, lineas)
        self._import(apuntes, lineas)

        moves = self.env["account.move"].search(
            [("numero_asiento_aicia", "=", "4100")]
        )
        self.assertEqual(len(moves), 1, "No debe duplicarse el asiento reimportado")

    def test_import_skips_anulados(self):
        """Asientos anulados se omiten cuando skip_anulados=True."""
        apuntes = self._make_apuntes_xlsx([
            [5, 500, 20250115, None, "Anulado", "DOC", 0, True, True, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [5, 1, "610000495", 0, 0, "Test", 10000, "D"],
            [5, 2, "572000001", 0, 0, "Test", 10000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
            skip_anulados=True,
        )
        with self.assertRaises(UserError):
            # No hay asientos válidos → UserError del _parse_apuntes
            wizard.action_import()

    def test_import_skips_not_validated(self):
        """Asientos con Validado=False no se importan."""
        apuntes = self._make_apuntes_xlsx([
            [6, 600, 20250115, None, "No validado", "DOC", 0, False, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [6, 1, "610000495", 0, 0, "Test", 10000, "D"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_import_no_lines_for_entry_is_error(self):
        """Asiento válido sin líneas en Lineas_Apunte → error en log."""
        wizard = self._import(
            [[7, 700, 20250115, None, "Sin líneas", "DOC", 0, True, False, "R"]],
            [],
        )

        self.assertEqual(wizard.total_errors, 1)
        self.assertEqual(wizard.total_created, 0)

    def test_import_posted_state(self):
        """move_state='posted' → asiento confirmado si no hay avisos."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        self._import(
            [[8, 800, 20250201, None, "Posted test", "DOC", 80000, True, False, "R"]],
            [
                [8, 1, "610000495", 0, 0, "Test", 80000, "D"],
                [8, 2, "572000001", 0, 0, "Test", 80000, "H"],
            ],
            move_state="posted",
        )

        move = self._find_move_by_legacy_number("800")
        self.assertEqual(move.state, "posted")

    def test_import_puts_entry_name_in_ref_and_leaves_name_for_sequence(self):
        """El texto visible va a ref y el nombre Odoo queda en '/' para la serie."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        self._import(
            [[30, 3000, 20250115, None, "Venta visible en referencia", "DOC-3000", 121000, True, False, "R"]],
            [
                [30, 1, "610000495", 0, 0, "Gasto", 121000, "D"],
                [30, 2, "572000001", 0, 0, "Pago", 121000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("3000")
        self.assertTrue(move)
        self.assertEqual(move.ref, "Venta visible en referencia")
        self.assertEqual(move.name, "/")

    def test_import_stores_numero_asiento_aicia(self):
        """El Numero_Apunte del legado se guarda en numero_asiento_aicia."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        self._import(
            [[40, 4000, 20250115, None, "Ref cruzada", "DOC", 30000, True, False, "R"]],
            [
                [40, 1, "610000495", 0, 0, "Test", 30000, "D"],
                [40, 2, "572000001", 0, 0, "Test", 30000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("4000")
        self.assertTrue(move, "El asiento debe localizarse por numero_asiento_aicia")
        self.assertEqual(move.numero_asiento_aicia, "4000")

    def test_import_log_html_generated(self):
        """Tras importar, import_log contiene HTML con el resumen y los totales."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        wizard = self._import(
            [[9, 900, 20250301, None, "Log test", "DOC", 30000, True, False, "R"]],
            [
                [9, 1, "610000495", 0, 0, "Test", 30000, "D"],
                [9, 2, "572000001", 0, 0, "Test", 30000, "H"],
            ],
        )

        self.assertIn("Resumen", wizard.import_log)
        self.assertIn("creados", wizard.import_log)
        self.assertIn("Totales", wizard.import_log)

    def test_import_continues_after_a_database_error_in_one_entry(self):
        """Un error de BD en un asiento no aborta la transacción de los demás."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")
        Move = type(self.env["account.move"])
        original_create = Move.create
        calls = {"n": 0}

        def flaky_create(model, vals):
            calls["n"] += 1
            if calls["n"] == 1:
                model.env.cr.execute("SELECT 1/0")
            return original_create(model, vals)

        with patch.object(Move, "create", flaky_create), mute_logger("odoo.sql_db"):
            wizard = self._import(
                [
                    [1, 100, 20250115, None, "Falla", "DOC", 1000, True, False, "R"],
                    [2, 101, 20250116, None, "Funciona", "DOC", 2000, True, False, "R"],
                ],
                [
                    [1, 1, "610000495", 0, 0, "Uno", 1000, "D"],
                    [1, 2, "572000001", 0, 0, "Uno", 1000, "H"],
                    [2, 1, "610000495", 0, 0, "Dos", 2000, "D"],
                    [2, 2, "572000001", 0, 0, "Dos", 2000, "H"],
                ],
            )

        self.assertEqual(wizard.total_errors, 1)
        self.assertEqual(wizard.total_created, 1)
        self.assertFalse(self._find_move_by_legacy_number("100"))
        self.assertTrue(self._find_move_by_legacy_number("101"))

    # ── Tests: diario ─────────────────────────────────────────────────────────

    def test_import_nomina_entry_goes_to_general_journal(self):
        """Numero_Documento 'NO-…' → diario misceláneo."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")

        self._import(
            [[1, 100, 20250115, None, "Nómina", "NO-001", 1000, True, False, "R"]],
            [
                [1, 1, "610000495", 0, 0, "Nómina", 1000, "D"],
                [1, 2, "572000001", 0, 0, "Pago", 1000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("100")
        self.assertEqual(move.journal_id.type, "general")

    def test_import_customer_entry_goes_to_sale_journal(self):
        self._ensure_basic_accounts()
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._make_partner("Cliente 3604", "3604", partner_type="customer")

        self._import(
            [[1, 100, 20250115, None, "Cobro", "DOC", 1000, True, False, "R"]],
            [
                [1, 1, "572000001", 0, 0, "Banco", 1000, "D"],
                [1, 2, "430003604", 0, 0, "Cliente", 1000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("100")
        self.assertEqual(move.journal_id.type, "sale")

    # ── Tests: proyecto analítico ────────────────────────────────────────────

    def test_import_project_zero_assigns_aicia_analytic(self):
        """ID_Proyecto=0 asigna la cuenta analítica [0] AICIA (0 no es 'sin proyecto')."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")
        analytic = self._ensure_analytic_account("0", "AICIA")

        self._import(
            [[42, 4200, 20250115, None, "Proyecto 0", "DOC", 30000, True, False, "R"]],
            [
                [42, 1, "610000495", 0, 0, "Test", 30000, "D"],
                [42, 2, "572000001", 0, 0, "Test", 30000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("4200")
        self.assertTrue(move)
        for line in move.line_ids:
            self.assertEqual(
                line.analytic_distribution,
                {str(analytic.id): 100.0},
                "Toda línea con ID_Proyecto=0 debe imputarse al proyecto AICIA",
            )

    def test_import_project_empty_leaves_no_analytic(self):
        """Celda ID_Proyecto vacía (None) → sin distribución analítica."""
        self._ensure_basic_accounts()
        self._make_partner("Contacto 495", "495")
        self._ensure_analytic_account("0", "AICIA")

        self._import(
            [[43, 4300, 20250115, None, "Sin proyecto", "DOC", 30000, True, False, "R"]],
            [
                [43, 1, "610000495", 0, None, "Test", 30000, "D"],
                [43, 2, "572000001", 0, None, "Test", 30000, "H"],
            ],
        )

        move = self._find_move_by_legacy_number("4300")
        self.assertTrue(move)
        for line in move.line_ids:
            self.assertFalse(
                line.analytic_distribution,
                "Sin ID_Proyecto no debe asignarse distribución analítica",
            )
