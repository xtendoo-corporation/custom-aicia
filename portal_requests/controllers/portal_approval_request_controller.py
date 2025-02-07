from odoo.http import request, Controller, route
import base64


class PortalApprovalRequestController(Controller):
    @route('/portal/approval_request', auth='user', website=True)
    def approval_request_form(self, **kwargs):
        return request.render('portal_requests.portal_approval_request_template', {})

    @route('/portal/approval_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def approval_request_submit(self, **post):
        # Obtener el usuario actual
        user_id = request.env.user.id
        # Obtener los datos del formulario
        approval_type = post.get('approval_type')
        description = post.get('description')
        user_id = request.env.user.id

        if approval_type == "sign_nda":
            approval_type = "Solicitud de firma NDA"
        elif approval_type == "business_contract":
            approval_type = "Solicitud firma contrato con empresa"
        elif approval_type == "collaboration_pas":
            approval_type = "Solicitud colaboración PAS"
        elif approval_type == "exit_authorization":
            approval_type = "Solicitud autorización salida a empresas"
        elif approval_type == "travel_request":
            approval_type = "Solicitud de salida de viaje"
        else: # Si el tipo de aprobación no es válido
            return request.redirect('/portal/approval_request')

        # Buscar el tipo de aprobación correspondiente en `type.approval`
        approval_type_record = request.env['type.approval'].search([('name', '=', approval_type)], limit=1)

        if not approval_type_record:
            return request.redirect(
                '/error-page')  # Redirige a una página de error si no se encuentra el tipo de aprobación

        # Crear un nuevo registro en `document.approval`
        new_document_approval = request.env['document.approval'].create({
            'type_id': approval_type_record.id,  # Asignar el tipo de aprobación
            'description': description,  # Asignar descripción
            'approved': False,  # Inicialmente no aprobado
            'group_approval_id': request.env.user.groups_id[0].id if request.env.user.groups_id else False,
            # Asignar el grupo de aprobación si existe
        })

        # Procesar archivos adjuntos
        attachments = request.httprequest.files.getlist('file')
        for attachment in attachments:
            attachment_data = {
                'name': attachment.filename,
                'res_model': 'document.approval',
                'res_id': new_document_approval.id,
                'datas': base64.b64encode(attachment.read()),
                'type': 'binary',
            }
            request.env['ir.attachment'].create(attachment_data)
        self.send_request_email(approval_type, new_document_approval)


        return request.redirect('/contactus-thank-you')


    def send_request_email(self, move_text,document_id):
        admin_users = request.env['res.users'].search(
            [('groups_id', 'in', request.env.ref('portal_requests.group_director_investigation_and_development').id)])
        document_request_link = f"/web#id={document_id.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=document.approval&view_type=form"
        user_id = request.env.user.id
        user= request.env['res.users'].search([('id', '=', user_id)], limit=1)
        print("*"*100)
        print("admin_users",admin_users)
        for admin_user in admin_users:
            print("admin_user",admin_user)
            admin_name = admin_user.name
            body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>El usuario {user.name} ha creado una solicitud de nuevo documento.</p>
                                <p>A continuación, se detallan los datos de la solicitud:
                                <ul>
                                    <li><strong>Usuario:</strong> {user.name}</li>
                                    <li><strong>Tipo:</strong> {move_text}</li>
                                    <li><strong>Enlace:</strong><a href="{document_request_link}">Solicitud</a></li>
                                <ul>
                                </p>
                                <p>Saludos cordiales, Odoo</p>
                            """
            # Filtrar usuarios que tienen un correo electrónico válido
            email = admin_user.email
            print("email",email)
            #email_list = [email for email in email_list if email]  # Solo correos no vacíos
            # Validar que haya destinatarios
            # if not email_list:
            #     raise ValueError("No hay destinatarios con correo válido en el grupo especificado.")
            mail_values = {
                'subject': f'Solicitud de documento',
                'email_from': request.env.user.email or 'no-reply@example.com',
                'email_to': email,
                'body_html': body_html,
            }
            mail = request.env['mail.mail'].create(mail_values)
            mail.send()

        return request.render("portal.email_sent_confirmation")
