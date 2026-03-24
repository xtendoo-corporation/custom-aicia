# -*- coding: utf-8 -*-
from odoo import models, fields


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    distribution_plan_id = fields.Many2one(
        'aicia.distribution.plan',
        string='Plan de Distribución',
        domain="[('company_id', 'in', [company_id, False])]",
        help="Plan de distribución que se ejecuta al cobrar una factura con esta analítica.\n"
             "Cada analítica solo puede tener un plan asignado.",
    )
    distribution_move_ids = fields.Many2many(
        'account.move',
        'aicia_dist_move_source_analytic_rel',
        'analytic_id', 'distribution_move_id',
        string='Asientos de Distribución',
        domain=[('is_cash_distribution_move', '=', True)],
    )
    distribution_move_count = fields.Integer(
        compute='_compute_distribution_move_count',
        string='Distribuciones',
    )

    def _compute_distribution_move_count(self):
        for account in self:
            account.distribution_move_count = self.env['account.move'].search_count([
                ('is_cash_distribution_move', '=', True),
                ('distribution_source_analytic_ids', 'in', account.ids),
            ])
