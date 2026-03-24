# -*- coding: utf-8 -*-
"""
Motor de distribución contable AICIA por criterio de caja.
Trigger: account.partial.reconcile — cada vez que se concilia (parcial o total)
una línea de pago con una línea de factura de cliente.
Reversión:
Al eliminar la conciliación (unlink) -> borrar el asiento generado.
"""
import logging
from odoo import models, fields, api
_logger = logging.getLogger(__name__)
class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    distribution_move_id = fields.Many2one(
        'account.move',
        string='Asiento de distribución',
        copy=False,
        ondelete='set null',
        domain=[('is_cash_distribution_move', '=', True)],
    )
    # ── Hooks ORM ─────────────────────────────────────────────────────────
    @api.model
    def create(self, vals):
        reconciles = super().create(vals)
        for rec in reconciles:
            try:
                move = rec._process_cash_distribution()
                if move:
                    rec.distribution_move_id = move.id
            except Exception:
                _logger.exception(
                    "Error al procesar distribución para conciliación id=%s", rec.id
                )
        return reconciles
    def unlink(self):
        for rec in self:
            rec._reverse_cash_distribution()
        return super().unlink()
    # ── Entry point ───────────────────────────────────────────────────────
    def _process_cash_distribution(self):
        """
        Punto de entrada principal.
        Prioridad para obtener el plan de distribución:
          1. Plan asignado directamente en el pago (account.payment.distribution_plan_id)
          2. Plan asignado en la cuenta analítica de la factura
        """
        self.ensure_one()
        if not self.company_id.cash_distribution_active:
            payment = self.credit_move_id.payment_id or self.debit_move_id.payment_id
            if payment and payment.distribution_plan_id:
                _logger.info(
                    "Distribución omitida para conciliación id=%s: la compañía %s tiene desactivada la distribución de cobros.",
                    self.id,
                    self.company_id.display_name,
                )
            return
        invoice = self._find_invoice_move()
        if not invoice:
            return
        ratio = self._calc_payment_ratio(invoice)
        if not ratio:
            return

        # Prioridad 1: plan desde el pago
        payment = (self.credit_move_id.payment_id or self.debit_move_id.payment_id)
        payment_plan = payment.distribution_plan_id if payment else None

        all_lines = []
        applied_plans = self.env['aicia.distribution.plan']
        source_analytic_ids = set()

        for analytic_id, base_amount, vat_amount in self._iter_analytic_amounts(invoice, ratio):
            analytic = self.env['account.analytic.account'].browse(analytic_id)

            # Si el pago trae un plan, se considera override explícito y se aplica
            # siempre sobre las analíticas detectadas en la factura, aunque el plan
            # tenga analíticas origen distintas configuradas.
            if payment_plan and payment_plan.active:
                plan = payment_plan
            else:
                plan = analytic.distribution_plan_id

            if not plan or not plan.active:
                continue
            if plan.company_id and plan.company_id != self.company_id:
                continue
            receiver_id = plan.get_receiver_analytic_id()
            if not receiver_id:
                continue
            lines = self._build_journal_lines(
                plan, analytic_id, base_amount, vat_amount, receiver_id, invoice
            )
            if lines:
                all_lines.extend(lines)
                applied_plans |= plan
                source_analytic_ids.add(analytic_id)

        if not all_lines:
            return
        move = self._create_distribution_move(
            invoice,
            all_lines,
            payment,
            applied_plans=applied_plans,
            source_analytic_ids=source_analytic_ids,
        )
        return move
    def _reverse_cash_distribution(self):
        """Reversión: cancela y elimina el asiento de distribución."""
        for rec in self:
            move = rec.distribution_move_id
            if not move:
                continue
            if move.exists():
                if move.state == 'posted':
                    move.button_draft()
                move.unlink()
    # ── Localización de factura ──────────────────────────────────────────
    def _find_invoice_move(self):
        """Devuelve la factura de venta relacionada (solo out_invoice)."""
        self.ensure_one()
        moves = [self.debit_move_id.move_id, self.credit_move_id.move_id]
        invoice = next((m for m in moves if m.move_type == 'out_invoice'), None)
        return invoice if invoice and invoice.state == 'posted' else None
    def _calc_payment_ratio(self, invoice):
        """Devuelve el ratio cobrado (rec.amount / total)."""
        self.ensure_one()
        total = abs(invoice.amount_total_signed)
        if total == 0:
            return 0.0
        return min(self.amount / total, 1.0)
    # ── Localización de factura ──────────────────────────────────────────
    def _iter_analytic_amounts(self, invoice, ratio):
        """
        Genera tuplas (analytic_id, base_cobrada, vat_cobrado).
        PRIORIDAD:
        1. analytic_distribution en cabecera de factura (si existe el campo)
        2. analytic_distribution en lineas de factura
        Nota: en Odoo 19 el campo analytic_distribution puede no existir
        en account.move (sólo en account.move.line), por eso se usa getattr.
        """
        total_vat = sum(
            abs(line.balance)
            for line in invoice.line_ids
            if line.tax_line_id
        )
        # CASO 1: Analítica en cabecera de factura (Odoo 16/17, getattr seguro)
        header_analytic = getattr(invoice, 'analytic_distribution', None)
        if header_analytic:
            total_base = sum(
                abs(l.balance)
                for l in invoice.invoice_line_ids
                if l.display_type not in ('line_section', 'line_note')
            )
            if not total_base:
                return
            for acc_str, pct in header_analytic.items():
                try:
                    acc_id = int(acc_str.split(',')[0])
                except (ValueError, IndexError):
                    continue
                base_cobrada = total_base * pct / 100.0 * ratio
                vat_cobrado = total_vat * pct / 100.0 * ratio
                yield acc_id, base_cobrada, vat_cobrado
            return
        # CASO 2: Analíticas en lineas de factura
        analytic_base = {}
        total_base = 0.0
        for line in invoice.invoice_line_ids:
            if line.display_type in ('line_section', 'line_note'):
                continue
            balance = abs(line.balance)
            if not balance or not line.analytic_distribution:
                continue
            total_base += balance
            for acc_str, pct in line.analytic_distribution.items():
                try:
                    acc_id = int(acc_str.split(',')[0])
                except (ValueError, IndexError):
                    continue
                analytic_base[acc_id] = analytic_base.get(acc_id, 0.0) + balance * pct / 100.0
        if not analytic_base:
            return
        for analytic_id, analytic_base_amount in analytic_base.items():
            base_cobrada = analytic_base_amount * ratio
            vat_cobrado = (
                total_vat * ratio * (analytic_base_amount / total_base)
                if total_base else 0.0
            )
            yield analytic_id, base_cobrada, vat_cobrado
    # ── Construcción de líneas ────────────────────────────────────────────
    def _build_journal_lines(self, plan, source_analytic_id,
                              base_amount, vat_amount, receiver_analytic_id, invoice):
        """Construye pares debe/haber para cada linea del plan."""
        lines = []
        currency = self.company_id.currency_id
        for plan_line in plan.line_ids:
            debit_account = plan_line.debit_account_id
            credit_account = plan_line.credit_account_id
            if plan_line.is_vat_line:
                amount = vat_amount
                vat_account = plan_line.get_effective_vat_account(invoice)
                if vat_account:
                    debit_account = vat_account
                    credit_account = vat_account
            else:
                amount = base_amount * plan_line.percentage / 100.0
            amount = currency.round(amount)
            if amount == 0:
                continue
            debit_analytic = (source_analytic_id
                              if plan_line.debit_analytic_side == 'source'
                              else receiver_analytic_id)
            credit_analytic = (source_analytic_id
                               if plan_line.credit_analytic_side == 'source'
                               else receiver_analytic_id)
            label = f'Distr: {invoice.name} - {plan.name} - {plan_line.name}'
            lines.append({
                'name': label,
                'account_id': debit_account.id,
                'debit': amount,
                'credit': 0.0,
                'analytic_distribution': {str(debit_analytic): 100},
                'partner_id': invoice.partner_id.id,
            })
            lines.append({
                'name': label,
                'account_id': credit_account.id,
                'debit': 0.0,
                'credit': amount,
                'analytic_distribution': {str(credit_analytic): 100},
                'partner_id': invoice.partner_id.id,
            })
        return lines
    def _create_distribution_move(self, invoice, line_vals_list, payment, applied_plans=None, source_analytic_ids=None):
        """Crea y publica el asiento de distribución."""
        applied_plans = applied_plans or self.env['aicia.distribution.plan']
        source_analytic_ids = source_analytic_ids or set()
        journal = self._get_distribution_journal()
        if not journal:
            _logger.warning(
                "Sin diario general disponible para distribución en compañía %s",
                self.company_id.name,
            )
            return None
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'company_id': self.company_id.id,
            'partner_id': invoice.partner_id.id,
            'date': fields.Date.context_today(self),
            'ref': f'Distribución {invoice.name}',
            'is_cash_distribution_move': True,
            'distribution_partial_reconcile_id': self.id,
            'distribution_payment_id': payment.id if payment else False,
            'distribution_source_analytic_ids': [(6, 0, list(source_analytic_ids))],
            'distribution_applied_plan_ids': [(6, 0, applied_plans.ids)],
            'line_ids': [(0, 0, vals) for vals in line_vals_list],
        })
        move.action_post()
        return move

    def _get_distribution_journal(self):
        """Obtiene el diario configurado o hace fallback al primer diario general."""
        self.ensure_one()
        return (
            self.company_id.cash_distribution_journal_id
            or self.env['account.journal'].search([
                ('company_id', '=', self.company_id.id),
                ('type', '=', 'general'),
            ], limit=1)
        )

