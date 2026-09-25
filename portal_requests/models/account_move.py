from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = 'account.move'

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

