from odoo import models, fields, tools
import base64


class TypeApproval(models.Model):
    _name = 'type.approval'
    _description = 'Type Approval'

    def _get_default_image(self):
        default_image_path = 'portal_requests/static/description/document.png'
        return base64.b64encode(tools.misc.file_open(default_image_path, 'rb').read())

    name = fields.Char(string='Name', required=True)
    count_unapproved = fields.Integer(string='Count Unapproved', compute='_compute_count_unapproved')
    document_approval_ids = fields.One2many('document.approval', 'type_id', string='Document Approvals')
    image = fields.Binary(string='Image', default=_get_default_image)

    def _compute_count_unapproved(self):
        for record in self:
            record.count_unapproved = self.env['document.approval'].search_count([('type_id', '=', record.id), ('is_revised', '=', False)])


