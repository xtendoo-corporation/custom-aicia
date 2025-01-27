from odoo.http import request, Controller, route
import base64


class PortalHrEmployeeRequestController(Controller):
    @route('/portal/hr_employee_request', auth='user', website=True)
    def hr_employee_request_form(self, **kwargs):
        employee_types = request.env['hr.contract.type'].search([])
        jobs = request.env['hr.job'].search([])
        resource_calendar_id = request.env['resource.calendar'].search([])
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        return request.render('portal_requests.portal_hr_employee_request_template', {
            'employee_types': employee_types,
            'jobs': jobs,
            'resource_calendar_id': resource_calendar_id,
            'companies': allowed_companies,
        })

    @route('/portal/hr_employee_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def hr_employee_request_submit(self, **post):
        user_id = request.env.user.id
        name = post.get('name')
        identification_id = post.get('identification_id')
        mobile_phone = post.get('mobile_phone')
        ssnid = post.get('ssnid')
        confidential_compromise = post.get('confidential_compromise')
        work_email = post.get('work_email')
        salary = float(post.get('salary'))
        number_of_pays = int(post.get('number_of_pays'))
        resource_calendar_id = int(post.get('resource_calendar_id'))
        bank_account = post.get('bank_account')
        company_id = int(post.get('company_id'))

        working_life_report = request.httprequest.files.get('working_life_report')
        working_life_report_filename = working_life_report.filename if working_life_report else False
        working_life_report_data = working_life_report.read() if working_life_report else False
        cv = request.httprequest.files.get('cv')
        cv_filename = cv.filename if cv else False
        cv_data = cv.read() if cv else False
        prl_annex = request.httprequest.files.get('prl_annex')
        prl_annex_filename = prl_annex.filename if prl_annex else False
        prl_annex_data = prl_annex.read() if prl_annex else False

        # employee_data = request.env['portal.hr.employee.request'].sudo().create({
        #     'user_id': user_id,
        #     'name': name,
        #     'identification_id': identification_id,
        #     'mobile_phone': mobile_phone,
        #     'ssnid': ssnid,
        #     'confidential_compromise': confidential_compromise,
        #     'working_life_report': base64.b64encode(working_life_report_data) if working_life_report_data else False,
        #     'working_life_report_filename': working_life_report_filename,
        #     'cv': base64.b64encode(cv_data) if cv_data else False,
        #     'cv_filename': cv_filename,
        #     'work_email': work_email,
        #     'prl_annex': base64.b64encode(prl_annex_data) if prl_annex_data else False,
        #     'prl_annex_filename': prl_annex_filename,
        #     'salary': salary,
        #     'number_of_pays': number_of_pays,
        #     'resource_calendar_id': resource_calendar_id,
        #     'bank_account': bank_account,
        #     'company_id': company_id,
        # })
        #
        # self.send_employee_email(employee_data, working_life_report_data, working_life_report_filename, cv_data,
        #                          cv_filename, prl_annex_data, prl_annex_filename)

        return request.redirect('/contactus-thank-you')

    def create_employee(self, employee_data):
        employee = request.env['hr.employee'].sudo()

        new_employee = employee.create({
            'name': employee_data.name,
            'identification_id': employee_data.identification_id,
            'mobile_phone': employee_data.mobile_phone,
            'ssnid': employee_data.ssnid,
            # 'confidential_compromise': employee_data.confidential_compromise,
            'work_email': employee_data.work_email,
            # 'salary': employee_data.salary,
            # 'number_of_pays': employee_data.number_of_pays,
            'resource_calendar_id': employee_data.resource_calendar_id.id,
            'bank_account_id': request.env['res.partner.bank'].create({
                'acc_number': employee_data.bank_account,
                'partner_id': employee_data.company_id.partner_id.id,
            }).id,
            'company_id': employee_data.company_id.id,
        })

        # Adjuntar archivos al empleado
        attachments = []
        if employee.working_life_report:
            attachments.append(request.env['ir.attachment'].create({
                'name': employee.working_life_report_filename,
                'type': 'binary',
                'datas': employee.working_life_report,
                'res_model': 'hr.employee',
                'res_id': new_employee.id,
                'mimetype': 'application/pdf',
            }))
        if employee.cv:
            attachments.append(request.env['ir.attachment'].create({
                'name': employee.cv_filename,
                'type': 'binary',
                'datas': employee.cv,
                'res_model': 'hr.employee',
                'res_id': new_employee.id,
                'mimetype': 'application/pdf',
            }))
        if employee.prl_annex:
            attachments.append(request.env['ir.attachment'].create({
                'name': employee.prl_annex_filename,
                'type': 'binary',
                'datas': employee.prl_annex,
                'res_model': 'hr.employee',
                'res_id': new_employee.id,
                'mimetype': 'application/pdf',
            }))

        # Retornar el empleado creado
        return new_employee

    # Enviar correo electrónico con los detalles del empleado
    def send_employee_email(self, employee_data, working_life_report_data, working_life_report_filename, cv_data,
                            cv_filename, prl_annex_data, prl_annex_filename):
        # Obtener el creador de la factura
        user_id = employee_data.user_id
        company_name = employee_data.company_id.name

        body_html = f"""
            <p>El usuario {user_id.name} ha solicitado la creación de un nuevo empleado en el proyecto {employee_data.company_id.name}.</p>
            <p>Por favor, revise los detalles del empleado y proceda con la creación del mismo.</p>
            <p><strong>Nombre:</strong> {employee_data.name}</p>
            <p><strong>Identificación:</strong> {employee_data.identification_id}</p>
            <p><strong>Teléfono móvil:</strong> {employee_data.mobile_phone}</p>
            <p><strong>SSNID:</strong> {employee_data.ssnid}</p>
            <p><strong>Compromiso de confidencialidad:</strong> {'Si' if employee_data.confidential_compromise else 'No'}</p>
            <p><strong>Correo electrónico:</strong> {employee_data.work_email}</p>
            <p><strong>Salario:</strong> {employee_data.salary}</p>
            <p><strong>Número de pagas:</strong> {employee_data.number_of_pays}</p>
            <p><strong>Horario laboral:</strong> {employee_data.resource_calendar_id.name}</p>
            <p><strong>Cuenta bancaria:</strong> {employee_data.bank_account}</p>
            <p><strong>Equipo de trabajo:</strong> {employee_data.company_id.name}</p>
        """

        # Obtener los usuarios del grupo de administradores de ajustes (base.group_system)
        admin_users = request.env['res.users'].search([('groups_id', 'in', request.env.ref('base.group_system').id)])

        # Filtrar usuarios que tienen un correo electrónico válido
        email_list = admin_users.mapped('email')
        email_list = [email for email in email_list if email]  # Solo correos no vacíos

        # Crear los valores para el correo
        mail_values = {
            'subject': f'Solicitud: Creación de empleado en {employee_data.company_id.name}',
            'email_from': request.env.user.email,
            'email_to': ','.join(email_list),
            'body_html': body_html,
        }

        # Crear el correo en el sistema
        mail = request.env['mail.mail'].create(mail_values)

        attachments = []
        if working_life_report_data:
            attachment = request.env['ir.attachment'].create({
                'name': working_life_report_filename,
                'type': 'binary',
                'datas': base64.b64encode(working_life_report_data),
                'res_model': 'mail.mail',
                'res_id': mail.id,
                'mimetype': 'application/pdf',
            })
            attachments.append(attachment.id)
        if cv_data:
            attachment = request.env['ir.attachment'].create({
                'name': cv_filename,
                'type': 'binary',
                'datas': base64.b64encode(cv_data),
                'res_model': 'mail.mail',
                'res_id': mail.id,
                'mimetype': 'application/pdf',
            })
            attachments.append(attachment.id)
        if prl_annex_data:
            attachment = request.env['ir.attachment'].create({
                'name': prl_annex_filename,
                'type': 'binary',
                'datas': base64.b64encode(prl_annex_data),
                'res_model': 'mail.mail',
                'res_id': mail.id,
                'mimetype': 'application/pdf',
            })
            attachments.append(attachment.id)
        # Si hay adjuntos, agregarlos al correo
        if attachments:
            mail.write({'attachment_ids': [(6, 0, attachments)]})

        # Enviar el correo
        mail.send()

        return request.render("portal.email_sent_confirmation")
