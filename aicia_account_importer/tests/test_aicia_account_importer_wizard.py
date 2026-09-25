# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

"""Tests del importador de apuntes contables AICIA.

Estructura del Excel de origen:
  - Apuntes2025.xlsx: ID_Apunte, Numero_Apunte, Fecha_Contable (YYYYMMDD),
    Descripcion, Validado, Anulado
  - Lineas_Apunte2025.xlsx: ID_Apunte, Cuenta_Contable (9 dig), Descripcion,
    Importe (céntimos), Tipo_Contable (D/H)

Cubre:
  - Parseo de Fecha_Contable (entero YYYYMMDD, datetime, string)
  - Conversión de importes de céntimos a euros
  - Cuentas colectivas: 400xxxxxx→400000, 430xxxxxx→430000, 572xxxxxx→572000
  - Cuentas normales: normalización 9→6 dígitos
  - Creación y omisión de partners en cuentas 400/430
  - Importación completa de asientos cuadrados
  - Idempotencia (duplicados omitidos por Numero_Apunte)
  - Asientos no cuadrados → error en log
  - Asientos anulados omitidos con skip_anulados=True
  - Asientos no validados omitidos
  - Sin archivos → reaplica el mapeo sobre apuntes existentes
  - Sin líneas para un asiento → error en log
  - Estado draft y posted tras la importación
  - Generación de log HTML con resumen
"""

