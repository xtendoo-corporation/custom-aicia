# -*- coding: utf-8 -*-

from odoo import api, fields, models

# Cambios de usuario que alteran quién lee cada manual en Knowledge
MANUAL_ACCESS_FIELDS = {'group_ids', 'active'}


class ResUsers(models.Model):
    _inherit = "res.users"


    work_group_ids = fields.Many2many(
        'portal.work.group',
        'work_group_users_rel',  # MISMA tabla relacional
        'user_id',  # columna del usuario
        'group_id',  # columna del grupo
        string='Grupos de Trabajo'
    )

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        self.env['knowledge.article']._sync_portal_manual_members()
        return users

    def write(self, vals):
        res = super().write(vals)
        if MANUAL_ACCESS_FIELDS & vals.keys():
            self.env['knowledge.article']._sync_portal_manual_members()
        return res


class ResGroups(models.Model):
    _inherit = "res.groups"

    def write(self, vals):
        res = super().write(vals)
        if {'user_ids', 'implied_ids'} & vals.keys():
            self.env['knowledge.article']._sync_portal_manual_members()
        return res
