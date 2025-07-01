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
import os
os.environ['_JAVA_OPTIONS'] = '-Xmx256m -Xms128m'

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
    attachment_check = fields.Integer(
        compute='_compute_attachment_check',
        store=False
    )

    @api.depends()
    def _compute_attachment_check(self):
        for record in self:
            attachments = self.env['ir.attachment'].search_count([
                ('res_model', '=', 'document.approval'),
                ('res_id', '=', record.id),
                ('name', 'ilike', '%_firmado%')
            ])
            record.attachment_check = attachments

    # Modifica el campo is_digital_signed para que dependa del campo auxiliar
    is_digital_signed = fields.Boolean(
        string='Firmado digitalmente',
        compute='_compute_is_digital_signed',
        tracking=True,
        store=False
    )

    @api.depends('attachment_check')
    def _compute_is_digital_signed(self):
        for record in self:
            if record.attachment_check > 0:
                record.is_digital_signed = True
            else:
                record.is_digital_signed = False
                if not record.financial_signature and not record.is_company_signed:
                    # Verificar si el valor de attachment_check era mayor a 0 antes de ser 0
                    previous_attachment_count = self.env['ir.attachment'].search_count([
                        ('res_model', '=', 'document.approval'),
                        ('res_id', '=', record.id),
                        ('name', 'ilike', '%_firmado%')
                    ])
                    if previous_attachment_count > 0:
                        # Verificar si ya existe un mensaje similar en el historial
                        mensaje_existe = any(
                            "El documento firmado digitalmente ha sido eliminado por" in mensaje.body
                            for mensaje in record.message_ids
                        )

                        # Solo enviar el mensaje si no existe uno similar
                        if not mensaje_existe:
                            record.sudo().message_post(
                                body=_(
                                    "El documento firmado digitalmente ha sido eliminado por %s") % self.env.user.name,
                                subtype_id=record.env.ref('mail.mt_note').id
                            )


                    # self.sudo().message_post(
                    #     body=_("El documento firmado ha sido eliminado por %s") % self.env.user.name,
                    #     subtype_id=self.env.ref('mail.mt_note').id,
                    # )


    def pdf_signer(self):
        #buscamos el adjunto para firmar
        attachment_ids = self.env['ir.attachment'].search([
            ('res_model', '=', 'document.approval'),
            ('res_id', '=', self.id)
        ], limit=1)
        #buscamos el certificado usando el usario logueado
        user = self.env.user
        certificate = self.env['report.certificate'].search([
            ('company_id', '=', user.company_id.id),
            ('model_id.model', '=', 'document.approval'),
            ('user_ids', 'in', user.id),
        ], limit=1)
        if not certificate:
            raise UserError("No se encontró un certificado para firmar el documento.")
        #verificamos que el adjunto existe
        if not attachment_ids:
            raise UserError("Falta el PDF adjunto o la firma")
        pdf_fd, pdf_path = tempfile.mkstemp(suffix=".pdf", prefix="document.tmp.")
        pdf_signed_path= ""
        try:
            # Obtenemos el contenido del PDF del attachment y lo escribimos en el archivo temporal
            with closing(os.fdopen(pdf_fd, "wb")) as pdf_file:
                pdf_file.write(base64.b64decode(attachment_ids.datas))

            # Firmamos el PDF
            pdf_signed_path = self.env['ir.actions.report'].pdf_sign(pdf_path, certificate)

            # Leemos el PDF firmado
            with open(pdf_signed_path, "rb") as signed_file:
                signed_content = signed_file.read()

            # Creamos un nuevo adjunto con el PDF firmado
            attachment_create = self.env['ir.attachment'].create({
                'name': f"{attachment_ids.name}_firmado",
                'res_model': 'document.approval',
                'res_id': self.id,
                'datas': base64.b64encode(signed_content),
                'type': 'binary',
            })
            # Actualizamos el estado del documento
            self.is_digital_signed = True
            # Registramos en el chatter que el documento ha sido firmado digitalmente
            self.sudo().message_post(
                body=_("El documento ha sido firmado digitalmente por %s") % self.env.user.name,
                subtype_id=self.env.ref('mail.mt_note').id,  # Usar subtipo 'nota' que no envía correos
                attachment_ids=[attachment_create.id]
            )

        finally:
            # Limpieza de archivos temporales
            for fname in [pdf_path, pdf_signed_path]:
                try:
                    if os.path.exists(fname):
                        os.unlink(fname)
                except OSError:
                    _logger.error("Error al intentar eliminar el archivo %s", fname)

        return True

    def add_signature_to_pdf(self):
        """ Añade la firma con fondo blanco solo en la última página del PDF y guarda el nuevo PDF en Odoo """
        if not self.financial_signature:
            return False

        # Buscar el adjunto
        attachment_ids = self.env['ir.attachment'].search([
            ('res_model', '=', 'document.approval'),
            ('res_id', '=', self.id)
        ], limit=1)

        if not attachment_ids:
            raise ValueError("Falta el PDF adjunto o la firma")

        # Decodificar el PDF
        pdf_data = base64.b64decode(attachment_ids.datas)
        pdf_reader = PdfFileReader(io.BytesIO(pdf_data))
        pdf_writer = PdfFileWriter()

        # Procesar la firma para añadir fondo blanco
        signature_data = base64.b64decode(self.financial_signature)
        signature_path = "/tmp/temp_signature.png"
        with open(signature_path, "wb") as f:
            f.write(signature_data)

        signature_image = Image.open(signature_path)
        width, height = signature_image.size
        new_image = Image.new('RGBA', (width, height), (255, 255, 255, 255))  # Fondo blanco
        new_image.paste(signature_image, (0, 0), signature_image.convert("RGBA").split()[3])
        signature_with_background_path = "/tmp/temp_signature_with_background.png"
        new_image.save(signature_with_background_path)

        # Añadir la firma solo en la última página
        last_page_index = pdf_reader.getNumPages() - 1
        for i in range(pdf_reader.getNumPages()):
            page = pdf_reader.getPage(i)

            if i == last_page_index:
                # Crear un lienzo para la última página
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=letter)

                # Dibujar la firma en una posición fija (ajustar según sea necesario)
                can.drawImage(signature_with_background_path, 100, 100, width=200, height=100)
                can.setFont("Helvetica", 12)
                can.drawString(100, 90, "FDO.: Director Gerente")
                can.save()

                # Combinar la firma con la última página
                packet.seek(0)
                signature_pdf = PdfFileReader(packet)
                page.mergePage(signature_pdf.getPage(0))

            pdf_writer.addPage(page)

        # Guardar el PDF firmado
        output_pdf = io.BytesIO()
        pdf_writer.write(output_pdf)
        output_pdf.seek(0)

        new_pdf_data = base64.b64encode(output_pdf.read()).decode('utf-8')
        attachment_data = {
            'name': f"firmado_director_gerente_{attachment_ids.name}",
            'res_model': 'document.approval',
            'res_id': self.id,
            'datas': new_pdf_data,
            'type': 'binary',
        }

        signed_attachment = self.env['ir.attachment'].create(attachment_data)

        # Eliminar archivos temporales
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
            if not self.financial_signature and self.is_digital_signed == False:
                raise UserError("Por favor, añada la firma del director gerente o firme mediante el certificado digital.")
            print("Gerente aprueba")
            if self.financial_signature:
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
        if self.status == 'final_revision' and self.env.user.has_group("portal_requests.group_director_investigation_and_development"):
            print("Jefe de equipo aprueba")
            self.status = 'approve'
            user_to_send = self.env['res.users'].search([
                ('groups_id', 'in', self.env.ref('portal_requests.group_equip_boss').id)
            ])
            self.send_request_email(self.type_id.name,user_to_send, "final_revision")

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
