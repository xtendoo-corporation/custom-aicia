from odoo import models, fields, api
from odoo.exceptions import UserError


class SignDocumentWizard(models.TransientModel):
    _name = 'sign.document.wizard'
    _description = 'Asistente para firmar documentos'

    certificate_id = fields.Many2one('digital.certificate', string='Certificado',
                                     domain="[('user_id', '=', uid), ('active', '=', True)]")
    signature_location = fields.Char('Ubicación', default='Madrid')
    signature_reason = fields.Char('Razón', default='Aprobación de documento')

    def action_sign(self):
        active_model = self._context.get('active_model')
        active_ids = self._context.get('active_ids', [])

        if not active_ids or not active_model:
            return {'type': 'ir.actions.act_window_close'}

        if not self.certificate_id:
            raise UserError("Debe seleccionar un certificado digital válido")

        # Si el modelo es ir.attachment, firmamos directamente los archivos
        if active_model == 'ir.attachment':
            for attachment_id in active_ids:
                attachment = self.env['ir.attachment'].browse(attachment_id)
                if not attachment.mimetype or 'application/pdf' not in attachment.mimetype:
                    raise UserError(f"El archivo {attachment.name} no es un PDF válido")

                # Crear un nuevo documento de firma
                signature_doc = self.env['document.signature'].create({
                    'document_to_sign': attachment.datas,
                    'document_filename': attachment.name,
                    'certificate_id': self.certificate_id.id,
                    'signature_location': self.signature_location,
                    'signature_reason': self.signature_reason,
                })

                # Firmar el documento
                signature_doc.action_sign_document()

                # Devolver mensaje de confirmación
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Firma completada',
                        'message': f'Se ha firmado el documento {attachment.name}',
                        'sticky': False,
                        'next': {'type': 'ir.actions.act_window_close'},
                    }
                }
        else:
            # Para otros modelos, implementar lógica específica
            return {'type': 'ir.actions.act_window_close'}
