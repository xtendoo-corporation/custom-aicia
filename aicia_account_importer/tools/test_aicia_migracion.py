# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Tests de aicia_migracion.py (sin Odoo): python3 -m unittest test_aicia_migracion -v"""
import collections
import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "aicia_migracion", os.path.join(os.path.dirname(os.path.abspath(__file__)), "aicia_migracion.py")
)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def apunte(id_, num, fecha="20250115", total="1000", validado="True", anulado="False"):
    return {"ID_Apunte": id_, "Numero_Apunte": num, "Fecha_Contable": fecha, "Importe_Total": total,
            "Validado": validado, "Anulado": anulado}


def linea(id_, cuenta, importe, tipo):
    return {"ID_Apunte": id_, "Cuenta_Contable": cuenta, "Importe": importe, "Tipo_Contable": tipo}


def owners(**kw):
    o = {"S": collections.defaultdict(list), "C": collections.defaultdict(list)}
    for kind, accounts in kw.items():
        for acc, ids in accounts.items():
            o[kind.upper()][acc] = ids
    return o


class TestAsientoSocio(unittest.TestCase):
    def test_factura_gives_partner_for_its_asiento(self):
        apuntes = [apunte("1", "10", total="1210")]
        prov = [{"Año_Apunte": "2025", "ID_Apunte": "1", "ID_Proveedor": "77", "Fecha_Factura": "20250115",
                 "Base": "1000", "Cuota": "210"}]
        rows, stats = tool.build_asiento_socio(apuntes, prov, [], 2025)
        self.assertEqual(rows, [(10, "proveedor", 77)])
        self.assertEqual(stats["importe coincide"], 1)
        self.assertEqual(stats["fecha coincide"], 1)

    def test_other_year_and_missing_apunte_are_ignored(self):
        cli = [
            {"Año_Apunte": "2024", "ID_Apunte": "1", "ID_Cliente": "5", "Fecha_Factura": "20240101", "Base": "1", "Cuota": "0"},
            {"Año_Apunte": "2025", "ID_Apunte": "99", "ID_Cliente": "6", "Fecha_Factura": "20250101", "Base": "1", "Cuota": "0"},
        ]
        rows, stats = tool.build_asiento_socio([apunte("1", "10")], [], cli, 2025)
        self.assertEqual(rows, [])
        self.assertEqual(stats["factura cliente sin apunte"], 1)


class TestExpected(unittest.TestCase):
    def setUp(self):
        self.apuntes = [apunte("1", "10")]

    def exp(self, lineas, facturas=None, own=None):
        return tool.expected_lines(self.apuntes, lineas, facturas or {}, own or owners())["10"]

    def test_target_account_is_five_digits_plus_zero_or_full_for_special(self):
        self.assertEqual(tool.target_account("430003604"), "430000")
        self.assertEqual(tool.target_account("401000200"), "401000200")

    def test_factura_beats_no_partner_rule(self):
        line = self.exp([linea("1", "430000000", "500", "H")], {("10", "C"): 12345})[0]
        self.assertEqual(line[3], ("C", 12345))
        self.assertEqual(line[4], "por factura")

    def test_no_partner_rule_without_factura(self):
        self.assertIsNone(self.exp([linea("1", "430000000", "500", "H")])[0][3])

    def test_shared_account_goes_to_owner_and_is_inferred(self):
        line = self.exp([linea("1", "430000185", "500", "H")], own=owners(c={"430000185": [185, 1262]}))[0]
        self.assertEqual((line[3], line[4]), (("C", 185), "cuenta compartida: titular"))

    def test_single_partner_account_uses_that_partner(self):
        line = self.exp([linea("1", "400000001", "500", "D")], own=owners(s={"400000001": [9]}))[0]
        self.assertEqual((line[3], line[4]), (("S", 9), "cuenta de un solo socio"))

    def test_credit_and_debit_in_cents(self):
        d, c = self.exp([linea("1", "572000001", "250", "D"), linea("1", "572000001", "250", "H")])
        self.assertEqual((d[1], d[2], c[1], c[2]), (250, 0, 0, 250))

    def test_annulled_or_invalid_apuntes_are_skipped(self):
        res = tool.expected_lines([apunte("1", "10", anulado="True")], [linea("1", "572000001", "1", "D")], {}, owners())
        self.assertEqual(len(res), 0)


class TestReconcile(unittest.TestCase):
    def odoo(self, **kw):
        base = {"num": "10", "acc": "430000", "debit": "0", "credit": "500", "cli": "", "prov": "", "emp": ""}
        base.update(kw)
        return base

    def expected(self, who, why="por factura"):
        return {"10": [("430000", 0, 500, who, why, "430000185", "20250115")]}

    def test_identical_line_is_matched(self):
        m, w, miss, extra = tool.reconcile(self.expected(("C", 185)), [self.odoo(cli="185")])
        self.assertEqual((len(m), len(w), len(miss), len(extra)), (1, 0, 0, 0))

    def test_wrong_partner_is_reported(self):
        m, w, miss, extra = tool.reconcile(self.expected(("C", 185)), [self.odoo(cli="999")])
        self.assertEqual((len(m), len(w)), (0, 1))

    def test_missing_and_extra_lines(self):
        m, w, miss, extra = tool.reconcile(self.expected(None), [self.odoo(credit="600")])
        self.assertEqual((len(m), len(miss), len(extra)), (0, 1, 1))

    def test_employee_matches_any_of_its_codes(self):
        exp = {"10": [("610000", 500, 0, ("E", 3311), "por código de personal", "610003311", "20250115")]}
        m, *_ = tool.reconcile(exp, [self.odoo(acc="610000", debit="500", credit="0", emp="1342|3311")])
        self.assertEqual(len(m), 1)

    def test_no_partner_expected_but_partner_present_is_wrong(self):
        m, w, *_ = tool.reconcile(self.expected(None, "sin socio por regla contable"), [self.odoo(cli="5")])
        self.assertEqual((len(m), len(w)), (0, 1))


if __name__ == "__main__":
    unittest.main()
