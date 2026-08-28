# -*- coding: utf-8 -*-
from odoo import models, fields, _

class PortalEtiqueta(models.Model):
    _name = 'portal.request.etiqueta'
    _description = 'Etiqueta para solicitudes del portal'

    name = fields.Char(string='Nombre', required=True)
    color = fields.Integer(string='Color', default=0)
    description = fields.Text(string='Descripción')
    # Comentario: Modelo para gestionar etiquetas con color y descripción

class PortalCategoria(models.Model):
    _name = 'portal.request.categoria'
    _description = 'Categoría para solicitudes del portal'

    name = fields.Char(string='Nombre', required=True)
    color = fields.Integer(string='Color', default=0)
    description = fields.Text(string='Descripción')
    # Comentario: Modelo para gestionar categorías con color y descripción
