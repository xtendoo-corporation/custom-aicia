from odoo.http import request, Controller, route


class PortalHrController(Controller):
    @route('/portal/hr_request', auth='user', website=True)
    def hr_request_form(self, **kwargs):
        companies = request.env['res.company'].search([])
        return request.render('portal_invoice_requests.portal_hr_request_template', {
            'companies': companies,
        })

    @route('/portal/hr_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def hr_request_submit(self, **post):
        company_id = post.get('company_id')
        condition = post.get('condition')

        employee = request.env['portal.hr.request'].sudo().create({
            'user_id': request.env.user.id,
            'company_id': int(company_id),
            'condition': condition,
        })

        self.send_hr_email(employee)

        return request.redirect('/contactus-thank-you')

    def send_hr_email(self, employee):
        user_id = employee.user_id
        company_id = employee.company_id
        condition = employee.condition
        body_html = f"""
            <p>Estimado/a Administrador/a,</p>
            <p>El usuario {user_id.name} ha creado una solicitud de contratación para el grupo {company_id.name}.</p>
            <p>A continuación, se detallan los datos de la solicitud:
            <ul>
                <li><strong>Usuario:</strong> {user_id.name}</li>
                <li><strong>Proyecto:</strong> {company_id.name}</li>
                <li><strong>Condición:</strong> {condition}</li>
            </ul>
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
            'subject': f'Solicitud de contratación',
            'email_from': request.env.user.email,
            'email_to': ','.join(email_list),
            'body_html': body_html,
        }

        # Crear el correo en el sistema
        mail = request.env['mail.mail'].create(mail_values)

        # Enviar el correo
        mail.send()

        return request.render("portal.email_sent_confirmation")
