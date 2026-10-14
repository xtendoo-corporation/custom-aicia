# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import re
from collections import defaultdict

from odoo import _, api, fields, models


class AiciaPartnerCode(models.Model):
    """Código AICIA de un contacto.

    Un contacto puede tener varios códigos. El importador de apuntes usa los
    4 últimos dígitos de la cuenta legada para localizar el contacto cuyo
    código coincide. El código es único dentro de cada tipo de tercero
    (personal, proveedor, cliente): el 495 de un empleado y el 495 de un
    proveedor son contactos distintos.
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

    _type_code_unique = models.Constraint(
        "unique(partner_type, code)",
        "Este código AICIA ya está asignado a un contacto del mismo tipo.",
    )

    @api.model
    def _normalize_code(self, code):
        """Quita espacios y ceros a la izquierda de los códigos numéricos ("0495" → "495")."""
        code = str(code or "").strip()
        return str(int(code)) if code.isdigit() else code

    # Los códigos de las cuentas legadas tienen 4 dígitos: un código mayor no se
    # puede referenciar desde ningún apunte.
    MAX_CODE = 9999

    @api.model
    def load_supplier_customer_codes(self, reset=False):
        """Rellena los códigos de proveedor y cliente a partir de la cuenta contable.

        El código de un tercero son los 4 últimos dígitos de su cuenta contable
        de AICIAWIN (``cuenta_contable_aicia``). Si el contacto no la tiene, se
        usa el número de ``codigo_proveedor`` / ``codigo_cliente`` (``C1234`` →
        ``1234``), que coincide con la cuenta en la mayoría de los casos.

        En AICIAWIN varios terceros pueden compartir una cuenta (la cuenta es la
        entidad). El código se asigna a un único contacto: el "dueño", cuyo
        número propio coincide con el código; el resto de terceros de esa cuenta
        no recibe código. Si ningún dueño es único, el código se omite (ambiguo).

        - Omite los códigos mayores de 9999 y las cuentas con los dígitos 4 y 5
          distintos de 0 (no caben en 4 dígitos) y las cuentas generales (0).
        - Sin ``reset`` no cambia códigos que ya existen. Con ``reset`` borra antes
          todos los códigos de proveedor y cliente (no los de personal).
        Devuelve un dict con los contadores.
        """
        Partner = self.env["res.partner"].with_context(active_test=False)
        stats = {
            "created": 0,
            "existing": 0,
            "conflicts": 0,
            "ambiguous": 0,
            "too_long": 0,
            "no_number": 0,
            "general": 0,
            "shared": 0,
            "aliases": 0,
            "fallback": 0,
            "missing_field": [],
        }
        if reset:
            self.search([("partner_type", "in", ["supplier", "customer"])]).unlink()
        existing = {
            (rec.partner_type, rec.code): rec.partner_id
            for rec in self.search([("partner_type", "in", ["supplier", "customer"])])
        }
        has_account = "cuenta_contable_aicia" in Partner._fields
        to_create = []
        for partner_type, field in (
            ("supplier", "codigo_proveedor"),
            ("customer", "codigo_cliente"),
        ):
            if field not in Partner._fields:
                stats["missing_field"].append(field)
                continue
            by_code = defaultdict(list)  # código → [(id contacto, número propio)]
            by_own = defaultdict(set)  # número propio → contactos
            unplaced = []  # contactos que no pudieron quedarse con el código de su cuenta
            read_fields = [field] + (["cuenta_contable_aicia"] if has_account else [])
            for rec in Partner.search_read([(field, "!=", False)], read_fields):
                found = re.findall(r"\d+", rec[field] or "")
                if not found:
                    stats["no_number"] += 1
                    continue
                own = int(found[0])
                by_own[own].add(rec["id"])
                account = (rec.get("cuenta_contable_aicia") or "").strip()
                if account.isdigit() and len(account) == 9:
                    if account[3:5] != "00":
                        stats["too_long"] += 1
                        unplaced.append((rec["id"], own))
                        continue
                    number = int(account[-4:])
                    if not number:
                        stats["general"] += 1
                        unplaced.append((rec["id"], own))
                        continue
                else:
                    number = own
                if number > self.MAX_CODE:
                    stats["too_long"] += 1
                    continue
                by_code[self._normalize_code(str(number))].append((rec["id"], own))
            chosen = {}  # código → id de contacto
            for code, members in by_code.items():
                if len(members) == 1:
                    chosen[code] = members[0][0]
                    continue
                owners = {pid for pid, own in members if str(own) == code}
                if len(owners) == 1:
                    owner = next(iter(owners))
                    chosen[code] = owner
                    stats["shared"] += 1
                    stats["aliases"] += len(members) - 1
                    unplaced.extend((pid, own) for pid, own in members if pid != owner)
                else:
                    # Ningún dueño dentro del grupo: si el contacto con ese número existe
                    # (hoy con otra cuenta), la cuenta era suya.
                    titular = by_own.get(int(code), set())
                    if len(titular) == 1:
                        chosen[code] = next(iter(titular))
                        stats["shared"] += 1
                        stats["aliases"] += len(members)
                    else:
                        stats["ambiguous"] += 1
                    unplaced.extend(members)
            # Un código que ninguna cuenta reclama era la cuenta antigua del contacto con
            # ese número (AICIAWIN le cambió después de cuenta): queda para él, como antes
            # de usar la cuenta contable. Un código reclamado por otras cuentas no se toca.
            for partner_id, own in unplaced:
                code = self._normalize_code(str(own))
                if own <= self.MAX_CODE and code not in by_code:
                    chosen[code] = partner_id
                    stats["fallback"] += 1
            for code, partner_id in chosen.items():
                current = existing.get((partner_type, code))
                if current:
                    stats["existing" if current.id == partner_id else "conflicts"] += 1
                    continue
                to_create.append(
                    {"partner_id": partner_id, "partner_type": partner_type, "code": code}
                )
                stats["created"] += 1
        if to_create:
            self.create(to_create)
        return stats

    def _notify_load(self, stats):
        message = _(
            "Creados: %(created)d · ya existían: %(existing)d · en conflicto: %(conflicts)d · "
            "ambiguos (omitidos): %(ambiguous)d · cuentas compartidas (asignadas al dueño): "
            "%(shared)d con %(aliases)d terceros que no son el dueño · cuenta general: "
            "%(general)d · no caben en 4 dígitos: %(too_long)d · código de cuenta antigua "
            "(por ID): %(fallback)d."
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

    def action_reload_supplier_customer_codes(self):
        return self._notify_load(self.load_supplier_customer_codes(reset=True))

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
