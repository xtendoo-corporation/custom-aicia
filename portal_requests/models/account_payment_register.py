from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _get_line_batch_key(self, line):
        """Odoo solo agrupa por la cuenta bancaria del contacto en facturas y
        recibos. Los traslados de deuda al empleado llevan su cuenta igual que
        los recibos de hr_expense, para que facturas y tickets de una
        liquidación se le reembolsen en un único pago."""
        key = super()._get_line_batch_key(line)
        if line.move_id.is_employee_transfer:
            key['partner_bank_id'] = line.move_id.partner_bank_id.id
        return key
