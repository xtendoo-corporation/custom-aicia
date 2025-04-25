import base64
import io
import os
import pdfplumber

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
    status = fields.Selection([('approved_by_director_i_d', 'Aprobación del DIrector I+D'), ('approved_by_director_gerente', 'Aprobación del DIrector Gerente'), ('sign_company', 'Esperando firma de empresa'),('final_revision','Revisión final'), ("approve", 'Aprobada'), ("rejected", 'Rechazada')], 'Estado', default='approved_by_director_i_d' ,tracking=True)
    financial_signature = fields.Binary(string="Firma Director Gerente")
    is_company_signed = fields.Boolean(string='Firmado por la empresa', default=False, tracking=True)

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
