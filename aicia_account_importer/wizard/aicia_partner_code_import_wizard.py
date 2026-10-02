# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import re
import unicodedata
from base64 import b64decode
from html import escape
from io import BytesIO

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import openpyxl
except ImportError:
    openpyxl = None

PARTNER_TYPE = "employee"

# Categorías de coincidencia. Las que están en ASSIGNABLE crean código.
CAT_CODE_NIF = "A"
CAT_CODE_NAME = "B"
CAT_CODE_CONFLICT = "C"
CAT_NIF_OTHER_CODE = "D"
CAT_NIF_CONTACT = "E"
CAT_NAME_ONLY = "F"
CAT_NONE = "G"
CAT_AMBIGUOUS = "H"
ASSIGNABLE = {
    CAT_CODE_NIF,
    CAT_CODE_NAME,
    CAT_CODE_CONFLICT,
    CAT_NIF_OTHER_CODE,
    CAT_NIF_CONTACT,
    CAT_NAME_ONLY,
}
CAT_LABELS = {
    CAT_CODE_NIF: "A — código del empleado y NIF coinciden",
    CAT_CODE_NAME: "B — código y nombre coinciden (NIF sin confirmar)",
    CAT_CODE_CONFLICT: "C — el empleado con ese código tiene otro NIF y otro nombre",
    CAT_NIF_OTHER_CODE: "D — misma persona por NIF, con otro código",
    CAT_NIF_CONTACT: "E — contacto existente por NIF (sin empleado)",
    CAT_NAME_ONLY: "F — solo por nombre (sin confirmar por NIF)",
    CAT_NONE: "G — sin coincidencia",
    CAT_AMBIGUOUS: "H — varias coincidencias posibles",
}
# Categorías que se listan con detalle en el log (A es la mayoría y solo se cuenta)
DETAILED = [
    CAT_CODE_CONFLICT,
    CAT_CODE_NAME,
    CAT_NIF_OTHER_CODE,
    CAT_NIF_CONTACT,
    CAT_NAME_ONLY,
    CAT_AMBIGUOUS,
    CAT_NONE,
]


