# -*- coding: utf-8 -*-

from odoo import fields, models

class ResUsers(models.Model):
    _inherit = "res.users"


    work_group_ids = fields.Many2many(
        'portal.work.group',
        'work_group_users_rel',  # MISMA tabla relacional
        'user_id',  # columna del usuario
        'group_id',  # columna del grupo
        string='Grupos de Trabajo'
    )
