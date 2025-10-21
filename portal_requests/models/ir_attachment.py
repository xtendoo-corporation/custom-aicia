# -*- coding: utf-8 -*-
from odoo import models, fields, _

class IrAttachmentInherit(models.Model):
    _inherit = 'ir.attachment'

    etiqueta_ids = fields.Many2many(
        'portal.request.etiqueta',
        'ir_attachment_etiqueta_rel',  # nombre de la tabla rel
        'attachment_id',                # referencia al modelo ir.attachment
        'etiqueta_id',                  # referencia al modelo portal.request.etiqueta
        string='Etiquetas'
    )

    categoria_ids = fields.Many2many(
        'portal.request.categoria',
        'ir_attachment_categoria_rel',  # nombre de la tabla rel
        'attachment_id',                 # referencia al modelo ir.attachment
        'categoria_id',                  # referencia al modelo portal.request.categoria
        string='Categorías'
    )
