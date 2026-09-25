# -*- coding: utf-8 -*-
from odoo import models, fields


class AiciaDistributionMove(models.Model):
    _name = 'aicia.distribution.move'
    _description = 'AICIA Distribution Log'
    _check_company_auto = True
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Nombre',
        related='move_id.name',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    partial_reconcile_id = fields.Many2one(
        'account.partial.reconcile', string='Conciliación',
        required=True, ondelete='cascade', index=True,
    )
    move_id = fields.Many2one(
        'account.move', string='Asiento Contable',
        required=True, check_company=True,
    )
    state = fields.Selection(related='move_id.state', store=True)
    amount_total = fields.Monetary(
        string='Importe Total', currency_field='currency_id',
    )
    currency_id = fields.Many2one(related='move_id.currency_id')
    applied_plan_ids = fields.Many2many(
        'aicia.distribution.plan',
        string='Planes Aplicados',
        help='Planes de distribución que generaron este asiento.',
    )
    source_analytic_account_ids = fields.Many2many(
        'account.analytic.account',
        'aicia_dist_move_source_analytic_rel',
        'distribution_move_id', 'analytic_id',
        string='Analíticas Origen',
        help='Cuentas analíticas de origen que activaron esta distribución.',
    )
