from odoo import models, fields

class ProjectInherit(models.Model):
    _inherit = 'project.project'

    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', tracking=True)
