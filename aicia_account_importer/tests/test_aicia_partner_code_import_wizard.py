# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

"""Tests del asistente que carga los códigos AICIA desde la hoja Personal.

Cubre: emparejamiento por código de empleado, NIF y nombre único; filas sin
coincidencia o ambiguas (no se asignan); varios códigos para una misma persona;
códigos ya existentes; simulación sin escritura.
"""

from base64 import b64encode
from io import BytesIO

from odoo.tests.common import TransactionCase


class TestAiciaPartnerCodeImportWizard(TransactionCase):
    def _xlsx(self, rows):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl no instalado")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["ID_Personal", "Nombre", "NIF", "Telefono"])
        for row in rows:
            ws.append(row)
        buf = BytesIO()
        wb.save(buf)
        return b64encode(buf.getvalue()).decode()

    def _wizard(self, rows):
        return self.env["aicia.partner.code.import.wizard"].create(
            {"file_personal": self._xlsx(rows)}
        )

    def _load(self, rows):
        wizard = self._wizard(rows)
        wizard.action_load()
        return wizard

    def _codes(self, partner):
        return set(
            partner.aicia_code_ids.filtered(
                lambda c: c.partner_type == "employee"
            ).mapped("code")
        )

    def _partner(self, name, vat=None):
        return self.env["res.partner"].create(
            {"name": name, "vat": vat, "is_company": False}
        )

    def _employee(self, name, code, nif, vat=None):
        """Empleado con codigo_empleado y NIF; omite el test si no hay hr."""
        Employee = self.env.get("hr.employee")
        if Employee is None or "codigo_empleado" not in Employee._fields:
            self.skipTest("hr / aicia_extra_fields no instalados")
        contact = self._partner(name, vat)
        employee = Employee.create(
            {
                "name": name,
                "codigo_empleado": code,
                "identification_id": nif,
                "work_contact_id": contact.id,
            }
        )
        return employee, contact

    # ── Emparejamiento sin hr (NIF de contacto y nombre) ─────────────────────

    def test_match_by_contact_nif(self):
        partner = self._partner("PEREZ TEST, ANA", vat="12345678Z")
        wizard = self._load([[7001, "Nombre distinto", "12345678Z", None]])
        self.assertEqual(self._codes(partner), {"7001"})
        self.assertEqual(wizard.total_created, 1)

    def test_match_by_unique_name_ignores_case_accents_and_punctuation(self):
        partner = self._partner("MUÑOZ RUIZ, JOSÉ")
        self._load([[7002, "muñoz ruiz jose", "", None]])
        self.assertEqual(self._codes(partner), {"7002"})

    def test_nif_has_priority_over_name(self):
        by_nif = self._partner("Otro nombre", vat="11111111H")
        self._partner("GOMEZ LUNA, PEPE")
        self._load([[7003, "GOMEZ LUNA, PEPE", "11111111H", None]])
        self.assertEqual(self._codes(by_nif), {"7003"})

    def test_ambiguous_name_is_not_assigned(self):
        first = self._partner("REPETIDO TEST, LUIS")
        second = self._partner("Repetido Test Luis")
        wizard = self._load([[7004, "REPETIDO TEST LUIS", "", None]])
        self.assertFalse(self._codes(first) | self._codes(second))
        self.assertEqual(wizard.total_created, 0)
        self.assertEqual(wizard.total_unassigned, 1)
        self.assertIn("H —", wizard.result_log)

    def test_no_match_is_not_assigned_and_does_not_create_partners(self):
        before = self.env["res.partner"].search_count([])
        wizard = self._load([[7005, "NADIE EXISTE, ASI", "99999999R", None]])
        self.assertEqual(self.env["res.partner"].search_count([]), before)
        self.assertEqual(wizard.total_created, 0)
        self.assertEqual(wizard.total_unassigned, 1)
        self.assertIn("G —", wizard.result_log)

    def test_company_names_do_not_match(self):
        self.env["res.partner"].create(
            {"name": "EMPRESA TEST SL", "is_company": True}
        )
        wizard = self._load([[7006, "EMPRESA TEST SL", "", None]])
        self.assertEqual(wizard.total_unassigned, 1)

    def test_person_with_several_ids_gets_several_codes(self):
        partner = self._partner("DOS CODIGOS, MARIA", vat="22222222J")
        self._load(
            [
                [7010, "DOS CODIGOS, MARIA", "22222222J", None],
                [7011, "DOS CODIGOS, MARIA", "22222222J", None],
            ]
        )
        self.assertEqual(self._codes(partner), {"7010", "7011"})

    def test_ids_as_float_and_leading_spaces_in_file(self):
        partner = self._partner("FLOTANTE, UNO", vat="33333333P")
        self._load([[7012.0, "FLOTANTE, UNO", " 33333333P ", None]])
        self.assertEqual(self._codes(partner), {"7012"})

    # ── Códigos ya existentes, simulación ────────────────────────────────────

    def test_existing_code_of_same_partner_is_counted_not_duplicated(self):
        partner = self._partner("YA TIENE, CODIGO", vat="44444444A")
        self._load([[7020, "YA TIENE, CODIGO", "44444444A", None]])
        wizard = self._load([[7020, "YA TIENE, CODIGO", "44444444A", None]])
        self.assertEqual(self._codes(partner), {"7020"})
        self.assertEqual(wizard.total_created, 0)
        self.assertEqual(wizard.total_existing, 1)

    def test_code_already_assigned_to_another_partner_is_not_changed(self):
        owner = self._partner("DUENO, ORIGINAL")
        owner.write(
            {"aicia_code_ids": [(0, 0, {"partner_type": "employee", "code": "7021"})]}
        )
        other = self._partner("OTRO, DISTINTO", vat="55555555K")
        wizard = self._load([[7021, "OTRO, DISTINTO", "55555555K", None]])
        self.assertEqual(self._codes(owner), {"7021"})
        self.assertFalse(self._codes(other))
        self.assertEqual(wizard.total_conflicts, 1)
        self.assertIn("DUENO", wizard.result_log)

    def test_codes_of_other_types_do_not_block_employee_codes(self):
        partner = self._partner("PROVEEDOR Y EMPLEADO", vat="66666666Q")
        supplier = self._partner("UN PROVEEDOR")
        supplier.write(
            {"aicia_code_ids": [(0, 0, {"partner_type": "supplier", "code": "7022"})]}
        )
        self._load([[7022, "PROVEEDOR Y EMPLEADO", "66666666Q", None]])
        self.assertEqual(self._codes(partner), {"7022"})

    def test_simulation_creates_nothing_but_reports(self):
        partner = self._partner("SIMULADO, TEST", vat="77777777B")
        wizard = self._wizard([[7030, "SIMULADO, TEST", "77777777B", None]])
        wizard.action_simulate()
        self.assertFalse(partner.aicia_code_ids)
        self.assertTrue(wizard.simulated)
        self.assertEqual(wizard.total_created, 1)
        self.assertIn("SIMULACIÓN", wizard.result_log)

    def test_missing_required_column_raises(self):
        import openpyxl

        wb = openpyxl.Workbook()
        wb.active.append(["Otra", "Cosa"])
        buf = BytesIO()
        wb.save(buf)
        wizard = self.env["aicia.partner.code.import.wizard"].create(
            {"file_personal": b64encode(buf.getvalue()).decode()}
        )
        with self.assertRaises(Exception) as ctx:
            wizard.action_load()
        self.assertIn("ID_Personal", str(ctx.exception))

    def test_no_file_raises(self):
        wizard = self.env["aicia.partner.code.import.wizard"].create({})
        with self.assertRaises(Exception):
            wizard.action_load()

    # ── Emparejamiento con empleados (necesita hr + aicia_extra_fields) ──────

    def test_employee_code_and_nif_match(self):
        _employee, contact = self._employee("EMPLEADO A, UNO", "E7040", "88888888C")
        wizard = self._load([[7040, "EMPLEADO A, UNO", "88888888C", None]])
        self.assertEqual(self._codes(contact), {"7040"})
        self.assertIn("1 &nbsp;A —", wizard.result_log.replace("    ", " "))

    def test_employee_code_matches_even_if_nif_and_name_differ(self):
        """Conflicto (C): se asigna al empleado que tiene ese código."""
        _employee, contact = self._employee("EMPLEADO C, DOS", "E7041", "99999999R")
        wizard = self._load([[7041, "OTRA PERSONA, DISTINTA", "00000000T", None]])
        self.assertEqual(self._codes(contact), {"7041"})
        self.assertIn("C —", wizard.result_log)

    def test_same_person_with_another_code_gets_a_second_code(self):
        """D: el empleado ya tiene otro código; por NIF recibe el nuevo además."""
        _employee, contact = self._employee("EMPLEADO D, TRES", "E7042", "10101010J")
        self._load(
            [
                [7042, "EMPLEADO D, TRES", "10101010J", None],
                [7043, "EMPLEADO D, TRES", "10101010J", None],
            ]
        )
        self.assertEqual(self._codes(contact), {"7042", "7043"})

    def test_employee_found_by_name_only_gets_the_code(self):
        _employee, contact = self._employee("EMPLEADO F, CUATRO", "E7044", "20202020W")
        self._load([[7045, "EMPLEADO F, CUATRO", "", None]])
        self.assertEqual(self._codes(contact), {"7045"})


