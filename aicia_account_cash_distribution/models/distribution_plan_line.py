# -*- coding: utf-8 -*-
from odoo import models, fields


class AiciaDistributionPlanLine(models.Model):
    """
    Línea de un plan de distribución.
    Cada línea define UN reparto contable:
    Tipo IVA (is_vat_line=True):
        El importe se calcula automáticamente como la fracción proporcional del
        IVA cobrado correspondiente a la analítica origen de esta línea.
        Ejemplo: Debe 477 (origen) / Haber 477 (AICIA)
    Tipo A (is_vat_line=False, cuentas iguales):
        Porcentaje sobre la base imponible cobrada.
        Ejemplo: Debe 700 (AICIA) / Haber 700 (origen) — 6%
    Tipo B (is_vat_line=False, cuentas distintas):
        Porcentaje sobre la base imponible cobrada con cuenta de proveedor/acreedor.
        Ejemplo: Debe 401200 (AICIA) / Haber 700 (origen) — 3%
    El campo `debit_analytic_side` / `credit_analytic_side` determina a qué proyecto
    (origen o AICIA receptor) se imputa cada línea del asiento.
    """
    _name = 'aicia.distribution.plan.line'
    _description = 'Línea de Plan de Distribución AICIA'
    _order = 'sequence, id'
    _check_company_auto = True

    plan_id = fields.Many2one(
        'aicia.distribution.plan',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Descripción', required=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)

    # ── Tipo: IVA automático vs porcentaje manual ─────────────────────────

    is_vat_line = fields.Boolean(
        string='Redistribución de IVA',
        default=False,
        help="Si activo: el importe se calcula del IVA proporcional cobrado.\n"
             "El campo Porcentaje se ignora.",
    )
    percentage = fields.Float(
        string='Porcentaje (%)',
        digits=(16, 4),
        help="Porcentaje sobre la base imponible cobrada.\n"
             "Ignorado en líneas de IVA automático.",
    )

    # ── Cuenta y lado analítico del DEBE ──────────────────────────────────

    debit_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Debe',
        required=True,
        check_company=True,
    )
    debit_analytic_side = fields.Selection(
        [('source', 'Analítica Origen'), ('receiver', 'Analítica Receptora AICIA')],
        string='Analítica Debe',
        required=True,
        default='source',
        help="A qué proyecto se imputa el apunte al debe.",
    )

    # ── Cuenta y lado analítico del HABER ─────────────────────────────────

    credit_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Haber',
        required=True,
        check_company=True,
    )
    credit_analytic_side = fields.Selection(
        [('source', 'Analítica Origen'), ('receiver', 'Analítica Receptora AICIA')],
        string='Analítica Haber',
        required=True,
        default='receiver',
        help="A qué proyecto se imputa el apunte al haber.",
    )

