# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountMove(models.Model):
    """Extensión de account.move para identificar asientos de cierre AICIA."""

    _inherit = "account.move"

    aicia_closure = fields.Boolean(
        string="Cierre AICIA",
        default=False,
        copy=False,
        index=True,
        help="Indica que este asiento fue generado por el proceso de cierre AICIA por proyectos.",
    )
    aicia_closure_ref = fields.Char(
        string="Referencia Cierre AICIA",
        copy=False,
        index=True,
        help="Clave única del cierre AICIA: AICIA-{analytic_id}-{date_from}-{date_to}. "
        "Se usa para detectar duplicados.",
    )

