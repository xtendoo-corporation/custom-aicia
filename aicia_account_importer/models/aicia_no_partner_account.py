# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AiciaAccountImporterNoPartnerAccount(models.Model):
    """Cuenta legada que, por criterio contable, no lleva socio.

    El importador no busca contacto para las líneas de estas cuentas y no avisa por
    ello. La regla puede ser la cuenta completa (9 dígitos) o un prefijo. Para las
    reglas de 9 dígitos, ``use_full_code`` importa la cuenta con los 9 dígitos en vez
    de los 5 primeros más un 0.
    """

    _name = "aicia.account.importer.no.partner.account"
    _description = "Cuenta legada sin socio (importador AICIA)"
    _order = "source_code"
    _rec_name = "source_code"

    source_code = fields.Char(
        string="Cuenta legada",
        required=True,
        index=True,
        help="Cuenta completa de 9 dígitos (ej. 430000000) o un prefijo.",
    )
    name = fields.Char(string="Descripción")
    note = fields.Char(string="Observaciones")
    use_full_code = fields.Boolean(
        string="Importar con los 9 dígitos",
        help=(
            "Solo para reglas de 9 dígitos. Si está activo, la cuenta de Odoo es el "
            "código legado completo; si no, los 5 primeros dígitos más un 0."
        ),
    )
    account_name = fields.Char(
        string="Nombre de la cuenta (si se crea)",
        help="Nombre con el que se crea la cuenta de 9 dígitos si no existe en Odoo.",
    )

    _source_code_unique = models.Constraint(
        "unique(source_code)",
        "Ya existe una regla para esta cuenta legada.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "source_code" in vals:
                vals["source_code"] = str(vals["source_code"] or "").strip().replace(" ", "")
        return super().create(vals_list)

    def write(self, vals):
        if "source_code" in vals:
            vals = dict(vals, source_code=str(vals["source_code"] or "").strip().replace(" ", ""))
        return super().write(vals)

    @api.constrains("source_code")
    def _check_source_code(self):
        for rule in self:
            if not re.fullmatch(r"\d{1,9}", rule.source_code or ""):
                raise ValidationError(
                    _("La cuenta legada debe ser un número de hasta 9 dígitos: '%s'.")
                    % rule.source_code
                )

    @api.constrains("source_code", "use_full_code")
    def _check_use_full_code(self):
        for rule in self:
            if rule.use_full_code and len(rule.source_code or "") != 9:
                raise ValidationError(
                    _("'Importar con los 9 dígitos' solo se puede usar con una cuenta de 9 dígitos.")
                )
