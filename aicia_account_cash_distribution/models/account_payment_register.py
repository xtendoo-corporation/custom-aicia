# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AccountPaymentRegister(models.TransientModel):
    """
    Al registrar un cobro de cliente, permite ver/modificar el plan de
    distribución y lo asigna al pago creado.
    """
    _inherit = 'account.payment.register'

    distribution_plan_id = fields.Many2one(
        'aicia.distribution.plan',
        string='Plan de Distribución',
        domain="[('company_id', '=', company_id)]",
        help="Plan de distribución que se copiará al pago generado y que se "
             "ejecutará al conciliar el cobro.",
    )
    show_distribution_plan_id = fields.Boolean(
        compute='_compute_show_distribution_plan_id',
        string='Mostrar plan de distribución',
    )

    @api.depends('line_ids.move_id.move_type')
    def _compute_show_distribution_plan_id(self):
        for wizard in self:
            moves = wizard.line_ids.move_id
            wizard.show_distribution_plan_id = bool(moves) and all(
                move.move_type == 'out_invoice' for move in moves
            )

    @api.model
    def _is_distribution_plan_applicable_moves(self, moves):
        return bool(moves) and all(move.move_type == 'out_invoice' for move in moves)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'distribution_plan_id' in fields_list and not vals.get('distribution_plan_id'):
            plan = self._detect_distribution_plan_from_context()
            if plan:
                vals['distribution_plan_id'] = plan.id
        return vals

    def _get_effective_distribution_plan(self):
        """Prioridad 1: plan manual del wizard. Prioridad 2: autodetección."""
        self.ensure_one()
        if not self.show_distribution_plan_id:
            return self.env['aicia.distribution.plan']
        if self.distribution_plan_id:
            return self.distribution_plan_id
        if self.env.company.cash_distribution_active:
            return self._detect_distribution_plan()
        return self.env['aicia.distribution.plan']

    def _create_payment_vals_from_wizard(self, batch_result):
        payment_vals = super()._create_payment_vals_from_wizard(batch_result)
        plan = self._get_effective_distribution_plan()
        if plan and self.show_distribution_plan_id:
            payment_vals['distribution_plan_id'] = plan.id
        return payment_vals

    def _create_payment_vals_from_batch(self, batch_result):
        payment_vals = super()._create_payment_vals_from_batch(batch_result)
        plan = self._get_effective_distribution_plan()
        if plan and self.show_distribution_plan_id:
            payment_vals['distribution_plan_id'] = plan.id
        return payment_vals

    def _create_payments(self):
        # Fallback defensivo: normalmente el plan ya se inyecta en create_vals
        # mediante _create_payment_vals_from_wizard/_from_batch antes de reconciliar.
        plan = self._get_effective_distribution_plan()

        payments = super()._create_payments()

        if plan:
            payments.filtered(
                lambda p: p.show_distribution_plan_id and not p.distribution_plan_id
            ).write({'distribution_plan_id': plan.id})

        return payments

    def _reconcile_payments(self, to_process, edit_mode=False):
        res = super()._reconcile_payments(to_process, edit_mode=edit_mode)
        payments = self.env['account.payment']
        for vals in to_process:
            payment = vals.get('payment')
            if payment:
                payments |= payment
        payments.filtered(
            lambda payment: payment.show_distribution_plan_id and not payment.distribution_plan_id
        )._sync_distribution_plan_from_invoices()
        return res

    @api.model
    def _detect_distribution_plan_from_context(self):
        """Detecta el plan desde los documentos activos del wizard."""
        if self.env.context.get('active_model') != 'account.move':
            return self.env['aicia.distribution.plan']
        moves = self.env['account.move'].browse(self.env.context.get('active_ids', []))
        return self._detect_distribution_plan_from_moves(moves)

    @api.model
    def _detect_distribution_plan_from_moves(self, moves):
        """Prioriza la analítica de cabecera y solo autocompleta si el plan es inequívoco."""
        if not self._is_distribution_plan_applicable_moves(moves):
            return self.env['aicia.distribution.plan']
        return self.env['account.payment']._get_distribution_plan_from_invoices(moves)

    def _detect_distribution_plan(self):
        """Compatibilidad: detecta el plan desde las líneas cargadas en el wizard."""
        moves = self.line_ids.move_id
        return self._detect_distribution_plan_from_moves(moves)
