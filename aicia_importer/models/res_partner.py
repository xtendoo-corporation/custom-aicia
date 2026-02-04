from odoo import models, api, _, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.constrains('vat', 'country_id')
    def _check_vat(self, **kwargs):
        if self.env.context.get('import_file'):
            print("*-*"*20)
            print("PASA VALIDACION VAT EN IMPORTACION")
            print("*-*"*20)
            return
        super()._check_vat(**kwargs)
