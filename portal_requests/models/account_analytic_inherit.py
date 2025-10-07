from odoo import models, fields, api

class AccountAnalyticAccountInherit(models.Model):
    _inherit = 'account.analytic.account'

    clientes_asociados = fields.Many2many('res.partner', 'account_analytic_partner_rel', 'account_id', 'partner_id',
                                        string='Clientes Asociados',
                                        domain="[('id', 'not in', clientes_asociados_domain)]")

    @api.depends('partner_id', 'clientes_asociados')
    def _compute_clientes_asociados_domain(self):
        for record in self:
            excluded_partners = record.clientes_asociados.ids
            if record.partner_id:
                excluded_partners.append(record.partner_id.id)
            record.clientes_asociados_domain = excluded_partners

    clientes_asociados_domain = fields.Many2many('res.partner', compute='_compute_clientes_asociados_domain')
