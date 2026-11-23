from odoo import fields, models


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    work_group_id = fields.Many2one(
        'portal.work.group',
        string='Grupo de Trabajo',
        related='account_id.work_group_id',
        store=True,
        readonly=True,
        index=True,
    )
