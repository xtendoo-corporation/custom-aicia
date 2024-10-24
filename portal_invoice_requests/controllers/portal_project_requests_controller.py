from odoo.http import request, Controller, route
from odoo import fields
from datetime import datetime
import base64

class PortalInvoiceController(Controller):

    @route('/portal/project_request', auth='user', website=True)
    def project_request_form(self, **kwargs):
        companies = request.env['res.company'].search([])
        return request.render('portal_invoice_requests.portal_project_request_template', {
            'companies': companies,
        })

    @route('/portal/project_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def project_request_submit(self, **post):
        # Procesar los campos de texto
        company_id = post.get('company_id')
        date_start = post.get('date_start')
        date_end = post.get('date_end')
        project_name = post.get('project_name')

        # Procesar los archivos usando request.httprequest.files
        signed_contract = request.httprequest.files.get('signed_contract')
        signed_contract_filename = signed_contract.filename if signed_contract else False
        signed_contract_data = signed_contract.read() if signed_contract else False

        budget_file = request.httprequest.files.get('budget_file')
        budget_file_filename = budget_file.filename if budget_file else False
        budget_file_data = budget_file.read() if budget_file else False

        print(f"Received signed_contract: {signed_contract_filename}")
        print(f"Received budget_file: {budget_file_filename}")

        # Crear el registro del proyecto en Odoo
        project = request.env['portal.project.request'].sudo().create({
            'user_id': request.env.user.id,
            'company_id': int(company_id),
            'date_start': datetime.strptime(date_start, '%Y-%m-%d'),
            'date_end': datetime.strptime(date_end, '%Y-%m-%d'),
            'project_name': project_name,
            'signed_contract': base64.b64encode(signed_contract_data) if signed_contract_data else False,
            'signed_contract_filename': signed_contract_filename,
            'budget_file': base64.b64encode(budget_file_data) if budget_file_data else False,
            'budget_file_filename': budget_file_filename,
        })

        # Enviar el correo con los archivos adjuntos
        self.send_project_email(project, signed_contract_data, signed_contract_filename, budget_file_data,
                                budget_file_filename)

        return request.redirect('/contactus-thank-you')

    # Método para enviar el correo electrónico
    def send_project_email(self, project, signed_contract_data, signed_contract_filename, budget_file_data,
                           budget_file_filename):
        # Recibir los datos del formulario
        user_id = project.user_id
        company_id = project.company_id
        project_name = project.project_name
        date_start = project.date_start.strftime('%d-%m-%Y')
        date_end = project.date_end.strftime('%d-%m-%Y')

        # Crear el cuerpo del mensaje de correo
        body_html = f"""
            <p>Estimado/a Administrador/a,</p>
            <p>El usuario {user_id.name} ha creado una solicitud de proyecto para el grupo {company_id.name}.</p>
            <p>A continuación, se detallan los datos de la solicitud:
            <ul>
                <li><strong>Usuario:</strong> {user_id.name}</li>
                <li><strong>Grupo:</strong> {company_id.name}</li>
                <li><strong>Nombre del proyecto:</strong> {project_name}</li>
                <li><strong>Fecha de inicio:</strong> {date_start}</li>
                <li><strong>Fecha de fin:</strong> {date_end}</li>
            <ul>
            </p>
            <p>Saludos cordiales, Odoo</p>
        """

        # Obtener los usuarios del grupo de administradores de ajustes (base.group_system)
        admin_users = request.env['res.users'].search([('groups_id', 'in', request.env.ref('base.group_system').id)])

        # Filtrar usuarios que tienen un correo electrónico válido
        email_list = admin_users.mapped('email')
        email_list = [email for email in email_list if email]  # Solo correos no vacíos

        # Crear los valores para el correo
        mail_values = {
            'subject': f'Project request: {project_name}',
            'email_from': request.env.user.email,
            'email_to': ','.join(email_list),
            'body_html': body_html,
        }

        # Crear el correo en el sistema
        mail = request.env['mail.mail'].create(mail_values)
        print("*"*80)
        print(f"Email list: {email_list}")
        print(f"Mail created with subject: {mail_values['subject']}")

        attachments = []
        if signed_contract_data:
            attachment = request.env['ir.attachment'].create({
                'name': signed_contract_filename,
                'type': 'binary',
                'datas': base64.b64encode(signed_contract_data),
                'res_model': 'mail.mail',
                'res_id': mail.id,
                'mimetype': 'application/octet-stream',
            })
            attachments.append(attachment.id)

        if budget_file_data:
            attachment = request.env['ir.attachment'].create({
                'name': budget_file_filename,
                'type': 'binary',
                'datas': base64.b64encode(budget_file_data),
                'res_model': 'mail.mail',
                'res_id': mail.id,
                'mimetype': 'application/octet-stream',
            })
            attachments.append(attachment.id)

        # Si hay adjuntos, agregarlos al correo
        if attachments:
            mail.write({'attachment_ids': [(6, 0, attachments)]})

        # Enviar el correo
        mail.send()

        return request.render("portal.email_sent_confirmation")
