from odoo import models, api, _, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    protecter_partner = fields.Boolean(
        string='Socio Protector',
        default=False,
    )
    codigo_cliente = fields.Char(
        string='Código de Cliente',
    )
    codigo_proveedor = fields.Char(
        string='Código de Proveedor',
    )
    cuenta_contable_aicia = fields.Char(
        string='Cuenta contable AICIA',
        index=True,
        help='Cuenta contable (9 dígitos) que el tercero tiene en AICIAWIN. '
             'Varios terceros pueden compartir una misma cuenta: en AICIAWIN la '
             'cuenta identifica a la entidad y el tercero es un registro de '
             'facturación dentro de ella.',
    )
