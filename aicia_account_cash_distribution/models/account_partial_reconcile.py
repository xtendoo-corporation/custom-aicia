# -*- coding: utf-8 -*-
"""
Motor de distribución contable AICIA por criterio de caja.
Trigger: account.partial.reconcile — cada vez que se concilia (parcial o total)
una línea de pago con una línea de factura de cliente.
Reversión:
Al eliminar la conciliación (unlink) -> borrar el asiento y el log.
"""
import logging
from odoo import models, fields, api
_logger = logging.getLogger(__name__)
class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'
    distribution_move_ids = fields.One2many(
        'aicia.distribution.move',
        'partial_reconcile_id',
        string='Distribuciones generadas',
    )
    # ── Hooks ORM ─────────────────────────────────────────────────────────
    @api.model
    def create(self, vals):
        reconciles = super().create(vals)
        for rec in reconciles:
            try:
                rec._process_cash_distribution()
            except Exception:
                _logger.exception(
                    "Error al procesar distribución para reconciliación id=%s", rec.id
                )
        return reconciles
    def unlink(self):
        for rec in self:
            rec._reverse_cash_distribution()
        return super().unlink()
    # ── Entry point ───────────────────────────────────────────────────────
    def _process_cash_distribution(self):
        """Punto de entrada principal. Procesa todos los planes activos."""
        self.ensure_one()
        if not self.company_id.cash_distribution_active:
            return
        invoice = self._find_invoice_move()
        if not invoice:
            return
        ratio = self._calc_payment_ratio(invoice)
        if not ratio:
            return
        plans = self._get_active_plans()
        if not plans:
            return
        all_lines = []
        applied_plans = self.env['aicia.distribution.plan']
        for analytic_id, base_amount, vat_amount in self._iter_analytic_amounts(invoice, ratio):
            for plan in plans:
                if not plan.matches_analytic(analytic_id):
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
        if not all_lines:
            return
        move = self._create_distribution_move(invoice, all_lines)
        if not move:
            return
        self.env['aicia.distribution.move'].create({
            'partial_reconcile_id': self.id,
            'move_id': move.id,
            'amount_total': move.amount_total,
            'applied_plan_ids': [(6, 0, applied_plans.ids)],
        })
    def _reverse_cash_distribution(self):
        """Reversión: cancela asientos y elimina logs."""
        for rec in self:
            for dist_move in rec.distribution_move_ids:
                account_move = dist_move.move_id
                # Primero eliminar el log (FK -> account_move)
                dist_move.unlink()
                # Luego cancelar y eliminar el asiento contable
                if account_move.exists():
                    if account_move.state == 'posted':
                        account_move.button_draft()
                    account_move.button_cancel()
                    account_move.unlink()
    # ── Localización de factura ──────────────────────────────────────────
    def _find_invoice_move(self):
        """Devuelve la factura de cliente relacionada (out_invoice/out_refund)."""
        self.ensure_one()
        moves = [self.debit_move_id.move_id, self.credit_move_id.move_id]
        invoice = next((m for m in moves if m.move_type in ('out_invoice', 'out_refund')), None)
        return invoice if invoice and invoice.state == 'posted' else None
    def _calc_payment_ratio(self, invoice):
        """Devuelve el ratio cobrado (rec.amount / total)."""
        self.ensure_one()
        total = abs(invoice.amount_total_signed)
        if total == 0:
            return 0.0
        return min(self.amount / total, 1.0)
    def _get_active_plans(self):
        """Devuelve todos los planes activos de la compañía."""
        return self.env['aicia.distribution.plan'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ])
    # ── Iterador de importes por analítica ────────────────────────────────
    def _iter_analytic_amounts(self, invoice, ratio):
        """
        Genera tuplas (analytic_id, base_cobrada, vat_cobrado).
        PRIORIDAD:
        1. analytic_distribution en cabecera de factura
        2. analytic_distribution en lineas de factura
        """
        total_vat = sum(
            abs(l.balance)
            for l in invoice.line_ids
            if l.tax_line_id and not l.display_type
        )
        # CASO 1: Analitica en cabecera de factura
        if invoice.analytic_distribution:
            total_base = sum(
                abs(l.balance)
                for l in invoice.invoice_line_ids
                if l.display_type not in ('line_section', 'line_note')
            )
            if not total_base:
                return
            for acc_str, pct in invoice.analytic_distribution.items():
                try:
                    acc_id = int(acc_str.split(',')[0])
                except (ValueError, IndexError):
                    continue
                base_cobrada = total_base * pct / 100.0 * ratio
                vat_cobrado = total_vat * pct / 100.0 * ratio
                yield acc_id, base_cobrada, vat_cobrado
            return
        # CASO 2: Analiticas en lineas de factura
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
            if plan_line.is_vat_line:
                amount = vat_amount
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
                'account_id': plan_line.debit_account_id.id,
                'debit': amount,
                'credit': 0.0,
                'analytic_distribution': {str(debit_analytic): 100},
                'partner_id': invoice.partner_id.id,
            })
            lines.append({
                'name': label,
                'account_id': plan_line.credit_account_id.id,
                'debit': 0.0,
                'credit': amount,
                'analytic_distribution': {str(credit_analytic): 100},
                'partner_id': invoice.partner_id.id,
            })
        return lines
    def _create_distribution_move(self, invoice, line_vals_list):
        """Crea y publica el asiento de distribución."""
        journal = self.company_id.cash_distribution_journal_id
        if not journal:
            _logger.warning(
                "Sin diario de distribución configurado en compañía %s",
                self.company_id.name,
            )
            return None
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': f'Distribución {invoice.name}',
            'line_ids': [(0, 0, vals) for vals in line_vals_list],
        })
        move.action_post()
        return move
