from odoo import models, fields

class CustomResPartner(models.Model):
    _inherit = 'res.partner'

    company_ids = fields.Many2many('res.company', 'res_company_contacts_rel', 'user_id', 'cid',
                                   string='Companies', default=lambda self: self.env.company.ids)
