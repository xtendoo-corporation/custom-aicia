from odoo.http import request, Controller, route

class PortalProjectEndRequestController(Controller):

    @route('/portal/project_end_request', auth='user', website=True)
    def project_end_request_form(self, **kwargs):
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        # Pasar las compañías permitidas al contexto para que se usen en el formulario
        return request.render('portal_requests.portal_project_end_request_template', {
            'companies': allowed_companies,
        })

    @route('/portal/project_end_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def project_end_request_submit(self, **post):
        company_id = int(post.get('company_id'))
        project_end_date = post.get('project_end_date')
        concept = post.get('concept')
        user = request.env.user  # Cambiado para obtener el usuario en lugar del ID

        project_to_finished = request.env['portal.project.end.request'].sudo().create({
            'company_id': company_id,
            'project_end_date': project_end_date,
            'concept': concept,
        })

        # Pasar el objeto usuario completo
        self.send_project_end_email(project_to_finished, user)

        return request.redirect('/my/project_requests/thank-you')

    # Enviar correo electrónico con los detalles de la solicitud de fin de proyecto
    def send_project_end_email(self, project_to_finished, user):
        # Obtener los usuarios del grupo de administradores de ajustes (base.group_system)
        admin_users = request.env['res.users'].search([('groups_id', 'in', request.env.ref('base.group_system').id)])

        # Filtrar usuarios que tienen un correo electrónico válido
        email_list = admin_users.mapped('email')
        email_list = [email for email in email_list if email]  # Solo correos no vacíos

        # Crear el cuerpo del correo
        body_html = f"""
            <p>Estimado/a Administrador</p>
            <p>El usuario {user.name} ha creado una solicitud de cierre de proyecto para el proyecto {project_to_finished.company_id.name}</p>
            <p>A continuación, se detallan los datos de la solicitud:
            <ul>
                <li><strong>Usuario:</strong> {user.name}</li>
                <li><strong>Proyecto:</strong> {project_to_finished.company_id.name}</li>
                <li><strong>Fecha de fin de proyecto:</strong> {project_to_finished.project_end_date}</li>
                <li><strong>Concepto:</strong> {project_to_finished.concept}</li>
            </ul>
            <p>Saludos cordiales, Odoo</p>
            """

        # Crear los valores para el correo, con email_to en formato de cadena
        mail_values = {
            'subject': 'Solicitud de fin de proyecto',
            'email_from': request.env.user.email or 'no-reply@tudominio.com',
            'email_to': ','.join(email_list),  # Convertir a una cadena separada por comas
            'body_html': body_html,
        }

        # Crear el correo en el sistema
        mail = request.env['mail.mail'].create(mail_values)

        # Enviar el correo
        mail.send()

        return request.render("portal.email_sent_confirmation")
