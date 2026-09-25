from odoo import models, api
class SignSendRequestInherit(models.TransientModel):
    _inherit = 'sign.send.request'
    @api.depends('template_id', 'set_sign_order', 'template_id.sign_item_ids', 'reference_doc')
    def _compute_signer_ids(self):
        """Cuando el reference_doc es un document.approval, forzamos que el
        firmante sea el usuario actual, sobreescribiendo lo que el metodo padre
        haya asignado a partir del user_id del documento (el creador)."""
        super()._compute_signer_ids()
        for wiz in self:
            if wiz.reference_doc and wiz.reference_doc._name == 'document.approval':
                current_partner = wiz.env.user.partner_id
                for signer in wiz.signer_ids:
                    signer.partner_id = current_partner
