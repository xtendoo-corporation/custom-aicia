# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
_logger = logging.getLogger(__name__)


class AiciaDistributionPlan(models.Model):
    """
    Plan de distribución de cobros AICIA.
    Un plan agrupa TODAS las líneas de reparto que deben ejecutarse
    cuando se cobra una factura cuya analítica de origen coincide con el filtro.
    Ejemplo de plan completo:
        Línea 1 — IVA (477 automático, proporcional al cobro)
        Línea 2 — 6 % Tipo A  (Debe: 700 AICIA / Haber: 700 origen)
        Línea 3 — 3 % Tipo B  (Debe: 401200 AICIA / Haber: 700 origen)
        Línea 4 — 1 % Tipo B  (Debe: 401300 AICIA / Haber: 700 origen)
    """
    _name = 'aicia.distribution.plan'
    _description = 'Plan de Distribución de Cobros AICIA'
    _check_company_auto = True
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)

    # Analíticas que tienen asignado este plan (inverso del Many2one en analytic)
    source_analytic_account_ids = fields.One2many(
        'account.analytic.account',
        'distribution_plan_id',
        string='Analíticas Vinculadas',
        help="Cuentas analíticas que tienen este plan asignado.\n"
             "Se gestiona desde cada cuenta analítica.",
        readonly=True,
    )
    analytic_count = fields.Integer(
        compute='_compute_analytic_count',
        string='Nº Analíticas',
    )

    # Analítica receptora AICIA (sobreescribe la de compañía si se indica)
    receiver_analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analítica Receptora AICIA',
        help="Proyecto AICIA receptor de los repartos.\n"
             "Si no se indica, se usa la configurada en la compañía.",
    )

    line_ids = fields.One2many(
        'aicia.distribution.plan.line', 'plan_id',
        string='Líneas de Reparto',
        copy=True,
    )
    line_count = fields.Integer(compute='_compute_line_count', string='Nº Líneas')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for plan in self:
            plan.line_count = len(plan.line_ids)

    @api.depends('source_analytic_account_ids')
    def _compute_analytic_count(self):
        for plan in self:
            plan.analytic_count = len(plan.source_analytic_account_ids)

    # ── Business helpers ──────────────────────────────────────────────────

    def get_receiver_analytic_id(self):
        """
        Devuelve el id de la analítica receptora efectiva.
        Prioridad: plan → compañía.
        Retorna None (con warning) si no hay ninguna configurada.
        """
        self.ensure_one()
        analytic = (
            self.receiver_analytic_account_id
            or self.company_id.cash_distribution_receiver_analytic_id
        )
        if not analytic:
            _logger.warning(
                "Plan '%s' (id=%s): sin analítica receptora configurada — omitido.",
                self.name, self.id,
            )
        return analytic.id if analytic else None

