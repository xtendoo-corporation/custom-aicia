# -*- coding: utf-8 -*-
from odoo import models, fields


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    distribution_plan_ids = fields.Many2many(
        'aicia.distribution.plan',
        'aicia_dist_plan_source_analytic_rel',
        'analytic_id', 'plan_id',
        string='Planes de Distribución',
        help="Planes de distribución que se activan cuando esta analítica "
             "está presente en la cabecera o líneas de una factura cobrada.",
    )
    distribution_plan_count = fields.Integer(
        compute='_compute_distribution_plan_count',
        string='Nº Planes de Distribución',
    )

    def _compute_distribution_plan_count(self):
        for account in self:
            account.distribution_plan_count = len(account.distribution_plan_ids)