from base64 import b64encode
from datetime import date, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestAiciaAccountImporterWizard(TransactionCase):
    """Suite de tests del wizard AiciaAccountImporterWizard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.env.company.id)],
            limit=1,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_wizard(self, **kwargs):
        defaults = {
            "move_state": "draft",
            "create_missing_partners": True,
            "skip_anulados": True,
        }
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

    def _create_account_user(self, suffix: str):
        return self.env["res.users"].create({
            "name": f"Account User {suffix}",
            "login": f"account_user_{suffix}",
            "email": f"account_user_{suffix}@example.com",
            "group_ids": [(6, 0, [self.env.ref("account.group_account_user").id])],
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
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

    # ── Tests: cuentas colectivas ─────────────────────────────────────────────

    def test_get_collective_prefix_400(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_collective_prefix("400000043"), "400")

    def test_get_collective_prefix_401(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_collective_prefix("401000099"), "401")

    def test_get_collective_prefix_430(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_collective_prefix("430003604"), "430")

    def test_get_collective_prefix_572(self):
        wizard = self._make_wizard()
        self.assertEqual(wizard._get_collective_prefix("572000106"), "572")

    def test_get_collective_prefix_none_for_normal(self):
        wizard = self._make_wizard()
        self.assertIsNone(wizard._get_collective_prefix("610000000"))

    def test_get_account_430_uses_colectiva(self):
        """430003604 → devuelve/crea la cuenta colectiva 430000."""
        self.env["account.account"].search(
            [("code", "=", "430000"), ("company_ids", "in", [self.env.company.id])]
        ).unlink()
        wizard = self._make_wizard()
        acc = wizard._get_account("430003604")
        self.assertIsNotNone(acc)
        self.assertEqual(acc.code, "430000")

    def test_get_account_400_uses_colectiva(self):
        """400000043 → devuelve/crea la cuenta colectiva 400000."""
        wizard = self._make_wizard()
        acc = wizard._get_account("400000043")
        self.assertIsNotNone(acc)
        self.assertEqual(acc.code, "400000")

    def test_get_account_572_uses_colectiva_if_exact_missing(self):
        """572000106 sin cuenta exacta → normaliza a 572000."""
        self.env["account.account"].search(
            [("code", "in", ["572000", "572000106"]),
             ("company_ids", "in", [self.env.company.id])]
        ).unlink()
        wizard = self._make_wizard()
        acc = wizard._get_account("572000106")
        self.assertIsNotNone(acc)
        self.assertEqual(acc.code, "572000")

    def test_get_account_572_truncates_to_first_6_digits(self):
        """572123456 → resuelve la cuenta 572123 y nunca una de más de 6 dígitos."""
        truncated_account = self.env["account.account"].search(
            [
                ("code", "=like", "572___"),
                ("company_ids", "in", [self.env.company.id]),
            ],
            order="code desc",
            limit=1,
        )
        if not truncated_account:
            self.skipTest("No existe ninguna cuenta 572XXX en el plan contable de pruebas")
        legacy_code = f"{truncated_account.code}123"

        wizard = self._make_wizard()
        acc = wizard._get_account(legacy_code)

        self.assertIsNotNone(acc)
        self.assertEqual(acc.id, truncated_account.id)
        self.assertEqual(acc.code, truncated_account.code)
        self.assertEqual(len(acc.code), 6)

    def test_get_account_normal_normalizes_to_6_digits(self):
        """610000000 → busca cuenta normalizada a 6 dígitos (610000 o 610)."""
        self._ensure_account("610000", "Variación existencias", "expense")
        wizard = self._make_wizard()
        acc = wizard._get_account("610000000")
        self.assertIsNotNone(acc)

    def test_get_account_normalization_creates_persistent_mapping(self):
        """115000000 → 115000 deja traza persistente en el mapeo global."""
        account = self._ensure_account("115000", "Inmovilizado material", "asset_fixed")
        wizard = self._make_wizard()

        resolved_account = wizard._get_account("115000000")
        mapping = self.env["aicia.account.importer.account.mapping"].search(
            [("source_code_normalized", "=", "115000000")], limit=1
        )

        self.assertEqual(resolved_account.id, account.id)
        self.assertTrue(mapping)
        self.assertEqual(mapping.source_code, "115000000")
        self.assertEqual(mapping.source_code_normalized, "115000000")
        self.assertEqual(mapping.target_account_id.id, account.id)

    def test_get_account_empty_returns_none(self):
        wizard = self._make_wizard()
        self.assertIsNone(wizard._get_account(""))

    def test_get_nomina_account_code_for_lookup_changes_610_to_640(self):
        """Las cuentas de nómina 610XXXXXX se reclasifican a 640XXX con 6 dígitos."""
        wizard = self._make_wizard()

        self.assertEqual(
            wizard._get_nomina_account_code_for_lookup("610123456"), "640123"
        )
        self.assertEqual(
            wizard._get_nomina_account_code_for_lookup("610000000"), "640000"
        )

    def test_build_line_vals_nomina_610_uses_640_after_partner_assignment(self):
        """Tras resolver el empleado, la línea de nómina busca la cuenta 640XXX."""
        wizard = self._make_wizard(create_missing_partners=False)
        partner = self.env.user.partner_id
        account = self.env["account.account"].search(
            [("company_ids", "in", [self.env.company.id])], limit=1
        )
        self.assertTrue(account)

        linea = {
            "cuenta": "610123456",
            "descripcion": "Nómina empleado",
            "debit": 100.0,
            "credit": 0.0,
            "id_proyecto": None,
        }

        with (
            patch.object(
                type(wizard),
                "_resolve_partner_nomina",
                autospec=True,
                return_value=partner,
            ) as mocked_resolve_partner,
            patch.object(
                type(wizard),
                "_get_account",
                autospec=True,
                return_value=account,
            ) as mocked_get_account,
        ):
            vals, error, warning = wizard._build_line_vals(
                linea,
                "Asiento nómina",
                set(),
                {},
                is_nomina=True,
            )

        self.assertFalse(error)
        self.assertFalse(warning)
        self.assertEqual(vals["partner_id"], partner.id)
        mocked_resolve_partner.assert_called_once()
        self.assertEqual(mocked_get_account.call_args.args[1], "640123")
        self.assertTrue(mocked_get_account.call_args.kwargs["skip_collective"])

    def test_build_line_vals_nomina_610_honors_manual_mapping(self):
        """El mapeo manual de nóminas gana a la regla automática 610→640XXX."""
        wizard = self._make_wizard(create_missing_partners=False)
        partner = self.env.user.partner_id
        target_account = self._ensure_account("640000", "Sueldos y salarios", "expense")
        self.env["aicia.account.importer.account.mapping"].create({
            "source_code": "610",
            "target_account_id": target_account.id,
        })

        linea = {
            "cuenta": "610123456",
            "descripcion": "Nómina empleado",
            "debit": 100.0,
            "credit": 0.0,
            "id_proyecto": None,
        }

        with patch.object(
            type(wizard),
            "_resolve_partner_nomina",
            autospec=True,
            return_value=partner,
        ):
            vals, error, warning = wizard._build_line_vals(
                linea,
                "Asiento nómina",
                set(),
                {},
                is_nomina=True,
            )

        self.assertFalse(error)
        self.assertFalse(warning)
        self.assertEqual(vals["account_id"], target_account.id)
        self.assertEqual(vals["partner_id"], partner.id)

    def test_get_employee_partner_prefers_partner_id(self):
        wizard = self._make_wizard()
        partner = self.env.user.partner_id
        employee = SimpleNamespace(
            _fields={"partner_id": object(), "work_contact_id": object()},
            partner_id=partner,
            work_contact_id=False,
        )

        self.assertEqual(wizard._get_employee_partner(employee).id, partner.id)

    def test_get_employee_partner_falls_back_to_work_contact_id(self):
        wizard = self._make_wizard()
        partner = self.env.user.partner_id
        employee = SimpleNamespace(
            _fields={"work_contact_id": object()},
            work_contact_id=partner,
        )

        self.assertEqual(wizard._get_employee_partner(employee).id, partner.id)

    # ── Tests: mapeo persistente de cuentas ─────────────────────────────────

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
            "source_code": "478",
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

    def test_load_default_mappings_creates_missing_defaults(self):
        """Carga mapeos por defecto cuando existe la cuenta destino."""
        mapping_model = self.env["aicia.account.importer.account.mapping"]
        mapping_model.search(
            [("source_code_normalized", "=", "991001000")]
        ).unlink()
        target_account = self._ensure_account(
            "991001", "Cuenta destino por defecto", "income"
        )

        with patch.object(
            type(mapping_model),
            "_get_default_mapping_values",
            autospec=True,
            return_value=[("991001000", "991001")],
        ):
            mapping_model.load_default_mappings()

        mapping = mapping_model.search(
            [("source_code_normalized", "=", "991001000")], limit=1
        )
        self.assertTrue(mapping)
        self.assertEqual(mapping.target_account_id.id, target_account.id)

    def test_default_mapping_catalog_is_read_only_for_account_users(self):
        """El catálogo técnico es legible para contabilidad pero no editable."""
        account_user = self._create_account_user("default_mapping")
        default_mapping_model = self.env[
            "aicia.account.importer.account.mapping.default"
        ].with_user(account_user)

        self.assertTrue(default_mapping_model.search([], limit=1))

        with self.assertRaises(AccessError):
            default_mapping_model.create({
                "source_code": "999998000",
                "target_account_code": "999998",
            })

    def test_load_default_mappings_creates_missing_target_account(self):
        """Crea la cuenta destino ausente y la enlaza al mapeo por defecto."""
        mapping_model = self.env["aicia.account.importer.account.mapping"]
        target_code = "620999"
        mapping_model.search(
            [("source_code_normalized", "=", "991002000")]
        ).unlink()
        self.env["account.account"].search(
            [("code", "=", target_code), ("company_ids", "in", [self.env.company.id])]
        ).unlink()

        with patch.object(
            type(mapping_model),
            "_get_default_mapping_values",
            autospec=True,
            return_value=[("991002000", target_code)],
        ):
            mapping_model.load_default_mappings()

        mapping = mapping_model.search(
            [("source_code_normalized", "=", "991002000")], limit=1
        )
        target_account = self.env["account.account"].search(
            [("code", "=", target_code), ("company_ids", "in", [self.env.company.id])],
            limit=1,
        )
        self.assertTrue(mapping)
        self.assertTrue(target_account)
        self.assertEqual(target_account.name, "*Cuenta no encontrada")
        self.assertEqual(target_account.account_type, "expense")
        self.assertEqual(mapping.target_account_id.id, target_account.id)

    def test_load_default_mappings_keeps_existing_target(self):
        """No sobrescribe mapeos ya configurados por el usuario."""
        mapping_model = self.env["aicia.account.importer.account.mapping"]
        existing_target = self._ensure_account(
            "991003", "Cuenta destino manual", "income"
        )
        default_target = self._ensure_account(
            "991004", "Cuenta destino por defecto", "income"
        )
        mapping_model.search(
            [("source_code_normalized", "=", "991003000")]
        ).unlink()
        mapping = mapping_model.create(
            {
                "source_code": "991003000",
                "target_account_id": existing_target.id,
            }
        )

        with patch.object(
            type(mapping_model),
            "_get_default_mapping_values",
            autospec=True,
            return_value=[("991003000", "991004")],
        ):
            mapping_model.load_default_mappings()

        self.assertEqual(mapping_model.search_count([
            ("source_code_normalized", "=", "991003000")
        ]), 1)
        self.assertEqual(mapping.target_account_id.id, existing_target.id)
        self.assertNotEqual(mapping.target_account_id.id, default_target.id)

    def test_action_load_default_mappings_updates_empty_targets(self):
        """La acción manual completa mapeos vacíos y devuelve notificación."""
        mapping_model = self.env["aicia.account.importer.account.mapping"]
        target_account = self._ensure_account(
            "991005", "Cuenta destino recarga", "income"
        )
        mapping_model.search(
            [("source_code_normalized", "=", "991005000")]
        ).unlink()
        mapping = mapping_model.create({"source_code": "991005000"})

        with patch.object(
            type(mapping_model),
            "_get_default_mapping_values",
            autospec=True,
            return_value=[("991005000", "991005")],
        ):
            action = mapping.action_load_default_mappings()

        mapping.invalidate_recordset(["target_account_id"])
        self.assertEqual(mapping.target_account_id.id, target_account.id)
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["next"]["tag"], "reload")

    def test_action_load_default_mappings_refreshes_wizard_mappings(self):
        """La recarga desde el wizard sincroniza la pestaña con los nuevos mapeos."""
        mapping_model = self.env["aicia.account.importer.account.mapping"]
        wizard = self._make_wizard()
        target_account = self._ensure_account(
            "991006", "Cuenta destino wizard", "income"
        )
        mapping_model.search(
            [("source_code_normalized", "=", "991006000")]
        ).unlink()

        with patch.object(
            type(mapping_model),
            "_get_default_mapping_values",
            autospec=True,
            return_value=[("991006000", "991006")],
        ):
            action = mapping_model.with_context(
                active_model=wizard._name,
                active_id=wizard.id,
            ).action_load_default_mappings()

        mapping = mapping_model.search(
            [("source_code_normalized", "=", "991006000")], limit=1
        )
        wizard.invalidate_recordset(["account_mapping_ids"])

        self.assertTrue(mapping)
        self.assertEqual(mapping.target_account_id.id, target_account.id)
        self.assertIn(mapping.id, wizard.account_mapping_ids.ids)
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["next"]["res_model"], wizard._name)
        self.assertEqual(action["params"]["next"]["res_id"], wizard.id)

    def test_action_load_default_mappings_refreshes_wizard_from_field_context(self):
        """La acción desde el formulario embebido usa el id del wizard en contexto."""
        mapping_model = self.env["aicia.account.importer.account.mapping"]
        wizard = self._make_wizard()
        target_account = self._ensure_account(
            "991007", "Cuenta destino wizard context", "income"
        )
        mapping_model.search(
            [("source_code_normalized", "=", "991007000")]
        ).unlink()

        with patch.object(
            type(mapping_model),
            "_get_default_mapping_values",
            autospec=True,
            return_value=[("991007000", "991007")],
        ):
            action = mapping_model.with_context(
                aicia_account_importer_wizard_id=wizard.id,
            ).action_load_default_mappings()

        mapping = mapping_model.search(
            [("source_code_normalized", "=", "991007000")], limit=1
        )
        wizard.invalidate_recordset(["account_mapping_ids"])

        self.assertTrue(mapping)
        self.assertEqual(mapping.target_account_id.id, target_account.id)
        self.assertIn(mapping.id, wizard.account_mapping_ids.ids)
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["next"]["res_model"], wizard._name)
        self.assertEqual(action["params"]["next"]["res_id"], wizard.id)

    def test_action_load_default_account_mappings_refreshes_wizard(self):
        """El botón del wizard carga el XML y refresca la lista embebida."""
        mapping_model = self.env["aicia.account.importer.account.mapping"]
        wizard = self._make_wizard()
        target_account = self._ensure_account(
            "991008", "Cuenta destino wizard button", "income"
        )
        mapping_model.search(
            [("source_code_normalized", "=", "991008000")]
        ).unlink()

        with patch.object(
            type(mapping_model),
            "_get_default_mapping_values",
            autospec=True,
            return_value=[("991008000", "991008")],
        ):
            action = wizard.action_load_default_account_mappings()

        mapping = mapping_model.search(
            [("source_code_normalized", "=", "991008000")], limit=1
        )
        wizard.invalidate_recordset(["account_mapping_ids"])

        self.assertTrue(mapping)
        self.assertEqual(mapping.target_account_id.id, target_account.id)
        self.assertIn(mapping.id, wizard.account_mapping_ids.ids)
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["next"]["res_model"], wizard._name)
        self.assertEqual(action["params"]["next"]["res_id"], wizard.id)

    def test_default_mapping_catalog_contains_requested_relations(self):
        """El catálogo XML incluye las relaciones pedidas para el legado."""
        default_mapping_model = self.env[
            "aicia.account.importer.account.mapping.default"
        ]
        expected_mappings = {
            "646000000": "625000",
            "650000000": "624000",
            "651000000": "650000",
            "660000000": "602000",
            "661000000": "628000",
            "662000100": "627000",
            "663000000": "627000",
            "664000000": "623000",
            "665000000": "629000",
            "666000000": "629000",
            "666000100": "629000",
            "667000000": "629000",
            "680000000": "682000",
            "681000000": "681000",
            "694000000": "699300",
            "700000000": "705000",
            "701000000": "705000",
            "702000000": "705000",
            "703000000": "705000",
            "704000000": "705000",
            "735000100": "705000",
            "736000000": "705000",
            "740000000": "705000",
            "747000400": "763300",
            "747000502": "763300",
            "747000504": "763300",
            "747000700": "763300",
            "750000000": "740000",
            "751000000": "740000",
            "751000100": "740000",
            "794000000": "795000",
            "794000100": "794000",
            "794100000": "778000",
        }

        default_mappings = default_mapping_model.search(
            [("source_code", "in", list(expected_mappings))]
        )
        mapping_by_source = {
            mapping.source_code: mapping.target_account_code
            for mapping in default_mappings
        }

        self.assertEqual(mapping_by_source, expected_mappings)

    # ── Tests: partners ───────────────────────────────────────────────────────

    def test_resolve_partner_found_by_exact_ref(self):
        """Partner con ref exacto 'C03604' → encontrado directamente."""
        partner = self.env["res.partner"].create({
            "name": "Cliente Legado Test",
            "ref": "C03604",
        })
        wizard = self._make_wizard()
        found = wizard._resolve_partner("C03604")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, partner.id)

    def test_resolve_partner_found_by_stripped_zeros(self):
        """Partner con ref sin ceros ('C3604') → encontrado por fallback."""
        partner = self.env["res.partner"].create({
            "name": "Cliente Sin Ceros",
            "ref": "C3604",
        })
        wizard = self._make_wizard()
        found = wizard._resolve_partner("C03604")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, partner.id)

    def test_resolve_partner_not_found_returns_none(self):
        """Partner inexistente → retorna None (no crea ni lanza error)."""
        wizard = self._make_wizard()
        result = wizard._resolve_partner("C99999")
        self.assertIsNone(result)

    def test_resolve_partner_empty_ref_returns_none(self):
        """ref_code vacío → retorna None inmediatamente."""
        wizard = self._make_wizard()
        result = wizard._resolve_partner("")
        self.assertIsNone(result)

    # ── Tests: importación completa ───────────────────────────────────────────

    def test_account_code_numeric_zfill(self):
        """Cuenta como entero en Excel (430003604 sin ceros) → zfill(9) correcto."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [1, 101, 20250115, None, "Test zfill", "DOC", 50000, True, False, "R"],
        ])
        # Cuenta_Contable como ENTERO (simula que Excel lo guardó sin ceros a la izq.)
        lineas = self._make_lineas_xlsx([
            [1, 1, 430003604, 0, 0, "Cliente zfill", 50000, "D"],   # int, no str
            [1, 2, 700000000, 0, 0, "Venta zfill",   50000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

        self.assertEqual(wizard.total_errors, 0)
        self.assertGreaterEqual(wizard.total_created + wizard.total_warnings, 1)

    def test_numero_apunte_float_no_dot_zero(self):
        """Numero_Apunte como float en Excel → se convierte a int (sin '.0' en ref)."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            # Numero_Apunte como float 102.0
            [2, 102.0, 20250115, None, "Test float ref", "DOC", 30000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [2, 1, "430000001", 0, 0, "Test", 30000, "D"],
            [2, 2, "700000000", 0, 0, "Test", 30000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

        # La ref debe ser "102", no "102.0"
        move = self._find_move_by_legacy_number("102")
        self.assertTrue(move, "El asiento debe tener ref='102', no '102.0'")

    def test_import_creates_journal_entry(self):
        """Importar un asiento cuadrado válido → crea el account.move."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")
        # Partner necesario: 430003604 → ref C03604. Sin él el asiento quedaría
        # como 'warning' (borrador) en lugar de 'created'.
        self.env["res.partner"].create({"name": "Cliente Test", "ref": "C03604"})

        apuntes = self._make_apuntes_xlsx([
            # id, num, fecha, intro, desc, doc, total, val, anu, clase
            [1, 100, 20250115, None, "Venta enero", "DOC-001",
             121000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            # id_apunte, id_linea, cuenta, id_dep, id_proy, desc, importe_cents, tipo
            [1, 1, "430003604", 0, 0, "Cliente Test", 121000, "D"],
            [1, 2, "700000000", 0, 0, "Venta enero", 121000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
        )
        wizard.action_import()

        self.assertEqual(wizard.state, "done")
        self.assertEqual(wizard.total_created, 1)
        self.assertEqual(wizard.total_errors, 0)
        move = self._find_move_by_legacy_number("100")
        self.assertTrue(move)

    def test_import_converts_cents_to_euros(self):
        """Importe 121000 céntimos → 1210,00 € en la línea del asiento."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [2, 200, 20250115, None, "Test euros", "DOC", 121000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [2, 1, "430000001", 0, 0, "Test", 121000, "D"],
            [2, 2, "700000000", 0, 0, "Test", 121000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

        move = self._find_move_by_legacy_number("200")
        self.assertTrue(move)
        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        self.assertAlmostEqual(debit_line[0].debit, 1210.0)

    def test_import_skips_duplicate(self):
        """Reimportar el mismo Numero_Apunte → se omite."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [3, 300, 20250115, None, "Duplicado", "DOC", 50000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [3, 1, "430000001", 0, 0, "Test", 50000, "D"],
            [3, 2, "700000000", 0, 0, "Test", 50000, "H"],
        ])
        for _ in range(2):
            w = self._make_wizard(
                file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
            )
            w.action_import()

        self.assertEqual(w.total_skipped, 1)
        self.assertEqual(w.total_created, 0)

    def test_import_unbalanced_entry_is_error(self):
        """Asiento que no cuadra → error en log."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [4, 400, 20250115, None, "Descuadrado", "DOC", 0, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [4, 1, "430000001", 0, 0, "Test", 100000, "D"],
            [4, 2, "700000000", 0, 0, "Test", 90000, "H"],  # diferencia: 100€
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

        self.assertEqual(wizard.total_errors, 1)
        self.assertEqual(wizard.total_created, 0)
        self.assertIn("no cuadra", wizard.import_log)

    def test_import_skips_anulados(self):
        """Asientos anulados se omiten cuando skip_anulados=True."""
        apuntes = self._make_apuntes_xlsx([
            [5, 500, 20250115, None, "Anulado", "DOC", 0, True, True, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [5, 1, "430000001", 0, 0, "Test", 10000, "D"],
            [5, 2, "700000000", 0, 0, "Test", 10000, "H"],
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
            [6, 1, "430000001", 0, 0, "Test", 10000, "D"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_import_no_lines_for_entry_is_error(self):
        """Asiento válido sin líneas en Lineas_Apunte → error en log."""
        apuntes = self._make_apuntes_xlsx([
            [7, 700, 20250115, None, "Sin líneas", "DOC", 0, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([])  # sin líneas

        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

        self.assertEqual(wizard.total_errors, 1)
        self.assertEqual(wizard.total_created, 0)

    def test_import_posted_state(self):
        """move_state='posted' → asiento confirmado tras la importación."""
        # Usamos 572 (banco) en el debe: no está en PARTNER_ACCOUNT_PREFIXES,
        # no dispara búsqueda de partner y permite confirmar el asiento.
        self._ensure_account("572000", "Bancos", "asset_cash")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [8, 800, 20250201, None, "Posted test", "DOC", 80000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [8, 1, "572000001", 0, 0, "Test", 80000, "D"],   # banco → sin partner
            [8, 2, "700000000", 0, 0, "Test", 80000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
            move_state="posted",
        )
        wizard.action_import()

        move = self._find_move_by_legacy_number("800")
        self.assertEqual(move.state, "posted")

    def test_import_puts_entry_name_in_ref_and_leaves_name_for_sequence(self):
        """El texto visible va a ref y el nombre Odoo queda en '/' para la serie."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")
        self.env["res.partner"].create({"name": "Cliente Test", "ref": "C03604"})

        apuntes = self._make_apuntes_xlsx([
            [30, 3000, 20250115, None, "Venta visible en referencia", "DOC-3000", 121000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [30, 1, "430003604", 0, 0, "Cliente Test", 121000, "D"],
            [30, 2, "700000000", 0, 0, "Venta visible en referencia", 121000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
        )
        wizard.action_import()

        move = self._find_move_by_legacy_number("3000")
        self.assertTrue(move)
        self.assertEqual(move.ref, "Venta visible en referencia")
        self.assertEqual(move.name, "/")

    def test_import_truncates_572_account_to_6_digits_in_move_lines(self):
        """La conversión del apunte usa 572XXX en la línea contable, nunca 572XXXXXX."""
        bank_account = self.env["account.account"].search(
            [
                ("code", "=like", "572___"),
                ("company_ids", "in", [self.env.company.id]),
            ],
            order="code desc",
            limit=1,
        )
        income_account = self.env["account.account"].search(
            [
                ("code", "=", "700000"),
                ("company_ids", "in", [self.env.company.id]),
            ],
            limit=1,
        )
        if not bank_account or not income_account:
            self.skipTest("No existen cuentas 572XXX/700000 disponibles en el plan contable")
        legacy_bank_code = f"{bank_account.code}123"

        apuntes = self._make_apuntes_xlsx([
            [81, 8100, 20250201, None, "Banco truncado", "DOC", 80000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [81, 1, legacy_bank_code, 0, 0, "Banco legado", 80000, "D"],
            [81, 2, "700000000", 0, 0, "Contrapartida", 80000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
        )

        wizard.action_import()

        move = self._find_move_by_legacy_number("8100")
        self.assertTrue(move)
        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        self.assertEqual(len(debit_line), 1)
        self.assertEqual(debit_line.account_id.id, bank_account.id)
        self.assertEqual(debit_line.account_id.code, bank_account.code)
        self.assertEqual(len(debit_line.account_id.code), 6)

    def test_import_log_html_generated(self):
        """Tras importar, import_log contiene HTML con el resumen."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [9, 900, 20250301, None, "Log test", "DOC", 30000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [9, 1, "430000001", 0, 0, "Test", 30000, "D"],
            [9, 2, "700000000", 0, 0, "Test", 30000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

        self.assertIn("Resumen", wizard.import_log)
        self.assertIn("creados", wizard.import_log)

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

    # ── Tests: creación automática de partners ────────────────────────────────

    def test_create_missing_partner_creates_customer(self):
        """create_missing_partners=True + cuenta cliente → crea partner con customer_rank=1."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [20, 2001, 20250115, None, "Cliente auto", "DOC", 50000, True, False, "R"],
        ])
        # "430099999" → last5="99999" → ref="C99999"
        lineas = self._make_lineas_xlsx([
            [20, 1, "430099999", 0, 0, "Cliente Automático", 50000, "D"],
            [20, 2, "700000000", 0, 0, "Venta auto",         50000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
            create_missing_partners=True,
        )
        wizard.action_import()

        self.assertEqual(wizard.total_errors, 0)
        # Partner creado con ref "C99999" y clasificado como cliente
        partner = self.env["res.partner"].search([("ref", "=", "C99999")], limit=1)
        self.assertTrue(partner, "Debe haberse creado el partner C99999")
        self.assertEqual(partner.customer_rank, 1)
        self.assertEqual(partner.supplier_rank, 0)

    def test_create_missing_partner_creates_supplier(self):
        """create_missing_partners=True + cuenta proveedor → crea partner con supplier_rank=1."""
        self._ensure_account("400000", "Proveedores", "liability_payable")
        self._ensure_account("600000", "Compras", "expense")

        apuntes = self._make_apuntes_xlsx([
            [21, 2101, 20250115, None, "Proveedor auto", "DOC", 30000, True, False, "R"],
        ])
        # "400088888" → last5="88888" → ref="P88888"
        lineas = self._make_lineas_xlsx([
            [21, 1, "600000000", 0, 0, "Compra auto",          30000, "D"],
            [21, 2, "400088888", 0, 0, "Proveedor Automático", 30000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
            create_missing_partners=True,
        )
        wizard.action_import()

        self.assertEqual(wizard.total_errors, 0)
        partner = self.env["res.partner"].search([("ref", "=", "P88888")], limit=1)
        self.assertTrue(partner, "Debe haberse creado el partner P88888")
        self.assertEqual(partner.supplier_rank, 1)
        self.assertEqual(partner.customer_rank, 0)

    def test_no_create_missing_partner_when_disabled(self):
        """create_missing_partners=False + partner no existe → warning, línea sin partner."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [22, 2201, 20250115, None, "Sin socio", "DOC", 40000, True, False, "R"],
        ])
        # "430077777" → last5="77777" → ref="C77777"
        lineas = self._make_lineas_xlsx([
            [22, 1, "430077777", 0, 0, "Sin Partner", 40000, "D"],
            [22, 2, "700000000", 0, 0, "Venta",       40000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
            create_missing_partners=False,
        )
        wizard.action_import()

        # No debe haberse creado ningún partner
        partner = self.env["res.partner"].search([("ref", "=", "C77777")], limit=1)
        self.assertFalse(partner, "No debe haberse creado ningún partner automático")
        # El asiento queda en borrador con warning
        self.assertEqual(wizard.total_warnings, 1)
        self.assertEqual(wizard.total_errors, 0)

    def test_create_missing_partner_idempotent(self):
        """Dos asientos con la misma cuenta de partner faltante → un solo partner creado."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [23, 2301, 20250201, None, "Asiento 1", "DOC", 10000, True, False, "R"],
            [24, 2401, 20250201, None, "Asiento 2", "DOC", 20000, True, False, "R"],
        ])
        # Ambas líneas referencian la misma cuenta → mismo ref "C66666"
        lineas = self._make_lineas_xlsx([
            [23, 1, "430066666", 0, 0, "Rep. cliente", 10000, "D"],
            [23, 2, "700000000", 0, 0, "Venta",        10000, "H"],
            [24, 1, "430066666", 0, 0, "Rep. cliente", 20000, "D"],
            [24, 2, "700000000", 0, 0, "Venta",        20000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes),
            file_lineas=self._enc(lineas),
            create_missing_partners=True,
        )
        wizard.action_import()

        partners = self.env["res.partner"].search([("ref", "=", "C66666")])
        self.assertEqual(len(partners), 1, "Solo debe existir un único partner C66666")
        self.assertEqual(wizard.total_errors, 0)

    def test_resolve_partner_found_by_6digit_ref(self):
        """Partner con ref de 6 dígitos 'C003604' → encontrado por fallback de _resolve_partner."""
        partner = self.env["res.partner"].create({
            "name": "Cliente 6 dígitos",
            "ref": "C003604",
        })
        wizard = self._make_wizard()
        # "C03604" → digits="03604" → digits_6="003604" → candidato "C003604"
        found = wizard._resolve_partner("C03604")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, partner.id)

    # ── Tests: Nº de asiento AICIA y proyecto analítico ──────────────────────

    def test_import_stores_numero_asiento_aicia(self):
        """El Numero_Apunte del legado se guarda en numero_asiento_aicia."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [40, 4000, 20250115, None, "Ref cruzada", "DOC", 30000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [40, 1, "430000001", 0, 0, "Test", 30000, "D"],
            [40, 2, "700000000", 0, 0, "Test", 30000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

        move = self._find_move_by_legacy_number("4000")
        self.assertTrue(move, "El asiento debe localizarse por numero_asiento_aicia")
        self.assertEqual(move.numero_asiento_aicia, "4000")

    def test_import_numero_asiento_aicia_is_idempotent_reference(self):
        """Reimportar no duplica: la referencia cruzada apunta a un único asiento."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")

        apuntes = self._make_apuntes_xlsx([
            [41, 4100, 20250115, None, "Dup ref", "DOC", 30000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [41, 1, "430000001", 0, 0, "Test", 30000, "D"],
            [41, 2, "700000000", 0, 0, "Test", 30000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()
        wizard2 = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard2.action_import()

        moves = self.env["account.move"].search(
            [("numero_asiento_aicia", "=", "4100")]
        )
        self.assertEqual(len(moves), 1, "No debe duplicarse el asiento reimportado")

    def test_import_project_zero_assigns_aicia_analytic(self):
        """ID_Proyecto=0 asigna la cuenta analítica [0] AICIA (0 no es 'sin proyecto')."""
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")
        analytic = self._ensure_analytic_account("0", "AICIA")

        apuntes = self._make_apuntes_xlsx([
            [42, 4200, 20250115, None, "Proyecto 0", "DOC", 30000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [42, 1, "430000001", 0, 0, "Test", 30000, "D"],
            [42, 2, "700000000", 0, 0, "Test", 30000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

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
        self._ensure_account("430000", "Clientes", "asset_receivable")
        self._ensure_account("700000", "Ventas", "income")
        self._ensure_analytic_account("0", "AICIA")

        apuntes = self._make_apuntes_xlsx([
            [43, 4300, 20250115, None, "Sin proyecto", "DOC", 30000, True, False, "R"],
        ])
        lineas = self._make_lineas_xlsx([
            [43, 1, "430000001", 0, None, "Test", 30000, "D"],
            [43, 2, "700000000", 0, None, "Test", 30000, "H"],
        ])
        wizard = self._make_wizard(
            file_apuntes=self._enc(apuntes), file_lineas=self._enc(lineas)
        )
        wizard.action_import()

        move = self._find_move_by_legacy_number("4300")
        self.assertTrue(move)
        for line in move.line_ids:
            self.assertFalse(
                line.analytic_distribution,
                "Sin ID_Proyecto no debe asignarse distribución analítica",
            )
