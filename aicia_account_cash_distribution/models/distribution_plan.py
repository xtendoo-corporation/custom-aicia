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

    # ── Defaults bootstrap ───────────────────────────────────────────────

    @api.model
    def _setup_default_plan(self, company):
        """Crea/actualiza el plan por defecto y sus líneas de forma segura."""
        plan = self.search([
            ('company_id', '=', company.id),
            ('name', '=', 'Distribución AICIA por defecto'),
        ], limit=1)
        if not plan:
            receiver = self._ensure_receiver_analytic(company)
            plan = self.create({
                'name': 'Distribución AICIA por defecto',
                'company_id': company.id,
                'receiver_analytic_account_id': receiver.id,
            })
        receiver = self._ensure_receiver_analytic(company)
        if plan.receiver_analytic_account_id != receiver:
            plan.write({'receiver_analytic_account_id': receiver.id})

        vat_account = self._get_account(company, [('code', '=', '477000')], order='code')
        if not vat_account:
            vat_account = self._get_account(company, [
                '|', ('code', 'ilike', '477%'), ('name', 'ilike', 'iva'),
            ], order='code')
        debit_account = self._get_account(company, [('account_type', 'in', ('expense', 'expense_direct_cost'))])
        credit_account = self._get_account(company, [('account_type', '=', 'income')]) or debit_account

        # IVA 100%
        vat_line = plan.line_ids.filtered('is_vat_line')[:1]
        if vat_account:
            if vat_line:
                vat_line.write({
                    'is_vat_line': True,
                    'percentage': 100.0,
                    'debit_account_id': vat_account.id,
                    'credit_account_id': vat_account.id,
                    'debit_analytic_side': 'source',
                    'credit_analytic_side': 'receiver',
                })
            else:
                self.env['aicia.distribution.plan.line'].create({
                    'plan_id': plan.id,
                    'name': 'Redistribución IVA 100%',
                    'is_vat_line': True,
                    'percentage': 100.0,
                    'debit_account_id': vat_account.id,
                    'credit_account_id': vat_account.id,
                    'debit_analytic_side': 'source',
                    'credit_analytic_side': 'receiver',
                })

        # Base 10%
        base_line = plan.line_ids.filtered(lambda l: not l.is_vat_line)[:1]
        if debit_account and credit_account:
            if base_line:
                base_line.write({
                    'is_vat_line': False,
                    'percentage': 10.0,
                    'debit_account_id': debit_account.id,
                    'credit_account_id': credit_account.id,
                    'debit_analytic_side': 'source',
                    'credit_analytic_side': 'receiver',
                })
            else:
                self.env['aicia.distribution.plan.line'].create({
                    'plan_id': plan.id,
                    'name': 'Distribución base 10%',
                    'is_vat_line': False,
                    'percentage': 10.0,
                    'debit_account_id': debit_account.id,
                    'credit_account_id': credit_account.id,
                    'debit_analytic_side': 'source',    # Origen paga (Gasto/Reducción Ingreso)
                    'credit_analytic_side': 'receiver', # AICIA recibe (Ingreso)
                })
        return plan

    def _get_account(self, company, domain, order='id'):
        return self.env['account.account'].sudo().search(
            [('company_ids', 'in', company.id)] + domain,
            order=order,
            limit=1,
        )

    def _ensure_receiver_analytic(self, company):
        receiver = company.cash_distribution_receiver_analytic_id
        if receiver:
            return receiver
        receiver = self.env['account.analytic.account'].sudo().search([
            ('company_id', '=', company.id),
            ('name', 'ilike', 'aicia'),
        ], limit=1)
        if receiver:
            company.sudo().write({'cash_distribution_receiver_analytic_id': receiver.id})
            return receiver
        analytic_plan = self.env['account.analytic.plan'].sudo().search([], limit=1)
        receiver = self.env['account.analytic.account'].sudo().create({
            'name': 'AICIA - Receptora Distribución',
            'company_id': company.id,
            'plan_id': analytic_plan.id if analytic_plan else False,
        })
        company.sudo().write({'cash_distribution_receiver_analytic_id': receiver.id})
        return receiver

