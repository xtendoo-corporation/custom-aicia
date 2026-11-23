# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    numero_asiento_aicia = fields.Char(
        string="Nº Asiento AICIA",
        index=True,
        copy=False,
        readonly=True,
        help=(
            "Número de asiento (Numero_Apunte) del sistema contable legado "
            "AICIA. Se registra durante la importación para mantener la "
            "trazabilidad entre ambos sistemas."
        ),
    )
