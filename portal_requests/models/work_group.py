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
