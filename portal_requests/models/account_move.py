from odoo import Command, _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Facturas a nombre de AICIA que ha pagado un empleado y que se le
    # reembolsan dentro de una liquidación de gastos del portal.
    employee_liquidation_id = fields.Many2one(
        'portal.hr.expensive.request', string='Liquidación de gastos',
        readonly=True, copy=False, index='btree_not_null')
    paid_by_employee_id = fields.Many2one(
        'hr.employee', string='Pagada por el empleado', readonly=True, copy=False, tracking=True)
    employee_transfer_move_id = fields.Many2one(
        'account.move', string='Traslado de la deuda al empleado', readonly=True, copy=False)
    is_employee_transfer = fields.Boolean(
        string='Traslado de deuda a empleado', readonly=True, copy=False,
        help='Asiento que traslada al empleado la deuda de una factura que él pagó.')

    def add_followers_from_request(self, request):
        self.ensure_one()
        if not request:
            return

        # 1) Quitar todos los followers actuales de la factura
        current_partner_ids = self.message_partner_ids.ids
        if current_partner_ids:
            self.message_unsubscribe(partner_ids=current_partner_ids)

        # 2) Obtener los partner_ids que tiene la solicitud
        req_partner_ids = []
        if hasattr(request, 'message_partner_ids'):
            req_partner_ids = list(request.message_partner_ids.ids)

        # 3) Suscribir esos partner_ids a la factura
        if req_partner_ids:
            self.message_subscribe(partner_ids=req_partner_ids)

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        posted.filtered(
            lambda move: move.paid_by_employee_id and move.is_purchase_document()
            and not move.employee_transfer_move_id
        )._transfer_payable_to_employee()
        posted.employee_liquidation_id._update_liquidation_tickets_amount()
        return posted

    def button_draft(self):
        transferred = self.filtered('employee_transfer_move_id')
        for move in transferred:
            move._check_employee_not_reimbursed()
        transferred.employee_transfer_move_id.line_ids.remove_move_reconcile()
        res = super().button_draft()
        for move in transferred:
            move.employee_transfer_move_id._reverse_moves(
                [{'ref': _('Anulación: %s', move.employee_transfer_move_id.ref)}], cancel=True)
            move.employee_transfer_move_id = False
        return res

    def _employee_transfer_journal(self):
        self.ensure_one()
        journal = self.env['account.journal'].search([
            *self.env['account.journal']._check_company_domain(self.company_id),
            ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            raise UserError(_(
                'No hay ningún diario de operaciones varias en %s para trasladar la deuda '
                'de la factura al empleado.', self.company_id.name))
        return journal

    def _employee_payable_account(self):
        """Cuenta a pagar del contacto del empleado: la misma que usa
        hr_expense para los gastos pagados por el empleado, de modo que
        facturas y tickets se le reembolsan en un único pago."""
        self.ensure_one()
        partner = self.paid_by_employee_id.sudo().work_contact_id
        if not partner:
            raise UserError(_(
                'El empleado %s no tiene contacto de trabajo: no se le puede trasladar la '
                'deuda de la factura.', self.paid_by_employee_id.name))
        partner = partner.with_company(self.company_id)
        return partner, partner.property_account_payable_id or partner.parent_id.property_account_payable_id

    def _transfer_payable_to_employee(self):
        """Asiento que salda la deuda con el proveedor contra el empleado que
        pagó la factura. Se concilia con la factura, que queda pagada, y deja
        pendiente el reembolso al empleado."""
        for move in self:
            payable_lines = move.line_ids.filtered(
                lambda line: line.account_id.account_type == 'liability_payable' and not line.reconciled)
            if not payable_lines:
                continue
            employee_partner, employee_account = move._employee_payable_account()
            balance = sum(payable_lines.mapped('amount_residual'))
            amount_currency = sum(payable_lines.mapped('amount_residual_currency'))
            label = _('Factura %(invoice)s pagada por %(employee)s',
                      invoice=move.name, employee=move.paid_by_employee_id.name)
            transfer = self.env['account.move'].create({
                'move_type': 'entry',
                'is_employee_transfer': True,
                'journal_id': move._employee_transfer_journal().id,
                'company_id': move.company_id.id,
                'date': move.date,
                'ref': label,
                # Cuenta del empleado: como en los recibos de hr_expense, para
                # que el registro de pago agrupe tickets y facturas en un
                # único pago y la transferencia SEPA tenga destino.
                'partner_bank_id': move.paid_by_employee_id.sudo().primary_bank_account_id.id,
                'line_ids': [
                    Command.create({
                        'name': label,
                        'account_id': payable_lines[0].account_id.id,
                        'partner_id': move.commercial_partner_id.id,
                        'balance': -balance,
                        'amount_currency': -amount_currency,
                        'currency_id': move.currency_id.id,
                    }),
                    Command.create({
                        'name': label,
                        'account_id': employee_account.id,
                        'partner_id': employee_partner.id,
                        'balance': balance,
                        'amount_currency': amount_currency,
                        'currency_id': move.currency_id.id,
                    }),
                ],
            })
            transfer._post(soft=False)
            supplier_line = transfer.line_ids.filtered(
                lambda line: line.partner_id == move.commercial_partner_id
                and line.account_id == payable_lines[0].account_id)
            (payable_lines | supplier_line).reconcile()
            move.employee_transfer_move_id = transfer
            move.message_post(body=_(
                'Deuda trasladada al empleado %(employee)s en el asiento %(transfer)s.',
                employee=move.paid_by_employee_id.name, transfer=transfer.name))

    def _check_employee_not_reimbursed(self):
        self.ensure_one()
        employee_partner = self.paid_by_employee_id.sudo().work_contact_id
        employee_lines = self.employee_transfer_move_id.line_ids.filtered(
            lambda line: line.partner_id == employee_partner)
        if employee_lines.matched_debit_ids or employee_lines.matched_credit_ids:
            raise UserError(_(
                'La factura %s ya se ha reembolsado al empleado. Anule primero el pago del '
                'reembolso para poder pasarla a borrador.', self.name))
