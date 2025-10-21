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

    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', tracking=True)

    def _compute_attachment_count(self):
        Attachment = self.env['ir.attachment']
        for record in self:
            attachment_count = Attachment.search_count([
                ('res_model', '=', 'account.analytic.account'),
                ('res_id', '=', record.id)
            ])
            record.attachment_count = attachment_count

    attachment_count = fields.Integer(string='Attachment Count', compute='_compute_attachment_count')

    def action_open_attachments(self):
        return {
            'name': 'Adjuntos',
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'tree,kanban,form',
            'domain': [
                ('res_model', '=', 'account.analytic.account'),
                ('res_id', '=', self.id)
            ],
            'context': {
                'default_res_model': 'account.analytic.account',
                'default_res_id': self.id,
            },
            'target': 'current',
        }