class TestAiciaSupplierCustomerCodes(TransactionCase):
    """Copia de codigo_proveedor / codigo_cliente a la tabla de códigos AICIA."""

    def setUp(self):
        super().setUp()
        if "codigo_proveedor" not in self.env["res.partner"]._fields:
            self.skipTest("aicia_extra_fields no instalado")
        self.Code = self.env["aicia.partner.code"]

    def _partner(self, name, **vals):
        return self.env["res.partner"].create(dict({"name": name}, **vals))

    def _code(self, partner, partner_type):
        return partner.aicia_code_ids.filtered(lambda c: c.partner_type == partner_type)

    def test_supplier_and_customer_numbers_are_copied_with_their_type(self):
        proveedor = self._partner("Proveedor test", codigo_proveedor="C7771")
        cliente = self._partner("Cliente test", codigo_cliente="C7772")
        self.Code.load_supplier_customer_codes()
        self.assertEqual(self._code(proveedor, "supplier").code, "7771")
        self.assertEqual(self._code(cliente, "customer").code, "7772")
        self.assertFalse(self._code(proveedor, "customer"))

    def test_load_is_repeatable_and_does_not_duplicate(self):
        proveedor = self._partner("Proveedor test", codigo_proveedor="C7773")
        self.Code.load_supplier_customer_codes()
        stats = self.Code.load_supplier_customer_codes()
        self.assertEqual(len(self._code(proveedor, "supplier")), 1)
        self.assertEqual(stats["created"], 0)
        self.assertGreaterEqual(stats["existing"], 1)

    def test_codes_above_9999_are_loaded_too(self):
        """Los clientes de la cuenta general tienen códigos de 5 cifras y se buscan por código."""
        cliente = self._partner("Cliente largo", codigo_cliente="C12345")
        self.Code.load_supplier_customer_codes()
        self.assertEqual(self._code(cliente, "customer").code, "12345")

    def test_numbers_repeated_in_two_partners_are_skipped(self):
        uno = self._partner("Proveedor uno", codigo_proveedor="C7774")
        dos = self._partner("Proveedor dos", codigo_proveedor="P7774")
        stats = self.Code.load_supplier_customer_codes()
        self.assertFalse(uno.aicia_code_ids | dos.aicia_code_ids)
        self.assertGreaterEqual(stats["ambiguous"], 1)

    def test_existing_code_of_another_partner_is_not_changed(self):
        owner = self._partner("Dueño", aicia_code_ids=[
            (0, 0, {"partner_type": "supplier", "code": "7775"})])
        other = self._partner("Otro", codigo_proveedor="C7775")
        stats = self.Code.load_supplier_customer_codes()
        self.assertTrue(self._code(owner, "supplier"))
        self.assertFalse(other.aicia_code_ids)
        self.assertGreaterEqual(stats["conflicts"], 1)

    def test_same_number_for_supplier_and_customer_is_allowed(self):
        ambos = self._partner("Ambos", codigo_proveedor="C7776", codigo_cliente="C7776")
        self.Code.load_supplier_customer_codes()
        self.assertEqual(set(ambos.aicia_code_ids.mapped("partner_type")),
                         {"supplier", "customer"})

    def test_load_never_removes_codes_already_in_the_table(self):
        """Tras fusionar, los códigos de los alias viven en el contacto final."""
        final = self._partner("Final", codigo_cliente="C7781", aicia_code_ids=[
            (0, 0, {"partner_type": "customer", "code": "7781"}),
            (0, 0, {"partner_type": "customer", "code": "7782"})])
        self.Code.load_supplier_customer_codes()
        self.assertEqual(sorted(self._code(final, "customer").mapped("code")), ["7781", "7782"])

    def test_partner_by_code_and_partners_by_codes(self):
        cliente = self._partner("Cliente", codigo_cliente="C7791")
        self.Code.load_supplier_customer_codes()
        self.assertEqual(self.Code._partner_by_code("customer", "07791"), cliente)
        self.assertFalse(self.Code._partner_by_code("supplier", "7791"))
        self.assertEqual(self.Code._partners_by_codes("customer", ["7791", "7799"]), {"7791": cliente})


