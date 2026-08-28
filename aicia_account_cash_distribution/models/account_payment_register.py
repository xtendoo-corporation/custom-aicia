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

    @api.onchange('line_ids')
    def _onchange_line_ids_detect_plan(self):
        for wizard in self:
            if not wizard.distribution_plan_id:
                plan = wizard._detect_distribution_plan()
                if plan:
                    wizard.distribution_plan_id = plan

    @api.model
    def _detect_distribution_plan_from_context(self):
        """Detecta el plan desde los documentos activos del wizard."""
        # Se prioriza el active_model/active_ids del contexto
        active_model = self.env.context.get('active_model')
        if active_model == 'account.move':
            active_ids = self.env.context.get('active_ids') or [self.env.context.get('active_id')]
            active_ids = [aid for aid in active_ids if aid]
            if active_ids:
                moves = self.env['account.move'].browse(active_ids)
                return self._detect_distribution_plan_from_moves(moves)
        elif active_model == 'account.move.line':
            # Si se viene desde apuntes contables, detectamos desde los asientos de esos apuntes
            active_ids = self.env.context.get('active_ids') or [self.env.context.get('active_id')]
            active_ids = [aid for aid in active_ids if aid]
            if active_ids:
                lines = self.env['account.move.line'].browse(active_ids)
                return self._detect_distribution_plan_from_moves(lines.move_id)
                
        return self.env['aicia.distribution.plan']

    @api.model
    def _detect_distribution_plan_from_moves(self, moves):
        """Detecta el plan desde un lote de asientos."""
        if not moves:
            return self.env['aicia.distribution.plan']
        # Usamos el método de account.payment que ahora es más robusto
        return self.env['account.payment']._get_distribution_plan_from_invoices(moves)

    def _detect_distribution_plan(self):
        """Detecta el plan desde las líneas ya cargadas en el objeto Transient."""
        moves = self.line_ids.move_id
        return self._detect_distribution_plan_from_moves(moves)
