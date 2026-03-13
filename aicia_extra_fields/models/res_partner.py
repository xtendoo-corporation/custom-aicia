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
