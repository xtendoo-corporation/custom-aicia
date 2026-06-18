from odoo import models, fields, api
import base64
from OpenSSL import crypto
import datetime
from odoo.exceptions import UserError


class DigitalCertificate(models.Model):
    _name = 'digital.certificate'
    _description = 'Certificado Digital'

    name = fields.Char('Nombre', required=True)
    certificate_file = fields.Binary('Archivo del Certificado', required=True)
    certificate_filename = fields.Char('Nombre del archivo')
    password = fields.Char('Contraseña', required=True)
    subject = fields.Char('Propietario', readonly=True)
    issuer = fields.Char('Emisor', readonly=True)
    expiration_date = fields.Date('Fecha de expiración', readonly=True)
    user_id = fields.Many2one('res.users', string='Usuario asociado', default=lambda self: self.env.user)
    active = fields.Boolean('Activo', default=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(DigitalCertificate, self).create(vals_list)
        for record in records:
            record._extract_certificate_info()
        return records

    def _extract_certificate_info(self):
        try:
            p12_data = base64.b64decode(self.certificate_file)
            p12 = crypto.load_pkcs12(p12_data, self.password.encode())
            cert = p12.get_certificate()

            self.subject = str(cert.get_subject())
            self.issuer = str(cert.get_issuer())

            # Extraer fecha de expiración
            not_after = cert.get_notAfter().decode()
            expiry_date = datetime.datetime.strptime(not_after, '%Y%m%d%H%M%SZ')
            self.expiration_date = expiry_date.date()

            if expiry_date < datetime.datetime.now():
                raise UserError('El certificado ha expirado')

        except Exception as e:
            raise UserError(f'Error al procesar el certificado: {str(e)}')
