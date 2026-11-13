# -*- coding: utf-8 -*-
# Modelo para añadir la acción de previsualización de adjuntos
from odoo import models, fields, api

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    pdf_preview = fields.Html(
        string='Previsualización PDF',
        compute='_compute_pdf_preview',
        sanitize=False,
    )

    def _compute_pdf_preview(self):
        for record in self:
            if record.type == 'binary' and record.mimetype == 'application/pdf' and record.datas:
                url = '/web/content/%s?download=false' % record.id
                record.pdf_preview = (
                    f'<iframe src="{url}" width="100%" height="600px" frameborder="0"></iframe>'
                )
            else:
                record.pdf_preview = '<p>No hay PDF para previsualizar.</p>'

    def preview_attachment(self):
        """
        Acción para previsualizar el adjunto PDF en una ventana modal personalizada.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Previsualizar PDF',
            'res_model': 'ir.attachment',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('aicia_preview_attachment.view_attachment_pdf_preview').id,
            'target': 'new',
        }
