from odoo.http import request, Controller, route
from odoo import fields
from odoo import http
from datetime import datetime
import json

class PortalInvoiceController(Controller):

    @route('/portal/project_request', auth='user', website=True)
    def project_request_form(self, **kwargs):
        return request.render('portal_invoice_requests.portal_project_request_template', {})

    @route('/portal/project_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def project_request_submit(self, **post):
        date_start = post.get('date_start')
        date_end = post.get('date_end')
        project_name = post.get('project_name')
        project = request.env['portal.project.request'].sudo().create({
            'date_start': datetime.strptime(date_start, '%Y-%m-%d'),
            'date_end': datetime.strptime(date_end, '%Y-%m-%d'),
            'project_name': project_name,
        })
        self.send_project_email(**post)

        return request.redirect('/thanks-project-send')

    # VER COMO MEJORAR
    @http.route('/portal/send_project_email', type='http', auth='public', methods=['POST'], csrf=True, website=True)
    def send_project_email(self, **post):
        # Recibir los datos del formulario
        project_name = post.get('project_name')
        date_start = post.get('date_start')
        date_end = post.get('date_end')

        # Formatear las fechas en formato legible
        date_start_formatted = datetime.strptime(date_start, '%Y-%m-%d').strftime('%d-%m-%Y')
        date_end_formatted = datetime.strptime(date_end, '%Y-%m-%d').strftime('%d-%m-%Y')

        # Crear el cuerpo del mensaje de correo
        body_html = f"""
            <p>Hello,</p>
            <p>A new project has been created with the following details:</p>
            <ul>
                <li><strong>Project Name:</strong> {project_name}</li>
                <li><strong>Start Date:</strong> {date_start_formatted}</li>
                <li><strong>End Date:</strong> {date_end_formatted}</li>
            </ul>
            <p>Best regards,<br/>Your Portal</p>
            """

        # Valores para enviar el correo
        mail_values = {
            'subject': f'New Project: {project_name}',
            'email_from': request.env.user.email,  # El correo del usuario logueado
            'email_to': 'salvador.gon.jim@gmail.com',  # Correo destino
            'body_html': body_html,  # Cuerpo del correo en HTML
        }

        # Enviar el correo usando el modelo mail.mail de Odoo
        request.env['mail.mail'].create(mail_values).send()

        # Redirigir a una página de éxito o mostrar un mensaje de confirmación
        return request.render("portal.email_sent_confirmation")

    @http.route('/get_partners_by_company', type='http', auth="user")
    def get_partners_by_company(self, company_id):
        try:
            # Buscar partners relacionados con la compañía seleccionada
            partners = request.env['res.partner'].search([('company_id', '=', int(company_id))])

            # Crear la respuesta JSON con los datos de los partners
            partners_data = [{'id': partner.id, 'name': partner.name} for partner in partners]

            # Retornar los datos en formato JSON
            return request.make_response(
                json.dumps({'partners': partners_data}),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'error': str(e)}),
                headers={'Content-Type': 'application/json'},
                status=400
            )