class TestMergePartnersByNif(TransactionCase):
    """Un solo contacto por NIF, con todos los códigos AICIA."""

    def setUp(self):
        super().setUp()
        if "codigo_cliente" not in self.env["res.partner"]._fields:
            self.skipTest("aicia_extra_fields no instalado")
        self.Code = self.env["aicia.partner.code"]
        self.ctx = {"import_file": True, "check_vies": False}

    def _partner(self, name, vat, **vals):
        return self.env["res.partner"].with_context(**self.ctx).create(
            dict({"name": name, "vat": vat, "street": "Calle %s 1" % name, "city": "Sevilla"}, **vals)
        )

    def test_duplicates_are_merged_into_the_oldest_code_and_keep_every_code(self):
        a = self._partner("Cliente A", "ESA81234561", codigo_cliente="C7001", customer_rank=1)
        b = self._partner("Cliente A nuevo nombre", "ESA81234561", codigo_cliente="C7010", customer_rank=1)
        c = self._partner("Cliente A otra dirección", "ESA81234561", codigo_cliente="C7020", customer_rank=1)
        stats = self.Code.merge_partners_by_nif(dry_run=False, partner_ids=(a | b | c).ids)
        self.assertEqual(stats["errors"], [])
        self.assertTrue(a.exists())
        self.assertFalse(b.exists() or c.exists())
        codes = a.aicia_code_ids.filtered(lambda r: r.partner_type == "customer")
        self.assertEqual(sorted(codes.mapped("code")), ["7001", "7010", "7020"])
        names = {r.code: r.legacy_name for r in codes}
        self.assertIn("nuevo nombre", names["7010"])
        self.assertIn("otra dirección", names["7020"])
        self.assertIn("Calle", codes.filtered(lambda r: r.code == "7010").legacy_address)

    def test_dry_run_changes_nothing(self):
        a = self._partner("Uno", "ESB81234562", codigo_proveedor="C7101", supplier_rank=1)
        b = self._partner("Dos", "ESB81234562", codigo_proveedor="C7102", supplier_rank=1)
        stats = self.Code.merge_partners_by_nif(dry_run=True, partner_ids=(a | b).ids)
        self.assertEqual((stats["groups"], stats["merged"]), (1, 1))
        self.assertTrue(a.exists() and b.exists())

    def test_customer_and_supplier_with_same_nif_become_one_partner_with_both_ranks(self):
        cli = self._partner("Entidad", "ESC81234563", codigo_cliente="C7201", customer_rank=1)
        prov = self._partner("Entidad proveedor", "ESC81234563", codigo_proveedor="C7301", supplier_rank=1)
        self.Code.merge_partners_by_nif(dry_run=False, partner_ids=(cli | prov).ids)
        survivors = (cli | prov).exists()
        self.assertEqual(len(survivors), 1)
        self.assertGreaterEqual(survivors.customer_rank, 1)
        self.assertGreaterEqual(survivors.supplier_rank, 1)
        self.assertEqual(
            set(survivors.aicia_code_ids.mapped("partner_type")), {"customer", "supplier"}
        )

    def test_different_nifs_are_not_merged(self):
        a = self._partner("Uno", "ESD81234564", codigo_cliente="C7401")
        b = self._partner("Dos", "ESD81234565", codigo_cliente="C7402")
        self.Code.merge_partners_by_nif(dry_run=False, partner_ids=(a | b).ids)
        self.assertTrue(a.exists() and b.exists())

    def test_placeholder_nif_is_never_merged(self):
        """99999999, 00000000… son NIF de relleno: no identifican a la misma entidad."""
        a = self._partner("Uno", "ESX9999999J", codigo_cliente="C7511")
        b = self._partner("Dos", "ESX9999999J", codigo_cliente="C7512")
        c = self._partner("Tres", "ES00000000T", codigo_cliente="C7513")
        d = self._partner("Cuatro", "ES00000000T", codigo_cliente="C7514")
        stats = self.Code.merge_partners_by_nif(dry_run=False, partner_ids=(a | b | c | d).ids)
        self.assertEqual(stats["groups"], 0)
        self.assertTrue((a | b | c | d).exists() == (a | b | c | d))

    def test_real_nif_helper(self):
        from ..models.aicia_partner_code import real_nif

        self.assertEqual(real_nif("ESA41990490"), "A41990490")
        self.assertEqual(real_nif("12345678z"), "12345678Z")
        self.assertIsNone(real_nif("X9999999J"))
        self.assertIsNone(real_nif("ES00000000T"))
        self.assertIsNone(real_nif("FR12345678901"))
        self.assertIsNone(real_nif(""))

    def test_foreign_or_invalid_vat_is_not_merged(self):
        a = self._partner("Uno", "FR12345678901", codigo_cliente="C7501")
        b = self._partner("Dos", "FR12345678901", codigo_cliente="C7502")
        self.Code.merge_partners_by_nif(dry_run=False, partner_ids=(a | b).ids)
        self.assertTrue(a.exists() and b.exists())

    def test_partner_linked_to_a_user_is_never_merged(self):
        user_partner = self.env.user.partner_id
        user_partner.with_context(**self.ctx).write({"vat": "ESE81234566", "codigo_cliente": "C7601"})
        other = self._partner("Duplicado", "ESE81234566", codigo_cliente="C7602")
        stats = self.Code.merge_partners_by_nif(dry_run=False, partner_ids=(user_partner | other).ids)
        self.assertIn("E81234566", stats["skipped"])
        self.assertTrue(user_partner.exists() and other.exists())

    def test_journal_items_move_to_the_surviving_partner(self):
        a = self._partner("Cliente A", "ESF81234567", codigo_cliente="C7701", customer_rank=1)
        b = self._partner("Cliente B", "ESF81234567", codigo_cliente="C7702", customer_rank=1)
        accounts = [
            self.env["account.account"].create({
                "code": code, "name": "Test " + code, "account_type": "asset_current",
                "company_ids": [(4, self.env.company.id)],
            }) for code in ("699971", "699972")
        ]
        journal = self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.env.company.id)], limit=1
        ) or self.env["account.journal"].create(
            {"name": "AICIA test", "code": "AIT", "type": "general", "company_id": self.env.company.id}
        )
        move = self.env["account.move"].create({
            "journal_id": journal.id,
            "date": "2025-01-15",
            "line_ids": [
                (0, 0, {"account_id": accounts[0].id, "debit": 10, "partner_id": b.id}),
                (0, 0, {"account_id": accounts[1].id, "credit": 10}),
            ],
        })
        self.Code.merge_partners_by_nif(dry_run=False, partner_ids=(a | b).ids)
        self.assertEqual(move.line_ids.filtered(lambda l: l.debit).partner_id, a)
        self.assertEqual(self.Code._partner_by_code("customer", "7702"), a)
