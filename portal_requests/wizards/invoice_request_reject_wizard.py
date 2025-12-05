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
        #Comprobamos si el que realiza la solicitud es el jefe de equipo o el responsabel del proyecto.
        status = 'to_revise'
        if self.request_id.equip_boss == self.request_id.user_id:
            status = 'approved_by_boss_group'
        self.request_id.write({'status': status })
        descripcion = self.descripcion or ''
        body = (
            'Solicitud Rechazada: {}'
        ).format(descripcion)

        # publicar como nota en el chatter (usar subtype_id con env.ref)
        self.request_id.sudo().message_post(
            body=body,
            subtype_id=self.env.ref('mail.mt_note').id
        )
        user_to_send = self.env['res.users'].search(
            [('id', 'in', self.request_id.user_id.ids)])
        print("*")
        print("user_to_send:", user_to_send)
        print("*")
        move_text = "factura" if self.request_id.move_type == 'out_invoice' else "factura rectificativa"
        self.request_id._send_invoice_request_mail('rejected',user_to_send,move_text, self.request_id.user_id.name, self.request_id.analytic_id.name, self.request_id.partner_id.name, notes=descripcion)

        return {'type': 'ir.actions.act_window_close'}



