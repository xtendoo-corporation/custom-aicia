import base64
import io
import os

from PyPDF2 import PdfFileReader, PdfFileWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from odoo import models, fields, api
from odoo.exceptions import UserError
from PIL import Image

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
    status = fields.Selection([('approved_by_director_i_d', 'Aprobación del DIrector I+D'), ('sign_director_accounting', 'Firma del Director Financiero'), ('sign_company', 'Esperando firma de empresa'), ("approve", 'Aprobada'), ("rejected", 'Rechazada')], 'Estado', default='approved_by_director_i_d' ,tracking=True)
    financial_signature = fields.Binary(string="Firma Director Financiero")

    def add_signature_to_pdf(self):
        """ Abre el PDF, añade la firma y guarda el nuevo PDF en Odoo """

        # Buscar los archivos adjuntos del documento actual
        attachment_ids = self.env['ir.attachment'].search([
            ('res_model', '=', 'document.approval'),
            ('res_id', '=', self.id)
        ], limit=1)  # Solo tomamos el primer adjunto

        if not attachment_ids or not self.financial_signature:
            raise ValueError("Falta el PDF adjunto o la firma")

        # Obtener el contenido del PDF adjunto
        pdf_data = base64.b64decode(attachment_ids.datas)  # Decodificar de base64
        pdf_reader = PdfFileReader(io.BytesIO(pdf_data))
        pdf_writer = PdfFileWriter()

        # Crear un lienzo para la firma
        packet = io.BytesIO()

        # Inicializar el lienzo con un fondo blanco
        can = canvas.Canvas(packet, pagesize=letter)
        can.setFillColorRGB(1, 1, 1)  # Fondo blanco
        can.rect(0, 0, letter[0], letter[1], fill=1)  # Rellenar fondo con blanco

        # Decodificar la firma
        signature_data = base64.b64decode(self.financial_signature)
        signature_path = "/tmp/temp_signature.png"

        # Guardar la firma como imagen temporal
        with open(signature_path, "wb") as f:
            f.write(signature_data)

        # Cargar la imagen con la firma
        signature_image = Image.open(signature_path)

        # Crear una nueva imagen con fondo blanco y tamaño igual al de la firma
        width, height = signature_image.size
        new_image = Image.new('RGB', (width, height), color=(255, 255, 255))  # Fondo blanco
        new_image.paste(signature_image, (0, 0), signature_image)  # Insertar firma con fondo blanco

        # Guardar la nueva imagen con fondo blanco
        signature_with_background_path = "/tmp/temp_signature_with_background.png"
        new_image.save(signature_with_background_path)

        # Insertar la firma en el PDF (posición en coordenadas X, Y)
        # Calculamos el espacio disponible en la página para colocar la firma justo al final
        last_page = pdf_reader.getPage(pdf_reader.getNumPages() - 1)  # Última página del PDF
        last_page_height = last_page.mediaBox.getHeight()

        # Calculamos la posición Y de la firma en la página
        signature_y_position = last_page_height - 150  # Ajusta la posición de la firma en Y (el valor 150 puede variar)

        can.drawImage(signature_with_background_path, 100, signature_y_position, width=200,
                      height=100)  # Ajusta posición y tamaño
        can.save()

        # Fusionar la firma con el PDF original
        packet.seek(0)
        signature_pdf = PdfFileReader(packet)

        for i in range(pdf_reader.getNumPages()):
            page = pdf_reader.getPage(i)
            if i == pdf_reader.getNumPages() - 1:  # Solo firmamos la última página
                page.mergePage(signature_pdf.getPage(0))
            pdf_writer.addPage(page)

        # Guardar el nuevo PDF
        output_pdf = io.BytesIO()
        pdf_writer.write(output_pdf)
        output_pdf.seek(0)

        # Guardar en Odoo como un nuevo adjunto
        new_pdf_data = base64.b64encode(output_pdf.read()).decode('utf-8')  # Convertir a string para Odoo
        attachment_data = {
            'name': f"firmado_{attachment_ids.name}",
            'res_model': 'document.approval',
            'res_id': self.id,
            'datas': new_pdf_data,  # No es necesario volver a codificar en base64
            'type': 'binary',
        }

        signed_attachment = self.env['ir.attachment'].create(attachment_data)

        # Eliminar archivos temporales de la firma
        os.remove(signature_path)
        os.remove(signature_with_background_path)

        return signed_attachment  # Retornamos el nuevo adjunto creado


    def write(self, vals):
        res = super(DocumentApproval, self).write(vals)
        if 'financial_signature' in vals:
            for record in self:
                record.message_post(
                    body="La firma del director financiero ha sido actualizada.",
                    message_type="comment",
                    subtype_xmlid=False
                )
            return res
        return super(DocumentApproval, self).write(vals)

    def _compute_name(self):
        for record in self:
            record.computed_name = f"{record.type_id.name} - {record.description}"

    # def request_partner_sign(self):
    #     print("*"*100)
    #     print("solicitar firmar cliente")
    #     print("*"*100)

    def action_approve(self):
        self.ensure_one()
        if self.status == 'approved_by_director_i_d' and self.env.user.has_group("portal_requests.group_director_investigation_and_development"):
            print("Director I+D aprueba")
            self.status = 'sign_director_accounting'
            user_to_send = self.env['res.users'].search([
                ('groups_id', 'in', self.env.ref('portal_requests.group_financial_director').id)
            ])
            self.send_request_email(self.type_id.name,user_to_send, "approved_by_director_i_d")
        if self.status == 'sign_director_accounting' and self.env.user.has_group("portal_requests.group_financial_director"):
            if not self.financial_signature:
                raise UserError("Por favor, suba la firma del director financiero.")
            print("Financiero aprueba")
            # self.status = 'sign_company'
            user_to_send = self.env['res.users'].search([
                ('groups_id', 'in', self.env.ref('portal_requests.group_director_manager').id)
            ])
            self.add_signature_to_pdf()
            # self.send_request_email(self.type_id.name,user_to_send, "sign_director_accounting")
        if self.status == 'sign_company' and self.env.user.has_group("portal_requests.group_director_manager"):
            print("Director Gerente aprueba")
            self.status = 'approve'
            self.send_request_email(self.type_id.name,self.user_id, "sign_company")

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
            elif type=="sign_director_accounting":
                print("sign_director_accounting")
                admin_name = admin_user.name
                body_html = f"""
                                      <p>Estimado/a {admin_name},</p>
                                      <p>El Director Financiero,{user_for_send}, ya ha firmado la siguiente solicitud:</p>
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
                                      <p>El Director Gerente,{user_for_send}, ha aprobado su solicitud:</p>
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
