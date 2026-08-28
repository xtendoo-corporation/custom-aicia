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
            # Si hay un plan en el pago, permitimos UserError para avisar al usuario.
            # En caso de error inesperado de red/sistema, sí capturamos para no romper Odoo,
            # pero los errores funcionales (UserError) llegarán a pantalla.
            from odoo.exceptions import UserError
            try:
                move = rec._process_cash_distribution()
                if move:
                    rec.distribution_move_id = move.id
            except UserError:
                raise
            except Exception as e:
                _logger.exception(
                    "Error crítico al procesar distribución para conciliación id=%s: %s",
                    rec.id, str(e)
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
        from odoo.exceptions import UserError

        # Prioridad 1: plan desde el pago
        payment = (self.credit_move_id.payment_id or self.debit_move_id.payment_id)
        payment_plan = payment.distribution_plan_id if payment else None


        invoice = self._find_invoice_move()
        if not invoice:
            return

        ratio = self._calc_payment_ratio(invoice)
        if not ratio:
            return

        all_lines = []
        applied_plans = self.env['aicia.distribution.plan']
        source_analytic_ids = set()
        any_analytic_found = False

        for analytic_id, base_amount, vat_amount in self._iter_analytic_amounts(invoice, ratio):
            any_analytic_found = True
            analytic = self.env['account.analytic.account'].browse(analytic_id)

            # Si el pago trae un plan, se considera override explícito
            if payment_plan and payment_plan.active:
                plan = payment_plan
            else:
                plan = analytic.distribution_plan_id

            if not plan or not plan.active:
                continue

            if plan.company_id and plan.company_id != self.company_id:
                continue

            # Validaciones críticas del plan
            if not plan.line_ids:
                raise UserError(
                    "El plan de distribución '%s' no tiene líneas de reparto configuradas." % plan.name
                )

            receiver_id = plan.get_receiver_analytic_id()
            if not receiver_id and plan._needs_receiver_analytic():
                raise UserError(
                    "El plan '%s' (o la compañía) no tiene configurada la Cuenta Analítica Receptora.\n\n"
                    "Configúrela en Contabilidad > Configuración > Ajustes > "
                    "Distribución de Cobros AICIA, o asigne una cuenta analítica fija "
                    "en cada línea del plan." % plan.name
                )

            lines = self._build_journal_lines(
                plan, analytic_id, base_amount, vat_amount, receiver_id, invoice
            )
            if lines:
                all_lines.extend(lines)
                applied_plans |= plan
                source_analytic_ids.add(analytic_id)

        # CASO CRÍTICO: El usuario puso un plan en el pago pero la factura no tiene analítica
        if payment_plan and not any_analytic_found:
            raise UserError(
                "Has seleccionado el plan '%s' en el pago, pero el asiento/factura '%s' "
                "no tiene ninguna distribución analítica configurada (en cabecera ni en líneas).\n\n"
                "La distribución no puede realizarse sin una base analítica de origen." % (
                    payment_plan.name, invoice.display_name
                )
            )

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
        """
        total_vat = sum(
            abs(line.balance)
            for line in invoice.line_ids
            if line.tax_line_id
        )
        _logger.debug(
            "[AICIA] _iter_analytic_amounts factura=%s ratio=%s total_vat=%s",
            invoice.name, ratio, total_vat,
        )

        def _get_analytic_ids(distribution):
            ids = set()
            if not distribution or not isinstance(distribution, dict):
                return ids
            for key in distribution:
                for part in str(key).split(','):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        ids.add(int(part))
                    except (ValueError, TypeError):
                        # Intentar buscar por código si no es un ID entero
                        account = self.env['account.analytic.account'].search([
                            ('code', '=', part),
                            '|', ('company_id', '=', self.company_id.id), ('company_id', '=', False)
                        ], limit=1)
                        if account:
                            ids.add(account.id)
            return ids

        # CASO 1: Analítica en cabecera de factura
        header_distribution = getattr(invoice, 'analytic_distribution', None)
        if header_distribution:
            total_base = sum(
                abs(l.balance)
                for l in invoice.invoice_line_ids
                if l.display_type not in ('line_section', 'line_note')
            )
            if not total_base:
                return

            analytic_ids = _get_analytic_ids(header_distribution)
            for acc_id in analytic_ids:
                # Nota: al usar múltiples analíticas en cabecera, Odoo reparte
                # según el porcentaje del JSON. Si hay varios en la misma clave,
                # simplificamos tomando el primero o asumiendo reparto equitativo
                # para este propósito, o mejor, seguimos la estructura del JSON.
                # Para simplificar y mantener compatibilidad, buscamos el porcentaje
                # original del JSON para este ID.
                pct = 0.0
                for key, val in header_distribution.items():
                    if str(acc_id) in str(key).split(','):
                        pct = val
                        break

                if not pct:
                    continue

                base_cobrada = total_base * pct / 100.0 * ratio
                vat_cobrado = total_vat * pct / 100.0 * ratio
                _logger.debug(
                    "[AICIA] CASO1 analytic_id=%s pct=%s base_cobrada=%s vat_cobrado=%s",
                    acc_id, pct, base_cobrada, vat_cobrado,
                )
                yield acc_id, base_cobrada, vat_cobrado
            return

        # CASO 2: Analíticas en líneas de factura
        analytic_base = {}
        total_base = 0.0
        for line in invoice.invoice_line_ids:
            if line.display_type in ('line_section', 'line_note'):
                continue
            balance = abs(line.balance)
            if not balance or not line.analytic_distribution:
                continue
            total_base += balance

            line_analytic_ids = _get_analytic_ids(line.analytic_distribution)
            for acc_id in line_analytic_ids:
                # Buscar porcentaje en el JSON de la línea
                pct = 0.0
                for key, val in line.analytic_distribution.items():
                    if str(acc_id) in str(key).split(','):
                        pct = val
                        break
                if pct:
                    analytic_base[acc_id] = analytic_base.get(acc_id, 0.0) + (balance * pct / 100.0)

        if not analytic_base:
            return

        for analytic_id, analytic_base_amount in analytic_base.items():
            base_cobrada = analytic_base_amount * ratio
            vat_cobrado = (
                total_vat * ratio * (analytic_base_amount / total_base)
                if total_base else 0.0
            )
            _logger.debug(
                "[AICIA] CASO2 analytic_id=%s analytic_base_amount=%s base_cobrada=%s vat_cobrado=%s",
                analytic_id, analytic_base_amount, base_cobrada, vat_cobrado,
            )
            yield analytic_id, base_cobrada, vat_cobrado
    # ── Construcción de líneas ────────────────────────────────────────────
    def _build_journal_lines(self, plan, source_analytic_id,
                              base_amount, vat_amount, receiver_analytic_id, invoice):
        """Construye pares debe/haber para cada linea del plan."""
        from odoo.exceptions import UserError
        lines = []
        currency = self.company_id.currency_id
        iva_line_detected = False
        iva_line_created = False

        _logger.debug(
            "[AICIA] _build_journal_lines plan=%s factura=%s base_amount=%s vat_amount=%s",
            plan.name, invoice.name, base_amount, vat_amount,
        )

        for plan_line in plan.line_ids:
            debit_account = plan_line.debit_account_id
            credit_account = plan_line.credit_account_id

            if plan_line.is_vat_line:
                iva_line_detected = True
                if not vat_amount:
                    _logger.warning(
                        "[AICIA] Línea IVA '%s' del plan '%s': vat_amount es 0 para factura %s. "
                        "Comprueba que la factura tenga líneas de impuesto (tax_line_id).",
                        plan_line.name, plan.name, invoice.name,
                    )
                # Usamos el porcentaje configurado en la línea (ej: 100%)
                amount = vat_amount * plan_line.percentage / 100.0
                vat_account = plan_line.get_effective_vat_account(invoice)
                if vat_account:
                    debit_account = vat_account
                    credit_account = vat_account
                _logger.debug(
                    "[AICIA] Línea IVA '%s': porcentaje=%s vat_amount=%s => amount=%s cuenta=%s",
                    plan_line.name, plan_line.percentage, vat_amount, amount,
                    debit_account.code if debit_account else 'N/A',
                )
            else:
                # Aplicamos el porcentaje configurado sobre la base imponible cobrada
                amount = base_amount * plan_line.percentage / 100.0
                _logger.debug(
                    "[AICIA] Línea venta '%s': porcentaje=%s base_amount=%s => amount=%s",
                    plan_line.name, plan_line.percentage, base_amount, amount,
                )

            amount = currency.round(amount)
            if amount == 0:
                _logger.debug(
                    "[AICIA] Línea '%s' del plan '%s' omitida por importe cero.",
                    plan_line.name, plan.name,
                )
                continue

            if plan_line.is_vat_line:
                iva_line_created = True

            debit_analytic = plan_line._get_debit_analytic_id(
                source_analytic_id, receiver_analytic_id
            )
            credit_analytic = plan_line._get_credit_analytic_id(
                source_analytic_id, receiver_analytic_id
            )
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

        # Si hay línea de IVA en el plan pero no se ha creado ningún apunte de IVA, lanzar error
        if iva_line_detected and not iva_line_created:
            raise UserError(
                "No se ha podido realizar el reparto del IVA para la factura '%s'.\n\n"
                "Causa probable: la factura no tiene líneas de impuesto (IVA) o el "
                "importe de IVA calculado es cero.\n\n"
                "Revise los logs del servidor para más detalle (busque '[AICIA]')." % invoice.name
            )
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

