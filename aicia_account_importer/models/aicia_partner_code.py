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
    def load_supplier_customer_codes(self):
        """Copia codigo_proveedor y codigo_cliente de los contactos a esta tabla.

        - Usa el número de cada campo (``C1234`` → ``1234``) con el tipo
          proveedor / cliente.
        - Omite los números mayores de 9999 (no caben en una cuenta legada) y los
          repetidos en varios contactos del mismo tipo (ambiguos).
        - No cambia códigos que ya existen. Es repetible.
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
            "missing_field": [],
        }
        existing = {
            (rec.partner_type, rec.code): rec.partner_id
            for rec in self.search([("partner_type", "in", ["supplier", "customer"])])
        }
        to_create = []
        for partner_type, field in (
            ("supplier", "codigo_proveedor"),
            ("customer", "codigo_cliente"),
        ):
            if field not in Partner._fields:
                stats["missing_field"].append(field)
                continue
            by_code = defaultdict(set)
            for rec in Partner.search_read([(field, "!=", False)], [field]):
                found = re.findall(r"\d+", rec[field] or "")
                if not found:
                    stats["no_number"] += 1
                    continue
                number = int(found[0])
                if number > self.MAX_CODE:
                    stats["too_long"] += 1
                    continue
                by_code[self._normalize_code(str(number))].add(rec["id"])
            for code, partner_ids in by_code.items():
                if len(partner_ids) > 1:
                    stats["ambiguous"] += 1
                    continue
                partner_id = next(iter(partner_ids))
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

    def action_load_supplier_customer_codes(self):
        stats = self.load_supplier_customer_codes()
        message = _(
            "Creados: %(created)d · ya existían: %(existing)d · en conflicto: %(conflicts)d · "
            "ambiguos (omitidos): %(ambiguous)d · mayores de 9999 (omitidos): %(too_long)d."
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