def _norm_name(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore")
    text = re.sub(r"[^A-Z0-9 ]", " ", text.decode().upper())
    return " ".join(text.split())


def _norm_nif(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _first_number(value):
    found = re.findall(r"\d+", str(value or ""))
    return int(found[0]) if found else None


class AiciaPartnerCodeImportWizard(models.TransientModel):
    """Carga los códigos AICIA de los contactos desde la hoja Personal.

    Cada fila de la hoja (ID_Personal, Nombre, NIF) se empareja con un contacto
    y se crea un código AICIA de tipo Personal con el ID_Personal. Una persona
    con varios ID_Personal acaba con varios códigos.
    """

    _name = "aicia.partner.code.import.wizard"
    _description = "Cargar códigos AICIA desde la hoja Personal"

    file_personal = fields.Binary(string="Personal.xlsx")
    filename_personal = fields.Char()
    state = fields.Selection(
        [("draft", "Pendiente"), ("done", "Procesado")], default="draft"
    )
    simulated = fields.Boolean(readonly=True)
    total_rows = fields.Integer(string="Filas leídas", readonly=True)
    total_created = fields.Integer(string="Códigos creados", readonly=True)
    total_existing = fields.Integer(string="Ya existían", readonly=True)
    total_conflicts = fields.Integer(
        string="Código ya asignado a otro contacto", readonly=True
    )
    total_unassigned = fields.Integer(string="Sin asignar (G y H)", readonly=True)
    result_log = fields.Html(string="Resultado", readonly=True)

    # ── Acciones ─────────────────────────────────────────────────────────────

    def action_simulate(self):
        """Calcula las coincidencias sin crear nada."""
        return self._run(dry_run=True)

    def action_load(self):
        """Calcula las coincidencias y crea los códigos de las asignables."""
        return self._run(dry_run=False)

    def _run(self, dry_run):
        self.ensure_one()
        if not self.file_personal:
            raise UserError(_("Sube la hoja Personal.xlsx antes de continuar."))
        rows = self._read_rows(b64decode(self.file_personal))
        matches = self._match_rows(rows)
        stats = self._apply(matches, dry_run=dry_run)
        stats["unassigned"] = sum(
            1 for m in matches if m["category"] not in ASSIGNABLE
        )
        self.write(
            {
                "state": "done",
                "simulated": dry_run,
                "total_rows": len(rows),
                "total_created": stats["created"],
                "total_existing": stats["existing"],
                "total_conflicts": stats["conflicts"],
                "total_unassigned": stats["unassigned"],
                "result_log": self._build_log(matches, stats, dry_run),
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }

    # ── Lectura del Excel ────────────────────────────────────────────────────

    def _read_rows(self, content):
        if not openpyxl:
            raise UserError(_("La librería 'openpyxl' no está instalada en el servidor."))
        try:
            wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:
            raise UserError(_("No se pudo abrir el archivo: %s") % exc) from exc
        ws = wb.worksheets[0]
        rows_iter = ws.iter_rows(values_only=True)
        header = next(rows_iter, None)
        if not header:
            raise UserError(_("La hoja está vacía."))
        index = {str(name).strip(): pos for pos, name in enumerate(header) if name}
        for required in ("ID_Personal", "Nombre"):
            if required not in index:
                raise UserError(
                    _("Falta la columna '%s' en la hoja Personal.") % required
                )

        def cell(row, name):
            pos = index.get(name)
            return row[pos] if pos is not None and len(row) > pos else None

        rows = []
        for row in rows_iter:
            raw_id = cell(row, "ID_Personal")
            if raw_id is None or raw_id == "":
                continue
            try:
                id_personal = int(float(raw_id))
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "id": id_personal,
                    "name": str(cell(row, "Nombre") or "").strip(),
                    "nif": str(cell(row, "NIF") or "").strip(),
                }
            )
        return rows

    # ── Índices de empleados y contactos ─────────────────────────────────────

    def _build_indexes(self):
        """Índices de búsqueda; el módulo funciona aunque no esté hr instalado."""
        idx = {
            "emp_by_code": {},
            "emp_by_nif": {},
            "emp_by_name": {},
            "partner_by_nif": {},
            "partner_by_name": {},
        }
        Employee = self.env.get("hr.employee")
        if Employee is not None:
            has_code = "codigo_empleado" in Employee._fields
            has_nif = "identification_id" in Employee._fields
            for emp in Employee.with_context(active_test=False).search([]):
                contact = emp.work_contact_id
                if not contact:
                    continue
                entry = {
                    "partner": contact,
                    "name": emp.name,
                    "nif": _norm_nif(emp.identification_id) if has_nif else "",
                    "vat": _norm_nif(contact.vat),
                }
                number = _first_number(emp.codigo_empleado) if has_code else None
                if number is not None:
                    idx["emp_by_code"].setdefault(number, []).append(entry)
                for nif in {entry["nif"], entry["vat"]} - {""}:
                    idx["emp_by_nif"].setdefault(nif, {})[contact.id] = entry
                idx["emp_by_name"].setdefault(_norm_name(emp.name), {})[
                    contact.id
                ] = entry
        Partner = self.env["res.partner"].with_context(active_test=False)
        for rec in Partner.search_read([("vat", "!=", False)], ["vat"]):
            idx["partner_by_nif"].setdefault(_norm_nif(rec["vat"]), set()).add(rec["id"])
        for rec in Partner.search_read([("is_company", "=", False)], ["name"]):
            idx["partner_by_name"].setdefault(_norm_name(rec["name"]), set()).add(
                rec["id"]
            )
        return idx

    # ── Emparejamiento ───────────────────────────────────────────────────────

    def _match_rows(self, rows):
        idx = self._build_indexes()
        Partner = self.env["res.partner"].with_context(active_test=False)
        matches = []
        for row in rows:
            nif = _norm_nif(row["nif"])
            name = _norm_name(row["name"])
            category, partner, note = self._match_row(row, nif, name, idx, Partner)
            matches.append({**row, "category": category, "partner": partner, "note": note})
        return matches

    def _match_row(self, row, nif, name, idx, Partner):
        # 1) Un empleado que ya tiene ese número como código de empleado
        candidates = idx["emp_by_code"].get(row["id"], [])
        if len(candidates) > 1:
            return CAT_AMBIGUOUS, Partner.browse(), _("Varios empleados con ese código")
        if candidates:
            entry = candidates[0]
            if nif and nif in {entry["nif"], entry["vat"]}:
                return CAT_CODE_NIF, entry["partner"], ""
            if name and name == _norm_name(entry["name"]):
                return CAT_CODE_NAME, entry["partner"], _("Revisar NIF")
            return (
                CAT_CODE_CONFLICT,
                entry["partner"],
                _("El código lo tiene %s") % entry["name"],
            )
        # 2) Por NIF: un empleado que ya tiene otro código, o un contacto
        if nif:
            by_nif = idx["emp_by_nif"].get(nif, {})
            if len(by_nif) == 1:
                entry = next(iter(by_nif.values()))
                return CAT_NIF_OTHER_CODE, entry["partner"], _("Ya tenía otro código")
            if len(by_nif) > 1:
                return CAT_AMBIGUOUS, Partner.browse(), _("NIF en varios empleados")
            partner_ids = idx["partner_by_nif"].get(nif, set())
            if len(partner_ids) == 1:
                return CAT_NIF_CONTACT, Partner.browse(next(iter(partner_ids))), ""
            if len(partner_ids) > 1:
                return CAT_AMBIGUOUS, Partner.browse(), _("NIF en varios contactos")
        # 3) Solo por nombre (único)
        if name:
            by_name = idx["emp_by_name"].get(name, {})
            people = idx["partner_by_name"].get(name, set())
            ids = set(by_name) | set(people)
            if len(ids) == 1:
                return CAT_NAME_ONLY, Partner.browse(next(iter(ids))), _(
                    "No confirmado por NIF"
                )
            if len(ids) > 1:
                return CAT_AMBIGUOUS, Partner.browse(), _("Nombre repetido")
        return CAT_NONE, Partner.browse(), ""

    # ── Creación de códigos ──────────────────────────────────────────────────

    def _apply(self, matches, dry_run):
        Code = self.env["aicia.partner.code"]
        existing = {
            rec.code: rec.partner_id
            for rec in Code.search([("partner_type", "=", PARTNER_TYPE)])
        }
        stats = {"created": 0, "existing": 0, "conflicts": 0}
        to_create = []
        seen = {}
        for m in matches:
            m["result"] = ""
            if m["category"] not in ASSIGNABLE:
                continue
            code = Code._normalize_code(str(m["id"]))
            current = existing.get(code) or seen.get(code)
            if current:
                if current == m["partner"]:
                    stats["existing"] += 1
                    m["result"] = "existing"
                else:
                    stats["conflicts"] += 1
                    m["result"] = "conflict"
                    m["note"] = (
                        m["note"] + " " if m["note"] else ""
                    ) + _("Código ya asignado a %s") % current.display_name
                continue
            seen[code] = m["partner"]
            to_create.append(
                {
                    "partner_id": m["partner"].id,
                    "partner_type": PARTNER_TYPE,
                    "code": code,
                }
            )
            stats["created"] += 1
            m["result"] = "created"
        if to_create and not dry_run:
            Code.create(to_create)
        return stats

    # ── Log ──────────────────────────────────────────────────────────────────

    def _build_log(self, matches, stats, dry_run):
        counts = {}
        for m in matches:
            counts[m["category"]] = counts.get(m["category"], 0) + 1
        title = _("SIMULACIÓN — no se ha creado nada") if dry_run else _("Carga realizada")
        html = f"<div style='font-size:12px'><p><strong>{escape(title)}</strong></p>"
        html += (
            f"<p>{len(matches)} filas — "
            f"{stats['created']} códigos {'por crear' if dry_run else 'creados'}, "
            f"{stats['existing']} ya existían, "
            f"{stats['conflicts']} en conflicto, "
            f"{stats['unassigned']} sin asignar.</p><ul>"
        )
        for cat in sorted(CAT_LABELS):
            html += f"<li>{counts.get(cat, 0):5d} &nbsp;{escape(CAT_LABELS[cat])}</li>"
        html += "</ul>"
        for cat in DETAILED:
            group = [m for m in matches if m["category"] == cat]
            if not group:
                continue
            html += f"<hr/><p><strong>{escape(CAT_LABELS[cat])}</strong> ({len(group)})</p><ul>"
            for m in group:
                target = m["partner"].display_name if m["partner"] else "—"
                note = f" — {escape(m['note'])}" if m["note"] else ""
                html += (
                    f"<li><code>{m['id']}</code> {escape(m['name'])} → "
                    f"{escape(target)}{note}</li>"
                )
            html += "</ul>"
        conflicts = [m for m in matches if m["result"] == "conflict"]
        if conflicts:
            html += (
                f"<hr/><p style='color:#8B0000'><strong>Códigos ya asignados a otro "
                f"contacto, no modificados ({len(conflicts)})</strong></p><ul>"
            )
            for m in conflicts:
                html += f"<li><code>{m['id']}</code> {escape(m['name'])} — {escape(m['note'])}</li>"
            html += "</ul>"
        return html + "</div>"
