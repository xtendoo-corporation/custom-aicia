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
    responsible_domain = fields.Many2many('res.users', compute='_compute_responsible_domain')
    work_group_boss_id = fields.Many2one('res.users', string='Jefe de Equipo', related='work_group_id.equip_boss', store=True)

    @api.depends('work_group_id')
    def _compute_responsible_domain(self):
        for record in self:
            if record.work_group_id:
                record.responsible_domain = record.work_group_id.user_ids.ids
            else:
                record.responsible_domain = []

    responsible_id = fields.Many2one('res.users', string='Responsable', tracking=True,
                                     domain="[('id', 'in', responsible_domain)]")

    user_can_edit = fields.Boolean(string='User Can Edit', compute='_compute_user_can_edit')

    @api.depends('work_group_id', 'responsible_id')
    def _compute_user_can_edit(self):
        for record in self:
            user = self.env.user
            if user.has_group('portal_requests.group_director_manager'):
                record.user_can_edit = True
            elif record.responsible_id == user:
                record.user_can_edit = True
            else:
                record.user_can_edit = False

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
