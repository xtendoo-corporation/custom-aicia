# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

"""Normalización del NIF de AICIAWIN: el correlativo " n" no es parte del NIF."""

from unittest.mock import patch

from odoo.tests.common import TransactionCase

from ..wizard.aicia_importer_wizard import split_nif_suffix


class TestSplitNifSuffix(TransactionCase):
    def test_suffix_with_space_is_removed(self):
        self.assertEqual(split_nif_suffix("A99990011 1"), ("A99990011", "1"))
        self.assertEqual(split_nif_suffix("17477748W 2"), ("17477748W", "2"))

    def test_double_space_and_lowercase(self):
        self.assertEqual(split_nif_suffix("a9999999a  9"), ("A9999999A", "9"))

    def test_two_digit_suffix(self):
        self.assertEqual(split_nif_suffix("A9999999A 12"), ("A9999999A", "12"))

    def test_nif_without_suffix_is_kept(self):
        self.assertEqual(split_nif_suffix("A99990011"), ("A99990011", ""))
        self.assertEqual(split_nif_suffix("12345678Z"), ("12345678Z", ""))

    def test_foreign_vat_is_not_touched(self):
        self.assertEqual(split_nif_suffix("GB 123456789"), ("GB 123456789", ""))
        self.assertEqual(split_nif_suffix("FR12345678901"), ("FR12345678901", ""))

    def test_empty(self):
        self.assertEqual(split_nif_suffix(None), ("", ""))
        self.assertEqual(split_nif_suffix("  "), ("", ""))


class TestPartnerRowNif(TransactionCase):
    def _wizard(self, **kw):
        return self.env["aicia.importer.wizard"].create(kw)

    def _import(self, is_supplier, row, wizard=None):
        wizard = wizard or self._wizard()
        if is_supplier:
            headers = ("ID_Proveedor", "Nombre", "CIF", "Cuenta_Contable", "Direccion", "Cod_Postal", "Localidad")
        else:
            headers = ("ID_Cliente", "Nombre", "NIF", "Cuenta_Contable", "Direccion", "Cod_Postal", "Localidad")
        return wizard._process_partner_row(row, headers, is_supplier=is_supplier)

    def _by_code(self, partner_type, code):
        return self.env["aicia.partner.code"]._partner_by_code(partner_type, code)

    def test_supplier_suffix_removed(self):
        self._import(True, (990003, "Proveedor", "B99990017 3", "400990003", "C/ Uno 1", "41001", "Sevilla"))
        self.assertEqual(self._by_code("supplier", 990003).vat, "ESB99990017")

    def test_new_partner_gets_its_aicia_code_with_name_and_address(self):
        self.assertEqual(
            self._import(False, (990010, "Cliente nuevo", "A99990015", "430990010", "C/ Uno 1", "41001", "Sevilla")),
            "created",
        )
        partner = self._by_code("customer", 990010)
        code = partner.aicia_code_ids
        self.assertEqual(code.partner_type, "customer")
        self.assertEqual(code.legacy_name, "Cliente nuevo")
        self.assertIn("C/ Uno 1", code.legacy_address)

    def test_same_nif_with_another_code_adds_the_code_instead_of_creating_a_partner(self):
        self._import(False, (990011, "Cliente principal", "A99990011", "430990011", "C/ Uno 1", "41001", "Sevilla"))
        result = self._import(False, (990012, "Cliente nueva razón social", "A99990011 1", "430990011", "C/ Dos 2", "41002", "Sevilla"))
        self.assertEqual(result, "linked")
        main = self._by_code("customer", 990011)
        self.assertEqual(self._by_code("customer", 990012), main)
        self.assertEqual(main.name, "Cliente principal")  # la ficha no se pisa
        codes = main.aicia_code_ids
        self.assertEqual(sorted(codes.mapped("code")), ["990011", "990012"])
        self.assertEqual(codes.filtered(lambda c: c.code == "990012").legacy_name, "Cliente nueva razón social")
        self.assertEqual(self.env["res.partner"].search_count([("vat", "=", "ESA99990011")]), 1)

    def test_supplier_and_customer_with_same_nif_share_one_partner(self):
        self._import(True, (990013, "Proveedor", "B99990016", "400990013", "C/ Uno 1", "41001", "Sevilla"))
        self.assertEqual(self._import(False, (990014, "Cliente", "B99990016", "430990014", "C/ Uno 1", "41001", "Sevilla")), "linked")
        partner = self._by_code("supplier", 990013)
        self.assertEqual(self._by_code("customer", 990014), partner)
        self.assertTrue(partner.supplier_rank and partner.customer_rank)

    def test_placeholder_nif_is_never_linked(self):
        self._import(False, (990030, "Uno", "X9999999J", "430990030", "", "", ""))
        self.assertEqual(self._import(False, (990031, "Dos", "X9999999J", "430990031", "", "", "")), "created")
        self.assertNotEqual(self._by_code("customer", 990030), self._by_code("customer", 990031))

    def test_invalid_or_foreign_nif_is_never_linked(self):
        self._import(False, (990015, "Uno", "FR12345678901", "430990015", "", "", ""))
        self.assertEqual(self._import(False, (990016, "Dos", "FR12345678901", "430990016", "", "", "")), "created")
        self.assertNotEqual(self._by_code("customer", 990015), self._by_code("customer", 990016))

    def test_reimport_finds_the_partner_by_code_and_only_the_principal_updates_the_file(self):
        self._import(False, (990017, "Principal", "A99990012", "430990017", "", "", ""))
        self._import(False, (990018, "Alias", "A99990012 1", "430990017", "", "", ""))
        wizard = self._wizard(update_existing=True)
        self.assertEqual(self._import(False, (990018, "Alias cambiado", "A99990012 1", "430990017", "", "", ""), wizard), "updated")
        main = self._by_code("customer", 990017)
        self.assertEqual(main.name, "Principal")  # un alias no pisa la ficha
        self.assertEqual(
            main.aicia_code_ids.filtered(lambda c: c.code == "990018").legacy_name, "Alias cambiado"
        )
        self.assertEqual(self._import(False, (990017, "Principal cambiado", "A99990012", "430990017", "", "", ""), wizard), "updated")
        self.assertEqual(main.name, "Principal cambiado")

    def test_existing_partner_found_by_old_codigo_cliente_gets_its_code(self):
        partner = self.env["res.partner"].create({"name": "Viejo", "codigo_cliente": "C990019"})
        self.assertEqual(self._import(False, (990019, "Viejo", "A99990013", "430990019", "", "", "")), "skipped")
        self.assertEqual(self._by_code("customer", 990019), partner)

    def test_rows_are_processed_by_ascending_id_so_the_oldest_code_is_the_principal(self):
        import base64
        import io
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["ID_Cliente", "Nombre", "NIF", "Cuenta_Contable"])
        ws.append([990021, "Alias", "A99990014 1", "430990020"])
        ws.append([990020, "Principal", "A99990014", "430990020"])
        buf = io.BytesIO()
        wb.save(buf)
        with patch.object(self.env.cr, "commit"):  # el importador confirma por lotes
            result = self._wizard()._import_file(base64.b64encode(buf.getvalue()), is_supplier=False)
        self.assertEqual((result["created"], result["linked"], result["errors"]), (1, 1, 0))
        self.assertEqual(self._by_code("customer", 990021).name, "Principal")
