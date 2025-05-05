import base64
import io
import os
import pdfplumber

from PyPDF2 import PdfFileReader, PdfFileWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from PIL import Image
import tempfile
from contextlib import closing
import logging

_logger = logging.getLogger(__name__)

class DocumentApproval(models.Model):
    _name = 'document.approval'
    _rec_name = 'computed_name'
    _description = 'Solicitud Documentos'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    type_id = fields.Many2one('type.approval', string='Tipo', required=True ,tracking=True)
    computed_name = fields.Char('Computed Name', compute='_compute_name')
    description = fields.Text(string='Descripción', tracking=True)
    # approved = fields.Boolean(string='Aprobado', default=False, tracking=True)
    # approved_by_director_i_d = fields.Boolean(string='Aprobación Director I+D', default=False, tracking=True)
    # approved_by_director_gerente = fields.Boolean(string='Aprobación Director Gerente ', default=False, tracking=True)
    # is_revised = fields.Boolean(string='Está revisado', default=False, store=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Grupo de trabajo',tracking=True)
    user_id = fields.Many2one('res.users', string='Solicitante', tracking=True)
    status = fields.Selection([('approved_by_director_i_d', 'Aprobación del DIrector I+D'), ('approved_by_director_gerente', 'Aprobación del DIrector Gerente'), ('sign_company', 'Esperando firma de empresa'),('final_revision','Revisión final'), ("approve", 'Aprobada'), ("rejected", 'Rechazada')], 'Estado', default='approved_by_director_i_d' ,tracking=True)
    financial_signature = fields.Binary(string="Firma Director Gerente")
    is_company_signed = fields.Boolean(string='Firmado por la empresa', default=False, tracking=True)

    def action_sign_attached_pdf(self):
        """Firmar PDF adjunto al documento de aprobación usando Java directamente"""
        self.ensure_one()

        # Importar subprocess
        import subprocess

        # 1. Buscar adjuntos de tipo PDF para este documento
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('mimetype', '=', 'application/pdf')
        ], limit=1)

        if not attachment:
            raise UserError(_("No hay documentos PDF adjuntos para firmar."))

        # 2. Buscar un certificado adecuado
        certificate = self.env['report.certificate'].search([
            ('company_id', '=', self.env.company.id),
            ('model_id.model', '=', self._name),
        ], limit=1)

        if not certificate:
            certificate = self.env['report.certificate'].search([
                ('company_id', '=', self.env.company.id),
            ], limit=1)

        if not certificate:
            raise UserError(_("No se encontró un certificado válido para este tipo de documento."))

        # 3. Obtener contenido PDF y crear archivos temporales
        pdf_content = base64.b64decode(attachment.datas)
        pdf_fd, pdf_path = tempfile.mkstemp(suffix=".pdf", prefix="approval.tmp.")

        # Crear nombre para archivo firmado
        fd, signed_path = tempfile.mkstemp(suffix=".pdf", prefix="approval.signed.")
        os.close(fd)

        try:
            with closing(os.fdopen(pdf_fd, "wb")) as pf:
                pf.write(pdf_content)

            # 4. Firma directamente con Java (sin modificar métodos)
            report_obj = self.env['ir.actions.report']

            # Buscar ubicación de Java
            java_path = None
            java_paths = ["java", "/usr/bin/java", "/usr/lib/jvm/default-java/bin/java", "/etc/alternatives/java"]

            for path in java_paths:
                try:
                    if "/" in path:
                        if os.path.exists(path) and os.access(path, os.X_OK):
                            java_path = path
                            _logger.info(f"Usando Java en: {java_path}")
                            break
                    else:
                        result = subprocess.call(["which", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        if result == 0:
                            java_path = path
                            _logger.info(f"Usando Java en PATH: {java_path}")
                            break
                except Exception as e:
                    _logger.debug(f"Error al verificar {path}: {e}")

            if not java_path:
                raise UserError(_("No se pudo encontrar Java en el sistema. Compruebe su instalación."))

            # Obtener ruta del JAR
            if not hasattr(report_obj, '_get_jar_path'):
                raise UserError(_("El módulo de firma PDF no está correctamente instalado."))

            jar_path = report_obj._get_jar_path()

            # Construir comando para firma
            command = [
                java_path,
                "-jar", jar_path,
                "--keystore-file", certificate.certificate,
                "--keystore-password", certificate.password,
                "--keystore-type", "pkcs12",
                "-o", signed_path
            ]

            # Añadir parámetros adicionales según la configuración
            if hasattr(certificate, 'java_params') and certificate.java_params:
                for param in certificate.java_params.split():
                    command += param.split('=')

            command += [pdf_path]

            _logger.info("Ejecutando comando: %s", ' '.join(command))

            env = os.environ.copy()
            env["LC_ALL"] = "C.UTF-8"
            env["LANG"] = "C.UTF-8"

            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
            )
            stdout, stderr = process.communicate()

            if process.returncode != 0:
                _logger.error("Error en jPdfSign (código: %s). Mensaje: %s. Salida: %s",
                              process.returncode, stderr, stdout)
                raise UserError(
                    _("Informe de firma (PDF): jPdfSign falló (código: %s). "
                      "Mensaje: %s. Salida: %s")
                    % (process.returncode, stderr, stdout)
                )

            # 5. Verificar y procesar el documento firmado
            if not os.path.exists(signed_path):
                raise UserError(_("No se pudo generar el PDF firmado."))

            with open(signed_path, "rb") as pf:
                signed_content = pf.read()

            # 6. Crear nuevo adjunto firmado
            signed_name = f"{attachment.name.rsplit('.', 1)[0]}_firmado.pdf"
            self.env['ir.attachment'].create({
                'name': signed_name,
                'datas': base64.b64encode(signed_content),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
                'description': f"Versión firmada de {attachment.name}"
            })

            # 7. Marcar como firmado
            self.is_company_signed = True

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Éxito"),
                    'message': _("Documento firmado correctamente"),
                    'type': 'success',
                }
            }

        except Exception as e:
            _logger.exception("Error durante la firma del PDF")
            raise UserError(_("Error al firmar el documento: %s") % str(e))

        finally:
            # Limpiar archivos temporales
            if os.path.exists(pdf_path):
                try:
                    os.unlink(pdf_path)
                except Exception as e:
                    _logger.warning(f"No se pudo eliminar el archivo temporal {pdf_path}: {e}")

            if signed_path and os.path.exists(signed_path):
                try:
                    os.unlink(signed_path)
                except Exception as e:
                    _logger.warning(f"No se pudo eliminar el archivo firmado temporal {signed_path}: {e}")

    def add_signature_to_pdf(self):
        """ Abre el PDF, añade la firma y guarda el nuevo PDF en Odoo """

        attachment_ids = self.env['ir.attachment'].search([
            ('res_model', '=', 'document.approval'),
            ('res_id', '=', self.id)
        ], limit=1)

        if not attachment_ids or not self.financial_signature:
            raise ValueError("Falta el PDF adjunto o la firma")

        pdf_data = base64.b64decode(attachment_ids.datas)
        with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
            text_content = ""
            for page in pdf.pages:
                text_content += page.extract_text()


        lines = text_content.split("\n")
        last_y_position = len(lines) * 12


        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)


        signature_data = base64.b64decode(self.financial_signature)
        signature_path = "/tmp/temp_signature.png"


        with open(signature_path, "wb") as f:
            f.write(signature_data)


        signature_image = Image.open(signature_path)


        width, height = signature_image.size
        new_image = Image.new('RGBA', (width, height), (255, 255, 255, 255))
        new_image.paste(signature_image, (0, 0),
                        signature_image.convert("RGBA").split()[3])


        signature_with_background_path = "/tmp/temp_signature_with_background.png"
        new_image.save(signature_with_background_path)


        can.drawImage(signature_with_background_path, 100, last_y_position + 10, width=200,
                      height=100)


        can.setFont("Helvetica", 12)
        can.drawString(100, last_y_position - 5,
                       "FDO.: Director Gerente")

        can.save()
        packet.seek(0)
        signature_pdf = PdfFileReader(packet)
        pdf_reader = PdfFileReader(io.BytesIO(pdf_data))
        pdf_writer = PdfFileWriter()

        for i in range(pdf_reader.getNumPages()):
            page = pdf_reader.getPage(i)
            if i == 0:
                page.mergePage(signature_pdf.getPage(0))
            pdf_writer.addPage(page)

        output_pdf = io.BytesIO()
        pdf_writer.write(output_pdf)
        output_pdf.seek(0)

        new_pdf_data = base64.b64encode(output_pdf.read()).decode('utf-8')  # Convertir a string para Odoo
        attachment_data = {
            'name': f"firmado_director_financiero_{attachment_ids.name}",
            'res_model': 'document.approval',
            'res_id': self.id,
            'datas': new_pdf_data,
            'type': 'binary',
        }

        signed_attachment = self.env['ir.attachment'].create(attachment_data)
        os.remove(signature_path)
        os.remove(signature_with_background_path)

        return signed_attachment

    def _compute_name(self):
        for record in self:
            record.computed_name = f"{record.type_id.name} - {record.description}"

    # def request_partner_sign(self):
    #     print("*"*100)
    #     print("solicitar firmar cliente")
    #     print("*"*100)


    def action_solicite_final_revision(self):
        self.ensure_one()
        if self.status == 'sign_company' and self.env.user.has_group("portal_requests.group_equip_boss"):
            print("Solicitante solicita revisión final")
            self.status = 'final_revision'
            self.is_company_signed = True
            user_to_send = self.env['res.users'].search([
                ('groups_id', 'in', self.env.ref('portal_requests.group_director_investigation_and_development').id)
            ])
            self.send_request_email(self.type_id.name,user_to_send, "final_revision")

    def action_approve(self):
        self.ensure_one()
        if self.status == 'approved_by_director_i_d' and self.env.user.has_group("portal_requests.group_director_investigation_and_development"):
            print("Director I+D aprueba")
            self.status = 'approved_by_director_gerente'
            user_to_send = self.env['res.users'].search([
                ('groups_id', 'in', self.env.ref('portal_requests.group_director_manager').id)
            ])
            self.send_request_email(self.type_id.name,user_to_send, "approved_by_director_i_d")
        if self.status == 'approved_by_director_gerente' and self.env.user.has_group("portal_requests.group_director_manager"):
            if not self.financial_signature:
                raise UserError("Por favor, añada la firma del director gerente.")
            print("Gerente aprueba")

            self.add_signature_to_pdf()
            if self.is_company_signed:
                user_to_send = self.env['res.users'].search([
                    ('groups_id', 'in', self.env.ref('portal_requests.group_director_investigation_and_development').id)
                ])
                print("esta ya firmado por la empresa")
                self.status = 'final_revision'
                self.send_request_email(self.type_id.name, user_to_send, "final_revision")

            else:
                print("no esta firmado")
                user_to_send = self.user_id
                self.status = 'sign_company'
                # self.add_signature_to_pdf()
                self.send_request_email(self.type_id.name, user_to_send, "sign_director_manager")
            # self.send_request_email(self.type_id.name,user_to_send, "sign_director_accounting")
        # if self.status == 'sign_company' and self.env.user.has_group("portal_requests.group_director_manager"):
        #     print("Director Gerente aprueba")
        #     self.status = 'approve'
        #     self.send_request_email(self.type_id.name,self.user_id, "sign_company")

    def action_reject(self):
        for record in self:
            record.status = 'rejected'

    def action_to_revise(self):
        self.ensure_one()
        if self.env.user.has_group("portal_requests.group_director_manager"):
            self.status = 'sign_company'
        else:
            raise UserError("Solo el director gerente puede enviar a revisión.")


    def send_request_email(self, move_text,user_to_send,type):
        print("*"*100)
        print("senf_request_email")
        document_request_link = f"/web#id={self.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=document.approval&view_type=form"
        user = self.user_id

        if not user_to_send:
            raise UserError("No se encontraron directores en el grupo especificado.")

        for admin_user in user_to_send:
            if not admin_user.email:
                continue  # Evita enviar correos a usuarios sin email
            user_for_send = self.env.user.name
            if type=="approved_by_director_i_d":
                print("approved_by_director_i_d")
                admin_name = admin_user.name
                body_html = f"""
                       <p>Estimado/a {admin_name},</p>
                       <p>El Director de I+D,{user_for_send}, ya ha dado su aprobación para la siguiente solicitud:</p>
                       <ul>
                           <li><strong>Solicitante:</strong> {user.name}</li>
                           <li><strong>Tipo:</strong> {move_text}</li>
                           <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                       </ul>
                       <p>Saludos cordiales, Odoo</p>
                   """
            elif type=="sign_director_manager":
                print("sign_director_manager")
                admin_name = admin_user.name
                body_html = f"""
                                      <p>Estimado/a {admin_name},</p>
                                      <p>El Director Gerente,{user_for_send}, ya ha firmado la siguiente solicitud:</p>
                                      <p>Es necesario que la empresa firme el documento para continuar con el proceso.</p>
                                      <ul>
                                          <li><strong>Solicitante:</strong> {user.name}</li>
                                          <li><strong>Tipo:</strong> {move_text}</li>
                                          <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                                      </ul>
                                      <p>Saludos cordiales, Odoo</p>
                                  """
            elif type=="sign_company":
                print("sign_company")
                admin_name = admin_user.name
                body_html = f"""
                                      <p>Estimado/a {admin_name},</p>
                                      <p>El jefe de equipo,{user_for_send}, ha añadido la firma de la empresa a la solicitud:</p>
                                      <ul>
                                          <li><strong>Solicitante:</strong> {user.name}</li>
                                          <li><strong>Tipo:</strong> {move_text}</li>
                                          <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                                      </ul>
                                      <p>Saludos cordiales, Odoo</p>
                                  """
            else:
                admin_name = admin_user.name
                body_html = f"""
                                       <p>Estimado/a {admin_name},</p>
                                       <p>El Director de I+D ya ha dado su aprobación para la siguiente solicitud:</p>
                                       <ul>
                                           <li><strong>Solicitante:</strong> {user.name}</li>
                                           <li><strong>Tipo:</strong> {move_text}</li>
                                           <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
                                       </ul>
                                       <p>Saludos cordiales, Odoo</p>
                                   """
            mail_values = {
                'subject': 'Solicitud de documento',
                'email_from': user.email or 'no-reply@example.com',
                'email_to': admin_user.email,
                'body_html': body_html,
            }
            mail = self.env['mail.mail'].create(mail_values)
            mail.send()

    def send_applied_email(self, move_text):
        admin_users = self.env['res.users'].search([
            ('id', '=', self.user_id.id)
        ])
        print("*" * 100)
        print("senf_applied_email")
        print("admin_users", admin_users)

        print("self.user_id", self.user_id)

        # document_request_link = f"/web#id={self.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=document.approval&view_type=form"
        # user = self.user_id
        #
        # if not admin_users:
        #     raise UserError("No se encontraron directores en el grupo especificado.")
        #
        # for admin_user in admin_users:
        #     if not admin_user.email:
        #         continue  # Evita enviar correos a usuarios sin email
        #
        #     admin_name = admin_user.name
        #     body_html = f"""
        #            <p>Estimado/a {admin_name},</p>
        #            <p>El Director de I+D ya ha dado su aprobación para la siguiente solicitud:</p>
        #            <ul>
        #                <li><strong>Solicitante:</strong> {user.name}</li>
        #                <li><strong>Tipo:</strong> {move_text}</li>
        #                <li><strong>Enlace:</strong> <a href="{document_request_link}">Solicitud</a></li>
        #            </ul>
        #            <p>Saludos cordiales, Odoo</p>
        #        """
        #
        #     mail_values = {
        #         'subject': 'Solicitud de documento',
        #         'email_from': user.email or 'no-reply@example.com',
        #         'email_to': admin_user.email,
        #         'body_html': body_html,
        #     }
        #     mail = self.env['mail.mail'].create(mail_values)
        #     mail.send()
