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
