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

    def _compute_distribution_move_count(self):
        for payment in self:
            reconciles = (
                payment.move_id.line_ids.mapped('matched_debit_ids')
                | payment.move_id.line_ids.mapped('matched_credit_ids')
            )
            payment.distribution_move_count = self.env['aicia.distribution.move'].search_count([
                ('partial_reconcile_id', 'in', reconciles.ids),
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
    def _extract_analytic_ids_from_distribution(self, distribution):
        analytic_ids = set()
        if not distribution:
            return analytic_ids

        for key in distribution:
            for key_part in str(key).split(','):
                key_part = key_part.strip()
                if not key_part:
                    continue
                try:
                    analytic_ids.add(int(key_part))
                except (TypeError, ValueError):
                    continue
        return analytic_ids

    @api.model
    def _get_distribution_plan_from_distribution(self, distribution):
        analytic_ids = self._extract_analytic_ids_from_distribution(distribution)
        if not analytic_ids:
            return self.env['aicia.distribution.plan']

        resolved_plan = self.env['aicia.distribution.plan']
        analytics = self.env['account.analytic.account'].browse(sorted(analytic_ids)).exists()
        for analytic in analytics:
            plan = analytic.distribution_plan_id
            if not plan or not plan.active:
                continue
            if resolved_plan and plan != resolved_plan:
                return self.env['aicia.distribution.plan']
            resolved_plan = plan
        return resolved_plan

    @api.model
    def _get_distribution_plan_from_invoice(self, invoice):
        if not invoice or invoice.move_type != 'out_invoice':
            return self.env['aicia.distribution.plan']

        header_distribution = getattr(invoice, 'analytic_distribution', False)
        if header_distribution:
            return self._get_distribution_plan_from_distribution(header_distribution)

        resolved_plan = self.env['aicia.distribution.plan']
        for line in invoice.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
        ):
            line_plan = self._get_distribution_plan_from_distribution(line.analytic_distribution)
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

    def _sync_distribution_plan_from_invoices(self):
        for payment in self.filtered(lambda pay: not pay.distribution_plan_id):
            source_moves = (
                payment.reconciled_invoice_ids.filtered(lambda move: move.move_type == 'out_invoice')
                or payment.invoice_ids.filtered(lambda move: move.move_type == 'out_invoice')
            )
            plan = payment._get_distribution_plan_from_invoices(source_moves)
            if plan:
                payment.distribution_plan_id = plan

    @api.onchange('invoice_ids')
    def _onchange_distribution_plan_from_invoice_ids(self):
        for payment in self:
            if payment.distribution_plan_id:
                continue
            plan = payment._get_distribution_plan_from_invoices(
                payment.invoice_ids.filtered(lambda move: move.move_type == 'out_invoice')
            )
            if plan:
                payment.distribution_plan_id = plan

    def action_view_distribution_moves(self):
        """Abrir los logs de distribución generados por este pago."""
        self.ensure_one()
        reconciles = (
            self.move_id.line_ids.mapped('matched_debit_ids')
            | self.move_id.line_ids.mapped('matched_credit_ids')
        )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Distribuciones',
            'res_model': 'aicia.distribution.move',
            'view_mode': 'list,form',
            'domain': [('partial_reconcile_id', 'in', reconciles.ids)],
        }

