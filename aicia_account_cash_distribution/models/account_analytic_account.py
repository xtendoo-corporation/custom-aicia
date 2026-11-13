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
        Calcula el margen del proyecto (Grupo 7 - Grupo 6).

        Notas de implementación Odoo 19:
        - account.account.code se almacena en columna 'code_store' (JSONB: {"company_id": "600000"})
          → se filtra con code_store::text LIKE '%": "6%' / '%": "7%'
        - analytic_distribution en account.move.line es JSONB
          → se usa el operador ? para comprobar si contiene la clave (ID analítica)
        - Savepoints para no abortar la transacción en caso de error SQL.
        """
        for account in self:
            sp = 'sp_margin_%d' % account.id
            self.env.cr.execute('SAVEPOINT "%s"' % sp)
            try:
                self.env.cr.execute("""
                    SELECT
                        COALESCE(SUM(
                            CASE WHEN aa.code_store::text LIKE '%%": "7%%'
                            THEN -(aml.balance)
                                 * COALESCE((aml.analytic_distribution->>%(aid)s)::numeric, 0)
                                 / 100.0
                            ELSE 0 END
                        ), 0.0) AS income,
                        COALESCE(SUM(
                            CASE WHEN aa.code_store::text LIKE '%%": "6%%'
                            THEN aml.balance
                                 * COALESCE((aml.analytic_distribution->>%(aid)s)::numeric, 0)
                                 / 100.0
                            ELSE 0 END
                        ), 0.0) AS expense,
                        COUNT(aml.id) AS cnt
                    FROM account_move_line aml
                    JOIN account_account aa ON aa.id = aml.account_id
                    JOIN account_move am    ON am.id = aml.move_id
                    WHERE aml.analytic_distribution ? %(aid)s
                      AND (   aa.code_store::text LIKE '%%": "6%%'
                           OR aa.code_store::text LIKE '%%": "7%%')
                      AND am.state = 'posted'
                """, {'aid': str(account.id)})
                row = self.env.cr.fetchone()
                income  = float(row[0]) if row and row[0] is not None else 0.0
                expense = float(row[1]) if row and row[1] is not None else 0.0
                account.project_income  = income
                account.project_expense = expense
                account.project_margin  = income - expense
                account.project_margin_line_count = int(row[2]) if row and row[2] is not None else 0
                self.env.cr.execute('RELEASE SAVEPOINT "%s"' % sp)
            except Exception:
                _logger.exception(
                    "Error calculando margen del proyecto para analítica id=%s", account.id
                )
                self.env.cr.execute('ROLLBACK TO SAVEPOINT "%s"' % sp)
                self.env.cr.execute('RELEASE SAVEPOINT "%s"' % sp)
                account.project_income  = 0.0
                account.project_expense = 0.0
                account.project_margin  = 0.0
                account.project_margin_line_count = 0
    def action_view_project_margin_lines(self):
        """
        Abre los apuntes contables de grupos 6 y 7 imputados a esta analítica.
        Usa la misma lógica SQL que _compute_project_margin.
        """
        self.ensure_one()
        sp = 'sp_margin_lines_%d' % self.id
        self.env.cr.execute('SAVEPOINT "%s"' % sp)
        try:
            self.env.cr.execute("""
                SELECT aml.id
                FROM account_move_line aml
                JOIN account_account aa ON aa.id = aml.account_id
                JOIN account_move am    ON am.id = aml.move_id
                WHERE aml.analytic_distribution ? %(aid)s
                  AND (   aa.code_store::text LIKE '%%": "6%%'
                       OR aa.code_store::text LIKE '%%": "7%%')
                  AND am.state = 'posted'
            """, {'aid': str(self.id)})
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
