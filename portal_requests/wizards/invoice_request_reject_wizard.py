# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class InvoiceResquestRejectWizard(models.TransientModel):
    _name = 'invoice.request.reject.wizard'
    _description = 'Reject Invoice Request Wizard'

    request_id = fields.Many2one(
        'portal.invoice.request',
        string='Solicitud',
        default=lambda self: self.env.context.get('default_request_id'),
        required=True,
    )
    descripcion = fields.Text(string='Descripción')

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}

    def action_accept(self):
        self.ensure_one()
        if not self.request_id:
            raise models.ValidationError(_('No hay solicitud seleccionada.'))
        self.request_id._reject_with_reason(self.descripcion or '')
        return {'type': 'ir.actions.act_window_close'}
