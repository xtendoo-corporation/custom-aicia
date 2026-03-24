# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


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

    def _register_hook(self):
        res = super()._register_hook()
        self._normalize_legacy_vat_lines()
        return res

    def _get_preferred_vat_account(self):
        self.ensure_one()
        candidate_accounts = self.debit_account_id | self.credit_account_id
        vat_accounts = candidate_accounts.filtered(
            lambda account: (account.code or '').startswith('477')
            or 'iva' in (account.name or '').lower()
        )
        return vat_accounts[:1] or self.credit_account_id or self.debit_account_id

    def get_effective_vat_account(self, invoice):
        self.ensure_one()
        invoice_tax_accounts = invoice.line_ids.filtered('tax_line_id').mapped('account_id')
        if len(invoice_tax_accounts) == 1:
            return invoice_tax_accounts
        if len(invoice_tax_accounts) > 1:
            _logger.warning(
                "Factura %s con múltiples cuentas fiscales %s; se usará la cuenta IVA preferida configurada en la línea %s.",
                invoice.name,
                invoice_tax_accounts.mapped('code'),
                self.display_name,
            )
        return self._get_preferred_vat_account()

    @api.model
    def _normalize_legacy_vat_lines(self):
        vat_lines = self.with_context(active_test=False).search([('is_vat_line', '=', True)])
        for line in vat_lines:
            target_account = line._get_preferred_vat_account()
            vals = {}
            if target_account and line.debit_account_id != target_account:
                vals['debit_account_id'] = target_account.id
            if target_account and line.credit_account_id != target_account:
                vals['credit_account_id'] = target_account.id
            if line.debit_analytic_side == line.credit_analytic_side:
                vals['credit_analytic_side'] = (
                    'source' if line.debit_analytic_side == 'receiver' else 'receiver'
                )
            if vals:
                line.write(vals)
                _logger.warning(
                    "Línea IVA legacy normalizada (id=%s, plan=%s): %s",
                    line.id,
                    line.plan_id.display_name,
                    vals,
                )

    @api.constrains(
        'is_vat_line',
        'debit_account_id',
        'credit_account_id',
        'debit_analytic_side',
        'credit_analytic_side',
    )
    def _check_vat_line_configuration(self):
        for line in self:
            if not line.is_vat_line:
                continue
            if line.debit_account_id != line.credit_account_id:
                raise ValidationError(_(
                    "Las líneas marcadas como redistribución de IVA deben usar la misma cuenta en el Debe y en el Haber."
                ))
            if line.debit_analytic_side == line.credit_analytic_side:
                raise ValidationError(_(
                    "Las líneas marcadas como redistribución de IVA deben imputar Debe y Haber en lados analíticos opuestos (Origen/AICIA)."
                ))

