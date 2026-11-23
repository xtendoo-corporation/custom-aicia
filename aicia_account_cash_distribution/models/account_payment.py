# -*- coding: utf-8 -*-
from odoo import api, models, fields


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    distribution_plan_id = fields.Many2one(
        'aicia.distribution.plan',
        string='Plan de Distribución',
        domain="[('company_id', '=', company_id)]",
        help="Plan de distribución que se ejecutará al conciliar este cobro con la factura.\n"
             "Se rellena automáticamente desde la analítica de la factura, "
             "pero puede modificarse antes de validar el pago.",
        tracking=True,
    )
    distribution_move_count = fields.Integer(
        compute='_compute_distribution_move_count',
        string='Distribuciones',
    )
    show_distribution_plan_id = fields.Boolean(
        compute='_compute_show_distribution_plan_id',
        string='Mostrar plan de distribución',
    )
    distribution_move_line_ids = fields.Many2many(
        'account.move.line',
        compute='_compute_distribution_move_line_ids',
        string='Líneas de Distribución',
    )

    def _compute_distribution_move_line_ids(self):
        for payment in self:
            payment.distribution_move_line_ids = self.env['account.move.line'].search([
                ('move_id.is_cash_distribution_move', '=', True),
                ('move_id.distribution_payment_id', '=', payment.id),
            ])

    def _compute_distribution_move_count(self):
        for payment in self:
            payment.distribution_move_count = self.env['account.move'].search_count([
                ('is_cash_distribution_move', '=', True),
                ('distribution_payment_id', '=', payment.id),
            ])

    def _compute_show_distribution_plan_id(self):
        for payment in self:
            source_moves = payment.invoice_ids or payment.reconciled_invoice_ids
            if source_moves:
                payment.show_distribution_plan_id = all(
                    move.move_type == 'out_invoice' for move in source_moves
                )
            else:
                payment.show_distribution_plan_id = (
                    payment.payment_type == 'inbound'
                    and payment.partner_type == 'customer'
                )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'distribution_plan_id' in fields_list and not vals.get('distribution_plan_id'):
            if self.env.context.get('active_model') == 'account.move':
                invoices = self.env['account.move'].browse(self.env.context.get('active_ids', []))
                plan = self._get_distribution_plan_from_invoices(invoices)
                if plan:
                    vals['distribution_plan_id'] = plan.id
        return vals

    @api.model
    def _extract_analytic_ids_from_distribution(self, distribution):
        analytic_ids = set()
        analytic_codes = set()
        if not distribution:
            return analytic_ids, analytic_codes

        # Handle JSON strings
        if isinstance(distribution, str):
            try:
                import json
                distribution = json.loads(distribution)
            except (json.JSONDecodeError, TypeError):
                # Potencialmente un string de códigos/IDs separados por coma
                for key_part in distribution.split(','):
                    key_part = key_part.strip()
                    if not key_part:
                        continue
                    try:
                        analytic_ids.add(int(key_part))
                    except (TypeError, ValueError):
                        analytic_codes.add(key_part)
                return analytic_ids, analytic_codes

        if not isinstance(distribution, dict):
            return analytic_ids, analytic_codes

        for key in distribution:
            for key_part in str(key).split(','):
                key_part = key_part.strip()
                if not key_part:
                    continue
                try:
                    analytic_ids.add(int(key_part))
                except (TypeError, ValueError):
                    analytic_codes.add(key_part)
        return analytic_ids, analytic_codes

    @api.model
    def _get_distribution_plan_from_distribution(self, distribution):
        analytic_ids, analytic_codes = self._extract_analytic_ids_from_distribution(distribution)
        if not analytic_ids and not analytic_codes:
            return self.env['aicia.distribution.plan']

        analytics = self.env['account.analytic.account']
        if analytic_ids:
            analytics |= self.env['account.analytic.account'].browse(sorted(analytic_ids)).exists()
        if analytic_codes:
            analytics |= self.env['account.analytic.account'].search([
                ('code', 'in', list(analytic_codes)),
                '|', ('company_id', '=', self.env.company.id), ('company_id', '=', False)
            ])

        if not analytics:
            return self.env['aicia.distribution.plan']

        resolved_plan = self.env['aicia.distribution.plan']
        for analytic in analytics:
            plan = analytic.distribution_plan_id
            if not plan or not plan.active:
                continue
            if resolved_plan and plan != resolved_plan:
                # Si hay múltiples planes, devolvemos vacío para evitar ambigüedades
                return self.env['aicia.distribution.plan']
            resolved_plan = plan
        return resolved_plan

    @api.model
    def _get_distribution_plan_from_invoice(self, invoice):
        """Intenta detectar el plan de distribución desde una factura (cabecera o líneas)."""
        if not invoice:
            return self.env['aicia.distribution.plan']

        # 1. Intentar desde la distribución analítica de cabecera
        header_distribution = getattr(invoice, 'analytic_distribution', False)
        if header_distribution:
            plan = self._get_distribution_plan_from_distribution(header_distribution)
            if plan:
                return plan

        # 2. Fallback: Analítica de cabecera clásica (analytic_account_id o similares)
        # Algunos módulos usan move_analytic_distribution_json o similar
        for field_name in ['analytic_account_id', 'move_analytic_account_id']:
            header_analytic = getattr(invoice, field_name, False)
            if header_analytic and isinstance(header_analytic, models.BaseModel) and \
               header_analytic._name == 'account.analytic.account' and \
               header_analytic.distribution_plan_id and header_analytic.distribution_plan_id.active:
                return header_analytic.distribution_plan_id

        # 3. Fallback: Líneas de la factura
        resolved_plan = self.env['aicia.distribution.plan']
        for line in invoice.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
        ):
            line_plan = self._get_distribution_plan_from_distribution(line.analytic_distribution)
            if not line_plan:
                # Compatibilidad: si solo hay analytic_account_id en la línea
                line_analytic = getattr(line, 'analytic_account_id', False)
                if line_analytic and line_analytic.distribution_plan_id and line_analytic.distribution_plan_id.active:
                    line_plan = line_analytic.distribution_plan_id

            if not line_plan:
                continue

            if resolved_plan and line_plan != resolved_plan:
                return self.env['aicia.distribution.plan']
            resolved_plan = line_plan

        return resolved_plan

    @api.model
    def _get_distribution_plan_from_invoices(self, invoices):
        invoices = invoices.filtered(lambda move: move.move_type == 'out_invoice')
        if not invoices:
            return self.env['aicia.distribution.plan']

        resolved_plan = self.env['aicia.distribution.plan']
        for invoice in invoices:
            invoice_plan = self._get_distribution_plan_from_invoice(invoice)
            if not invoice_plan:
                return self.env['aicia.distribution.plan']
            if resolved_plan and invoice_plan != resolved_plan:
                return self.env['aicia.distribution.plan']
            resolved_plan = invoice_plan
        return resolved_plan

    def action_post(self):
        """Validación preventiva del plan de distribución antes de publicar el pago."""
        from odoo.exceptions import UserError
        for payment in self:
            if payment.distribution_plan_id:
                plan = payment.distribution_plan_id
                if not plan.active:
                    raise UserError(
                        "El plan de distribución '%s' está archivado.\n\n"
                        "Por favor, desarchívelo o seleccione un plan activo para el pago." % plan.name
                    )
                if not plan.line_ids:
                    raise UserError(
                        "El plan de distribución '%s' no tiene líneas configuradas.\n\n"
                        "Por favor, añada reglas de reparto al plan para poder realizar el cobro." % plan.name
                    )
                
                # Verificar que haya analítica en las facturas reconciliadas o por reconciliar
                source_moves = (
                    payment.reconciled_invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
                    | payment.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
                )
                if source_moves:
                    any_analytic = False
                    for move in source_moves:
                        if getattr(move, 'analytic_distribution', False) or \
                           any(l.analytic_distribution for l in move.invoice_line_ids):
                            any_analytic = True
                            break
                    if not any_analytic:
                        raise UserError(
                            "Has seleccionado el plan '%s' en el pago, pero las facturas asociadas "
                            "no tienen ninguna distribución analítica configurada (en cabecera ni en líneas).\n\n"
                            "Por favor, verfique la configuración analítica de las facturas." % plan.name
                        )
        return super().action_post()

    def _sync_distribution_plan_from_invoices(self):
        for payment in self.filtered(lambda pay: not pay.distribution_plan_id):
            source_moves = (
                payment.reconciled_invoice_ids.filtered(lambda move: move.move_type == 'out_invoice')
                or payment.invoice_ids.filtered(lambda move: move.move_type == 'out_invoice')
            )
            plan = payment._get_distribution_plan_from_invoices(source_moves)
            if plan:
                payment.distribution_plan_id = plan

    @api.onchange('invoice_ids', 'reconciled_invoice_ids', 'reconciled_bill_ids')
    def _onchange_distribution_plan_from_invoice_ids(self):
        for payment in self:
            if payment.distribution_plan_id:
                continue
            source_moves = (
                payment.invoice_ids.filtered(lambda move: move.move_type == 'out_invoice')
                | payment.reconciled_invoice_ids.filtered(lambda move: move.move_type == 'out_invoice')
                | payment.reconciled_bill_ids.filtered(lambda move: move.move_type == 'out_invoice')
            )
            plan = payment._get_distribution_plan_from_invoices(source_moves)
            if plan:
                payment.distribution_plan_id = plan

    def action_view_distribution_moves(self):
        """Abrir el asiento de distribución generado por este pago."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Distribuciones',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('is_cash_distribution_move', '=', True),
                ('distribution_payment_id', '=', self.id),
            ],
            'context': {'default_is_cash_distribution_move': True},
        }

