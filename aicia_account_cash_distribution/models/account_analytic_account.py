# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, _
_logger = logging.getLogger(__name__)
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
    # ── Margen del Proyecto (Grupo 7 - Grupo 6) ───────────────────────────
    project_income = fields.Float(
        compute='_compute_project_margin',
        string='Ingresos (Grupo 7)',
        digits='Account',
        help="Suma de importes analíticos en cuentas del grupo 7 (ventas e ingresos).",
    )
    project_expense = fields.Float(
        compute='_compute_project_margin',
        string='Gastos (Grupo 6)',
        digits='Account',
        help="Suma de importes analíticos en cuentas del grupo 6 (compras y gastos).",
    )
    project_margin = fields.Float(
        compute='_compute_project_margin',
        string='Margen del Proyecto',
        digits='Account',
        help="Diferencia entre los ingresos (grupo 7) y los gastos (grupo 6) de esta analítica.",
    )
    project_margin_line_count = fields.Integer(
        compute='_compute_project_margin',
        string='Apuntes de Margen',
    )
    def _compute_distribution_move_count(self):
        for account in self:
            account.distribution_move_count = self.env['account.move'].search_count([
                ('is_cash_distribution_move', '=', True),
                ('distribution_source_analytic_ids', 'in', account.ids),
            ])
    def _compute_project_margin(self):
        """
        Calcula el margen del proyecto usando account.analytic.line.
        account_id es FK directa al proyecto; amount ya incluye el % analítico.
        Convención: grupo 7 crédito => aal.amount > 0 (ingreso)
                    grupo 6 débito  => aal.amount < 0 (gasto, invertimos signo)
        Savepoints para no abortar la transacción en caso de error SQL.
        """
        for account in self:
            sp = 'sp_margin_%d' % account.id
            self.env.cr.execute('SAVEPOINT "%s"' % sp)
            try:
                self.env.cr.execute("""
                    SELECT
                        COALESCE(SUM(
                            CASE WHEN aa.code LIKE '7%%'
                            THEN aal.amount
                            ELSE 0 END
                        ), 0.0) AS income,
                        COALESCE(SUM(
                            CASE WHEN aa.code LIKE '6%%'
                            THEN -aal.amount
                            ELSE 0 END
                        ), 0.0) AS expense,
                        COUNT(aal.id) AS cnt
                    FROM account_analytic_line aal
                    JOIN account_move_line aml ON aml.id = aal.move_line_id
                    JOIN account_account aa   ON aa.id  = aml.account_id
                    JOIN account_move am      ON am.id  = aml.move_id
                    WHERE aal.account_id = %(account_id)s
                      AND (aa.code LIKE '6%%' OR aa.code LIKE '7%%')
                      AND am.state = 'posted'
                """, {'account_id': account.id})
                row = self.env.cr.fetchone()
                income  = float(row[0]) if row and row[0] is not None else 0.0
                expense = float(row[1]) if row and row[1] is not None else 0.0
                account.project_income = income
                account.project_expense = expense
                account.project_margin = income - expense
                account.project_margin_line_count = int(row[2]) if row and row[2] is not None else 0
                self.env.cr.execute('RELEASE SAVEPOINT "%s"' % sp)
            except Exception:
                _logger.exception(
                    "Error calculando margen del proyecto para analítica id=%s", account.id
                )
                self.env.cr.execute('ROLLBACK TO SAVEPOINT "%s"' % sp)
                self.env.cr.execute('RELEASE SAVEPOINT "%s"' % sp)
                account.project_income = 0.0
                account.project_expense = 0.0
                account.project_margin = 0.0
                account.project_margin_line_count = 0
    def action_view_project_margin_lines(self):
        """
        Abre los apuntes contables de grupos 6 y 7 imputados a esta analítica,
        obtenidos vía account.analytic.line para máxima fiabilidad.
        """
        self.ensure_one()
        sp = 'sp_margin_lines_%d' % self.id
        self.env.cr.execute('SAVEPOINT "%s"' % sp)
        try:
            self.env.cr.execute("""
                SELECT DISTINCT aml.id
                FROM account_analytic_line aal
                JOIN account_move_line aml ON aml.id = aal.move_line_id
                JOIN account_account aa   ON aa.id  = aml.account_id
                JOIN account_move am      ON am.id  = aml.move_id
                WHERE aal.account_id = %(account_id)s
                  AND (aa.code LIKE '6%%' OR aa.code LIKE '7%%')
                  AND am.state = 'posted'
            """, {'account_id': self.id})
            line_ids = [row[0] for row in self.env.cr.fetchall()]
            self.env.cr.execute('RELEASE SAVEPOINT "%s"' % sp)
        except Exception:
            _logger.exception(
                "Error obteniendo apuntes de margen para analítica id=%s", self.id
            )
            self.env.cr.execute('ROLLBACK TO SAVEPOINT "%s"' % sp)
            self.env.cr.execute('RELEASE SAVEPOINT "%s"' % sp)
            line_ids = []
        return {
            'type': 'ir.actions.act_window',
            'name': _('Margen Analítico: %s') % self.name,
            'res_model': 'account.move.line',
            'view_mode': 'list,pivot,graph',
            'domain': [('id', 'in', line_ids)],
            'context': {
                'search_default_group_by_account': 1,
                'expand': 1,
            },
        }
