# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

"""Normalización del NIF de AICIAWIN: el correlativo " n" no es parte del NIF."""

from odoo.tests.common import TransactionCase

from ..wizard.aicia_importer_wizard import split_nif_suffix


class TestSplitNifSuffix(TransactionCase):
    def test_suffix_with_space_is_removed(self):
        self.assertEqual(split_nif_suffix("A41990490 1"), ("A41990490", "1"))
        self.assertEqual(split_nif_suffix("17477748W 2"), ("17477748W", "2"))

    def test_double_space_and_lowercase(self):
        self.assertEqual(split_nif_suffix("a9999999a  9"), ("A9999999A", "9"))

    def test_two_digit_suffix(self):
        self.assertEqual(split_nif_suffix("A9999999A 12"), ("A9999999A", "12"))

    def test_nif_without_suffix_is_kept(self):
        self.assertEqual(split_nif_suffix("A41990490"), ("A41990490", ""))
        self.assertEqual(split_nif_suffix("12345678Z"), ("12345678Z", ""))

    def test_foreign_vat_is_not_touched(self):
        self.assertEqual(split_nif_suffix("GB 123456789"), ("GB 123456789", ""))
        self.assertEqual(split_nif_suffix("FR12345678901"), ("FR12345678901", ""))

    def test_empty(self):
        self.assertEqual(split_nif_suffix(None), ("", ""))
        self.assertEqual(split_nif_suffix("  "), ("", ""))


class TestPartnerRowNif(TransactionCase):
    def _import(self, is_supplier, row):
        wizard = self.env["aicia.importer.wizard"].create({})
        if is_supplier:
            headers = ("ID_Proveedor", "Nombre", "CIF", "Cuenta_Contable")
        else:
            headers = ("ID_Cliente", "Nombre", "NIF", "Cuenta_Contable")
        return wizard._process_partner_row(row, headers, is_supplier=is_supplier)

    def test_customer_alias_keeps_code_but_nif_loses_suffix(self):
        self._import(False, (990001, "Cliente principal", "A41990490", "430990001"))
        self._import(False, (990002, "Cliente alias", "A41990490 1", "430990001"))
        partners = self.env["res.partner"].search(
            [("codigo_cliente", "in", ["C990001", "C990002"])]
        )
        self.assertEqual(len(partners), 2)
        self.assertEqual(set(partners.mapped("vat")), {"ESA41990490"})
        self.assertEqual(
            set(partners.mapped("codigo_cliente")), {"C990001", "C990002"}
        )

    def test_supplier_suffix_removed(self):
        self._import(True, (990003, "Proveedor alias", "B12345678 3", "400990003"))
        partner = self.env["res.partner"].search([("codigo_proveedor", "=", "C990003")])
        self.assertEqual(partner.vat, "ESB12345678")
