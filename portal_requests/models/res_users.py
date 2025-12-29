# -*- coding: utf-8 -*-

from odoo import fields, models

class ResUsers(models.Model):
    _inherit = "res.users"

    certificate_id = fields.Many2one(
        comodel_name="report.certificate",
        string="Certificado de firma",
        help="Certificado asignado para firmar informes",
        ondelete="restrict",
    )

    work_group_ids = fields.Many2many(
        'portal.work.group',
        'work_group_users_rel',  # MISMA tabla relacional
        'user_id',  # columna del usuario
        'group_id',  # columna del grupo
        string='Grupos de Trabajo'
    )
