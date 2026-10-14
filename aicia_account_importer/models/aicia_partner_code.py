# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import re
from collections import defaultdict

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# NIF/CIF/NIE español (con o sin el prefijo ES del VAT).
SPANISH_NIF_RE = re.compile(r"^(?:ES)?([A-Z]\d{7}[A-Z0-9]|\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")


def real_nif(vat):
    """NIF español sin el prefijo ES, o None si no es un NIF o es de relleno.

    AICIAWIN usa NIF de relleno (99999999, 00000000…) para entidades sin NIF: no
    identifican a nadie, y unir por ellos fusionaría entidades sin relación.
    """
    match = SPANISH_NIF_RE.match(re.sub(r"\s+", "", (vat or "").upper()))
    if not match:
        return None
    nif = match.group(1)
    if len(set(re.sub(r"\D", "", nif))) <= 2:
        return None
    return nif


class AiciaPartnerCode(models.Model):
    """Código AICIA de un contacto.

    Un contacto puede tener varios códigos: los de personal, proveedor y cliente con los
    que AICIAWIN lo dio de alta. El importador de apuntes usa los 4 últimos dígitos de la
    cuenta legada para localizar el contacto cuyo código coincide, y los importadores de
    terceros y el fichero asiento → socio buscan a las personas por estos códigos. El
    código es único dentro de cada tipo de tercero (personal, proveedor, cliente): el 495
    de un empleado y el 495 de un proveedor son contactos distintos.

    Cuando AICIAWIN tenía a una misma entidad con varios códigos (mismo NIF), en Odoo es un
    solo contacto con todos sus códigos; cada código conserva la denominación y la dirección
    con las que se dio de alta.
    """

    _name = "aicia.partner.code"
    _description = "Código AICIA de contacto"
    _order = "code"
    _rec_name = "code"

    partner_id = fields.Many2one(
        "res.partner",
        string="Contacto",
        required=True,
        ondelete="cascade",
        index=True,
    )
    partner_type = fields.Selection(
        [
            ("employee", "Personal"),
            ("supplier", "Proveedor"),
            ("customer", "Cliente"),
        ],
        string="Tipo",
        required=True,
        default="employee",
        index=True,
    )
    code = fields.Char(string="Código AICIA", required=True, index=True)
    legacy_name = fields.Char(
        string="Denominación en AICIAWIN",
        help="Nombre con el que AICIAWIN dio de alta este código (razón social de entonces).",
    )
    legacy_address = fields.Char(
        string="Dirección en AICIAWIN",
        help="Dirección de facturación con la que AICIAWIN dio de alta este código.",
    )

    _type_code_unique = models.Constraint(
        "unique(partner_type, code)",
        "Este código AICIA ya está asignado a un contacto del mismo tipo.",
    )

    @api.model
    def _normalize_code(self, code):
        """Quita espacios y ceros a la izquierda de los códigos numéricos ("0495" → "495")."""
        code = str(code or "").strip()
        return str(int(code)) if code.isdigit() else code

    @api.model
    def _partner_by_code(self, partner_type, code):
        """Contacto que tiene este código para este tipo, o un recordset vacío."""
        return self.search(
            [("partner_type", "=", partner_type), ("code", "=", self._normalize_code(code))],
            limit=1,
        ).partner_id

    @api.model
    def _partners_by_codes(self, partner_type, codes):
        """{código normalizado: contacto} para una lista de códigos."""
        codes = sorted({self._normalize_code(c) for c in codes})
        if not codes:
            return {}
        return {
            rec.code: rec.partner_id
            for rec in self.search([("partner_type", "=", partner_type), ("code", "in", codes)])
        }

    @api.model
    def _partner_address(self, partner):
        return ", ".join(filter(None, [partner.street, partner.zip, partner.city])) or False

    # ── Carga de códigos de proveedor y cliente ──────────────────────────────

    @api.model
    def load_supplier_customer_codes(self):
        """Crea el código AICIA de cada contacto con ``codigo_proveedor`` / ``codigo_cliente``.

        El número de cada campo (``C1234`` → ``1234``) es el código, con el tipo proveedor o
        cliente. No hay límite de dígitos: los clientes de la cuenta general (430000000)
        tienen códigos de 5 cifras y también se buscan por código. Solo añade: no cambia ni
        borra códigos que ya existen y es repetible. Se omiten los números repetidos en
        varios contactos del mismo tipo (ambiguos).
        Devuelve un dict con los contadores.
        """
        Partner = self.env["res.partner"].with_context(active_test=False)
        stats = {"created": 0, "existing": 0, "conflicts": 0, "ambiguous": 0,
                 "no_number": 0, "missing_field": []}
        existing = {
            (rec.partner_type, rec.code): rec.partner_id
            for rec in self.search([("partner_type", "in", ["supplier", "customer"])])
        }
        to_create = []
        for partner_type, field in (("supplier", "codigo_proveedor"), ("customer", "codigo_cliente")):
            if field not in Partner._fields:
                stats["missing_field"].append(field)
                continue
            by_code = defaultdict(set)
            for rec in Partner.search_read([(field, "!=", False)], [field]):
                found = re.findall(r"\d+", rec[field] or "")
                if not found:
                    stats["no_number"] += 1
                    continue
                by_code[self._normalize_code(found[0])].add(rec["id"])
            for code, partner_ids in by_code.items():
                if len(partner_ids) > 1:
                    stats["ambiguous"] += 1
                    continue
                partner_id = next(iter(partner_ids))
                current = existing.get((partner_type, code))
                if current:
                    stats["existing" if current.id == partner_id else "conflicts"] += 1
                    continue
                to_create.append({"partner_id": partner_id, "partner_type": partner_type, "code": code})
                stats["created"] += 1
        if to_create:
            self.create(to_create)
        return stats

    def _notify_load(self, stats):
        message = _(
            "Creados: %(created)d · ya existían: %(existing)d · en conflicto: %(conflicts)d · "
            "ambiguos (omitidos): %(ambiguous)d."
        ) % stats
        if stats["missing_field"]:
            message += " " + _("Falta el campo: %s.") % ", ".join(stats["missing_field"])
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Códigos de proveedor y cliente"),
                "message": message,
                "type": "success",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_load_supplier_customer_codes(self):
        return self._notify_load(self.load_supplier_customer_codes())

    # ── Fusión de contactos con el mismo NIF ─────────────────────────────────

    @api.model
    def merge_partners_by_nif(self, dry_run=True, partner_ids=None, commit_every=None):
        """Deja un solo contacto por NIF entre los proveedores y clientes de AICIAWIN.

        Los contactos con el mismo NIF español se fusionan en el que tiene el código más
        antiguo. Antes de fusionar, cada código guarda la denominación y la dirección de su
        contacto (``legacy_name`` / ``legacy_address``), y el contacto final conserva todos
        los códigos. Se salta los grupos en los que algún contacto es un empleado o un
        usuario. Con ``dry_run`` solo cuenta. Con ``partner_ids`` solo se tocan esos contactos.
        Con ``commit_every`` confirma cada N grupos (para lanzarlo desde un shell: si se corta,
        se puede repetir y continúa donde se quedó, porque lo ya fusionado ya no está duplicado).
        Es irreversible: hazlo con copia de seguridad.
        Devuelve un dict con los contadores y la lista de grupos saltados.
        """
        self.load_supplier_customer_codes()
        codes = self.search([("partner_type", "in", ["supplier", "customer"])])
        by_partner = defaultdict(list)
        for rec in codes:
            by_partner[rec.partner_id.id].append(rec)
        Partner = self.env["res.partner"].with_context(active_test=False)
        groups = defaultdict(list)
        scope = set(partner_ids) if partner_ids is not None else None
        for partner in Partner.browse([pid for pid in by_partner if scope is None or pid in scope]):
            nif = real_nif(partner.vat)
            if nif:
                groups[nif].append(partner)
        groups = {nif: ps for nif, ps in groups.items() if len(ps) > 1}
        protected = self._protected_partner_ids([p.id for ps in groups.values() for p in ps])
        stats = {"groups": 0, "merged": 0, "skipped": [], "errors": []}
        # Los NIF de AICIAWIN no siempre pasan la validación de Odoo (igual que al importar).
        Wizard = self.env["base.partner.merge.automatic.wizard"].with_context(
            import_file=True, check_vies=False
        )
        for nif, partners in sorted(groups.items()):
            if any(p.id in protected for p in partners):
                stats["skipped"].append(nif)
                continue
            stats["groups"] += 1
            stats["merged"] += len(partners) - 1
            if dry_run:
                continue
            if stats["groups"] % 25 == 0:
                _logger.info("AICIA fusión por NIF: %d grupos", stats["groups"])

            def oldest(partner):
                return (min(int(c.code) for c in by_partner[partner.id] if c.code.isdigit()), partner.id)

            partners.sort(key=oldest)
            dst, sources = partners[0], partners[1:]
            for partner in partners:
                for rec in by_partner[partner.id]:
                    rec.write({
                        "legacy_name": rec.legacy_name or partner.complete_name or partner.name,
                        "legacy_address": rec.legacy_address or self._partner_address(partner),
                    })
            ranks = {
                "customer_rank": max(p.customer_rank for p in partners),
                "supplier_rank": max(p.supplier_rank for p in partners),
            }
            try:
                with self.env.cr.savepoint():
                    for i in range(0, len(sources), 2):  # la herramienta de Odoo admite 3 contactos por vez
                        chunk = sources[i:i + 2]
                        Wizard._merge([dst.id] + [s.id for s in chunk], dst.with_env(Wizard.env), extra_checks=False)
                    dst.with_context(import_file=True, check_vies=False).write(ranks)
            except Exception as exc:  # noqa: BLE001 - se informa y se sigue con el resto
                stats["errors"].append((nif, repr(exc)))
            if commit_every and stats["groups"] % commit_every == 0:
                self.env.cr.commit()
        return stats

    @api.model
    def _protected_partner_ids(self, partner_ids):
        """Contactos que no se fusionan: empleados (contacto de trabajo) y usuarios."""
        protected = set(self.env["res.users"].sudo().with_context(active_test=False).search(
            [("partner_id", "in", partner_ids)]).partner_id.ids)
        if "hr.employee" in self.env:
            protected |= set(self.env["hr.employee"].sudo().with_context(active_test=False).search(
                [("work_contact_id", "in", partner_ids)]).work_contact_id.ids)
        return protected

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "code" in vals:
                vals["code"] = self._normalize_code(vals["code"])
        return super().create(vals_list)

    def write(self, vals):
        if "code" in vals:
            vals = dict(vals, code=self._normalize_code(vals["code"]))
        return super().write(vals)


class ResPartner(models.Model):
    _inherit = "res.partner"

    aicia_code_ids = fields.One2many(
        "aicia.partner.code",
        "partner_id",
        string="Códigos AICIA",
        copy=False,
    )
