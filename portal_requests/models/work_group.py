from odoo import models, fields, api

class WorkGroup(models.Model):
    _name = 'portal.work.group'
    _description = 'Grupos de Trabajo'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(string='Código', required=True)
    user_ids = fields.Many2many(
        'res.users',
        'work_group_users_rel',
        'group_id',
        'user_id',
        string='Usuarios'
    )

    equip_boss_domain = fields.Many2many('res.users', compute='_compute_equip_boss_domain')


    @api.depends('user_ids')
    def _compute_equip_boss_domain(self):
        group = self.env.ref('portal_requests.group_equip_boss', False)
        for record in self:
            if record.user_ids:
                domain_user = record.user_ids.filtered(lambda u: group in u.groups_id)
                record.equip_boss_domain = domain_user.ids
            else:
                record.equip_boss_domain = []

    equip_boss = fields.Many2one(
        'res.users',
        string='Jefe de Equipo',
        domain="[('id', 'in', equip_boss_domain)]"
    )




