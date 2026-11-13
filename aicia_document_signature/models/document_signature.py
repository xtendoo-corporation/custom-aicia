from odoo import models, fields, api
import base64
import tempfile
import os
from datetime import datetime
from odoo.exceptions import UserError
import logging
import endesive.pdf

_logger = logging.getLogger(__name__)

class DocumentSignature(models.Model):
    _name = 'document.signature'
    _description = 'Documento Firmado Digitalmente'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Nombre', compute='_compute_name')
    document_to_sign = fields.Binary('Documento a firmar', required=True)
    document_filename = fields.Char('Nombre del archivo')
    signed_document = fields.Binary('Documento firmado')
    signed_filename = fields.Char('Nombre del archivo firmado')
    certificate_id = fields.Many2one('digital.certificate', string='Certificado digital', required=True)
    signature_date = fields.Datetime('Fecha de firma', readonly=True)
    user_id = fields.Many2one('res.users', string='Usuario firmante', default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('signed', 'Firmado'),
        ('error', 'Error')
    ], string='Estado', default='draft', tracking=True)
    signature_location = fields.Char('Ubicación', default='Madrid')
    signature_reason = fields.Char('Razón de la firma', default='Documento aprobado')
    signature_pages = fields.Selection([
        ('last', 'Solo en la última página'),
        ('all', 'En todas las páginas')
    ], string='Firmar en', default='last', required=True, help='Elija si la firma debe aplicarse solo en la última página o en todas las páginas del PDF.')

    @api.depends('document_filename', 'state')
    def _compute_name(self):
        for record in self:
            if record.document_filename:
                if record.state == 'signed':
                    record.name = f'Firmado: {record.document_filename}'
                else:
                    record.name = f'Pendiente: {record.document_filename}'
            else:
                record.name = 'Nuevo documento'

    def action_sign_document(self):
        self.ensure_one()
        if not self.certificate_id:
            raise UserError("Se requiere un certificado digital para firmar")

        try:
            cert_data = base64.b64decode(self.certificate_id.certificate_file)
            password = self.certificate_id.password
            pdf_data = base64.b64decode(self.document_to_sign)
            fd, temp_pdf_path = tempfile.mkstemp(suffix='.pdf')
            os.write(fd, pdf_data)
            os.close(fd)

            from PyPDF2 import PdfFileReader, PdfFileWriter
            pdf_reader = PdfFileReader(open(temp_pdf_path, 'rb'))
            num_pages = pdf_reader.getNumPages()
            signed_pdf_writer = PdfFileWriter()

            date = datetime.utcnow()
            dct_base = {
                'sigflags': 3,
                'sigbutton': True,
                'contact': self.user_id.email or '',
                'location': self.signature_location,
                'reason': self.signature_reason,
                'signingdate': date.strftime("%Y%m%d%H%M%S+00'00'"),
            }

            # Firmar según la selección del usuario
            if self.signature_pages == 'all':
                # Firmar todas las páginas
                temp_signed_path = temp_pdf_path
                for i in range(num_pages):
                    dct = dct_base.copy()
                    dct['sigpage'] = i
                    datau = open(temp_signed_path, 'rb').read()
                    datas = endesive.pdf.cms.sign(
                        datau, dct,
                        cert_data, password,
                        'sha256'
                    )
                    # Guardar el PDF firmado temporalmente para la siguiente iteración
                    temp_signed_path2 = tempfile.mktemp(suffix='.pdf')
                    with open(temp_signed_path2, 'wb') as f:
                        f.write(datas)
                    if temp_signed_path != temp_pdf_path:
                        os.unlink(temp_signed_path)
                    temp_signed_path = temp_signed_path2
                with open(temp_signed_path, 'rb') as f:
                    final_signed_data = f.read()
                if temp_signed_path != temp_pdf_path:
                    os.unlink(temp_signed_path)
            else:
                # Solo la última página
                dct = dct_base.copy()
                dct['sigpage'] = num_pages - 1
                datau = open(temp_pdf_path, 'rb').read()
                final_signed_data = endesive.pdf.cms.sign(
                    datau, dct,
                    cert_data, password,
                    'sha256'
                )

            signed_data = base64.b64encode(final_signed_data)
            signed_filename = f"signed_{self.document_filename or 'document.pdf'}"

            self.write({
                'signed_document': signed_data,
                'signed_filename': signed_filename,
                'signature_date': fields.Datetime.now(),
                'state': 'signed',
            })

            try:
                os.unlink(temp_pdf_path)
            except Exception:
                pass

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Éxito',
                    'message': 'El documento se ha firmado correctamente',
                    'sticky': False,
                }
            }

        except Exception as e:
            self.state = 'error'
            _logger.error("Error en la firma digital: %s", str(e))
            raise UserError(f"Error al firmar el documento: {str(e)}")
