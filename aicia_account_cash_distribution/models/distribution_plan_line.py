# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_ANALYTIC_SIDE_SELECTION = [
    ('source', 'Origen'),
    ('fixed', 'Fija'),
]


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
    (origen, AICIA receptor, o una cuenta analítica fija específica)
    se imputa cada línea del asiento.
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
        _ANALYTIC_SIDE_SELECTION,
        string='Analítica Debe',
        required=True,
        default='source',
        help=(
            "A qué proyecto se imputa el apunte al debe:\n"
            "• Origen — la cuenta analítica de la factura cobrada.\n"
            "• Fija — una cuenta analítica concreta que eliges tú."
        ),
    )
    debit_analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Cuenta Analítica Debe',
        check_company=True,
        ondelete='restrict',
        help="Cuenta analítica específica para el apunte al debe.\n"
             "Solo aplica cuando 'Analítica Debe' = 'Fija'.",
    )

    # ── Cuenta y lado analítico del HABER ─────────────────────────────────

    credit_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Haber',
        required=True,
        check_company=True,
    )
    credit_analytic_side = fields.Selection(
        _ANALYTIC_SIDE_SELECTION,
        string='Analítica Haber',
        required=True,
        default='source',
        help=(
            "A qué proyecto se imputa el apunte al haber:\n"
            "• Origen — la cuenta analítica de la factura cobrada.\n"
            "• Fija — una cuenta analítica concreta que eliges tú."
        ),
    )
    credit_analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Cuenta Analítica Haber',
        check_company=True,
        ondelete='restrict',
        help="Cuenta analítica específica para el apunte al haber.\n"
             "Solo aplica cuando 'Analítica Haber' = 'Fija'.",
    )

    # ── Hooks ORM ─────────────────────────────────────────────────────────

    def _register_hook(self):
        res = super()._register_hook()
        self._migrate_receiver_to_fixed()
        self._normalize_legacy_vat_lines()
        return res

    # ── Cuenta IVA efectiva ───────────────────────────────────────────────

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

    # ── Helpers de resolución analítica ──────────────────────────────────

    def _get_debit_analytic_id(self, source_analytic_id, receiver_analytic_id):
        """
        Devuelve el ID de cuenta analítica efectivo para el apunte al debe.
          'source' → analítica de la factura origen
          'fixed'  → la cuenta analítica fija configurada en esta línea
                     (receiver_analytic_id actúa de fallback si no hay cuenta fija)
        """
        self.ensure_one()
        if self.debit_analytic_side == 'fixed':
            return self.debit_analytic_account_id.id or receiver_analytic_id
        return source_analytic_id  # 'source'

    def _get_credit_analytic_id(self, source_analytic_id, receiver_analytic_id):
        """
        Devuelve el ID de cuenta analítica efectivo para el apunte al haber.
          'source' → analítica de la factura origen
          'fixed'  → la cuenta analítica fija configurada en esta línea
                     (receiver_analytic_id actúa de fallback si no hay cuenta fija)
        """
        self.ensure_one()
        if self.credit_analytic_side == 'fixed':
            return self.credit_analytic_account_id.id or receiver_analytic_id
        return source_analytic_id  # 'source'

    def _vat_sides_are_identical(self):
        """
        Retorna True si ambos lados analíticos apuntarían siempre al mismo proyecto,
        condición que está prohibida en líneas de IVA.
        Casos idénticos:
          - ambos 'source'
          - ambos 'receiver'
          - ambos 'fixed' apuntando a la misma cuenta analítica
        """
        self.ensure_one()
        d, c = self.debit_analytic_side, self.credit_analytic_side
        if d != c:
            return False
        if d == 'fixed':
            return self.debit_analytic_account_id == self.credit_analytic_account_id
        return True  # both 'source' or both 'receiver'

    # ── Validaciones ──────────────────────────────────────────────────────

    @api.constrains(
        'debit_analytic_side', 'debit_analytic_account_id',
        'credit_analytic_side', 'credit_analytic_account_id',
    )
    def _check_fixed_analytic_required(self):
        for line in self:
            if line.debit_analytic_side == 'fixed' and not line.debit_analytic_account_id:
                raise ValidationError(_(
                    "Línea '%s': al seleccionar 'Fija' en el Debe, "
                    "debes indicar la cuenta analítica concreta."
                ) % line.name)
            if line.credit_analytic_side == 'fixed' and not line.credit_analytic_account_id:
                raise ValidationError(_(
                    "Línea '%s': al seleccionar 'Fija' en el Haber, "
                    "debes indicar la cuenta analítica concreta."
                ) % line.name)

    @api.constrains(
        'is_vat_line',
        'debit_account_id',
        'credit_account_id',
        'debit_analytic_side',
        'credit_analytic_side',
        'debit_analytic_account_id',
        'credit_analytic_account_id',
    )
    def _check_vat_line_configuration(self):
        for line in self:
            if not line.is_vat_line:
                continue
            if line.debit_account_id != line.credit_account_id:
                raise ValidationError(_(
                    "Las líneas marcadas como redistribución de IVA deben usar la misma cuenta en el Debe y en el Haber."
                ))
            if line._vat_sides_are_identical():
                raise ValidationError(_(
                    "Las líneas marcadas como redistribución de IVA deben imputar Debe y Haber "
                    "en lados analíticos distintos (no pueden apuntar al mismo proyecto)."
                ))

    # ── Migración de datos legacy ─────────────────────────────────────────

    @api.model
    def _migrate_receiver_to_fixed(self):
        """
        Migración automática (única ejecución efectiva): convierte registros
        legacy con debit/credit_analytic_side == 'receiver' a 'fixed',
        asignando la cuenta analítica receptora del plan correspondiente.
        """
        legacy_lines = self.with_context(active_test=False).search([
            '|',
            ('debit_analytic_side', '=', 'receiver'),
            ('credit_analytic_side', '=', 'receiver'),
        ])
        for line in legacy_lines:
            receiver_id = line.plan_id.get_receiver_analytic_id()
            vals = {}
            if line.debit_analytic_side == 'receiver':
                vals['debit_analytic_side'] = 'fixed'
                if receiver_id:
                    vals['debit_analytic_account_id'] = receiver_id
            if line.credit_analytic_side == 'receiver':
                vals['credit_analytic_side'] = 'fixed'
                if receiver_id:
                    vals['credit_analytic_account_id'] = receiver_id
            if vals:
                line.write(vals)
                _logger.info(
                    "[AICIA] Línea migrada receiver→fixed (id=%s, plan=%s): %s",
                    line.id, line.plan_id.display_name, vals,
                )

    # ── IVA automático: normalización de líneas legacy ─────────────────────

    @api.model
    def _normalize_legacy_vat_lines(self):
        """Alinea las cuentas contables de las líneas IVA heredadas."""
        vat_lines = self.with_context(active_test=False).search([('is_vat_line', '=', True)])
        for line in vat_lines:
            target_account = line._get_preferred_vat_account()
            vals = {}
            if target_account and line.debit_account_id != target_account:
                vals['debit_account_id'] = target_account.id
            if target_account and line.credit_account_id != target_account:
                vals['credit_account_id'] = target_account.id
            if vals:
                line.write(vals)
                _logger.warning(
                    "Línea IVA legacy normalizada (id=%s, plan=%s): %s",
                    line.id,
                    line.plan_id.display_name,
                    vals,
                )
