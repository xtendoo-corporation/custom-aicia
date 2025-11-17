from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = 'account.move'

    def add_group_boss_to_followers(self, group):
        if not group:
            return
        boss = group.user_ids.filtered(lambda u: u.has_group('portal_requests.group_equip_boss'))
        if boss:
            print("*" * 100)
            print("Adding boss to followers:", boss.name)
            print("*" * 100)
            self.message_subscribe(partner_ids=[boss.partner_id.id])
