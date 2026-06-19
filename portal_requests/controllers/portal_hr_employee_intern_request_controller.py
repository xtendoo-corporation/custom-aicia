from odoo.http import request, Controller, route
import base64



class PortalHrEmployeeRequestController(Controller):
    @route('/portal/hr_employee_intern_request', auth='user', website=True)
    def hr_employee_intern_request_form(self, **kwargs):
        employee_types = request.env['hr.contract.type'].search([])
        jobs = request.env['hr.job'].search([])
        resource_calendar_id = request.env['resource.calendar'].search([])
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        # options = request.env['hr.departure.wizard']._fields['departure_reason_id']._description_selection(
        #     request.env)
        options = request.env['hr.departure.reason'].search([])
        print("/"*100)
        print("options",options)
        print("/"*100)
        return request.render('portal_requests.portal_hr_employee_intern_request_template', {
            'employee_types': employee_types,
            'jobs': jobs,
            'resource_calendar_id': resource_calendar_id,
            'companies': allowed_companies,
            'options': options,
        })

    @route('/portal/hr_employee_intern_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def hr_employee_intern_request_submit(self, **post):
        request_type = post.get('type_id')
        company_id = int(post.get('company_id'))
        user_id = request.env.user.id
        if request_type == 'new':
            name = post.get('name')
            identification_id = post.get('identification_id')
            mobile_phone = post.get('mobile_phone')
            confidential_compromise = post.get('confidential_compromise')
            work_email = post.get('work_email')
            salary = float(post.get('salary'))
            number_of_pays = int(post.get('number_of_pays'))
            resource_calendar_id = int(post.get('resource_calendar_id'))
            bank_account = post.get('bank_account')
            working_life_report = request.httprequest.files.get('working_life_report')
            cv = request.httprequest.files.get('cv')
            prl_annex = request.httprequest.files.get('prl_annex')
            employee = request.env['portal.hr.employee.intern.request'].sudo().create({
                'user_id': user_id,
                'name': name,
                'identification_id': identification_id,
                'mobile_phone': mobile_phone,
                'confidential_compromise': confidential_compromise,
                'work_email': work_email,
                'salary': salary,
                'number_of_pays': number_of_pays,
                'resource_calendar_id': resource_calendar_id,
                'bank_account': bank_account,
                'company_id': company_id,
                'type': request_type,
            })
            #Procesar archivos adjuntos
            attachments = []
            if working_life_report:
                attachments.append(request.env['ir.attachment'].create({
                    'name': working_life_report.filename,
                    'type': 'binary',
                    'datas': base64.b64encode(working_life_report.read()),
                    'res_model': 'portal.hr.employee.intern.request',
                    'res_id': employee.id,
                    'mimetype': 'application/pdf',
                }))
            if cv:
                attachments.append(request.env['ir.attachment'].create({
                    'name': cv.filename,
                    'type': 'binary',
                    'datas': base64.b64encode(cv.read()),
                    'res_model': 'portal.hr.employee.intern.request',
                    'res_id': employee.id,
                    'mimetype': 'application/pdf',
                }))
            if prl_annex:
                attachments.append(request.env['ir.attachment'].create({
                    'name': prl_annex.filename,
                    'type': 'binary',
                    'datas': base64.b64encode(prl_annex.read()),
                    'res_model': 'portal.hr.employee.intern.request',
                    'res_id': employee.id,
                    'mimetype': 'application/pdf',
                })
            )
            self.send_intern_mail(employee, request_type)

        elif request_type == 'alta':
            employee_inactive_id = int(post.get('employee_id_unactive'))
            employee_name = request.env['hr.employee'].sudo().search([('id', '=', employee_inactive_id), ('active', '=', False)]).name
            alta_date = post.get('alta_date')
            employee = request.env['portal.hr.employee.intern.request'].sudo().create({
                'user_id': user_id,
                'name': employee_name,
                'type': request_type,
                'company_id': company_id,
                'employee_id': employee_inactive_id,
                'alta_date': alta_date,
            })

        else:
            employee_active_id = int(post.get('employee_id_active'))
            employee_name = request.env['hr.employee'].sudo().search([('id', '=', employee_active_id)]).name
            baja_date = post.get('baja_date')
            baja_reason = post.get('baja_reason')
            baja_notes = post.get('baja_notes')
            employee = request.env['portal.hr.employee.intern.request'].sudo().create({
                'user_id': user_id,
                'name': employee_name,
                'type': request_type,
                'company_id': company_id,
                'employee_id': employee_active_id,
                'baja_date': baja_date,
                'baja_reason_id': baja_reason,
                'baja_description': baja_notes,
            })
            self.send_intern_mail(employee, request_type)

        return request.redirect('/contactus-thank-you')


    def send_intern_mail(self, intern, request_type):
        intern_request_link = f"/web#id={intern.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=portal.hr.employee.intern.request&view_type=form"
        user_id = intern.user_id
        if request_type == 'new':
            admin_users = request.env['res.users'].search(
                [('groups_id', 'in', request.env.ref('portal_requests.group_intern_partner_responsible').id)])
            for admin_user in admin_users:
                admin_name = admin_user.name
                body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>El usuario {user_id.name} ha creado una solicitud de nuevo becario en el proyecto {intern.company_id.name}.</p>
                                <p>A continuación, se detallan los datos de la solicitud:
                                <ul>
                                    <li><strong>Usuario:</strong> {user_id.name}</li>
                                    <li><strong>Proyecto:</strong> {intern.company_id.name}</li>
                                    <li><strong>Nombre: </strong> {intern.name}</li>
                                    <li><strong>Enlace:</strong> <a href="{intern_request_link}">Solicitud</a></li>
                                <ul>
                                </p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                email = admin_user.email
                mail_values = {
                    'subject': f'Solicitud de nuevo becario',
                    'email_from': request.env.user.email or 'no-reply@example.com',
                    'email_to': email,
                    'body_html': body_html,
                }
                mail = request.env['mail.mail'].create(mail_values)

                mail.send()
        elif request_type == 'baja':
            admin_users = request.env['res.users'].search(
                [('groups_id', 'in', request.env.ref('portal_requests.group_intern_partner_responsible').id)])
            for admin_user in admin_users:
                admin_name = admin_user.name
                body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>El usuario {user_id.name} ha creado una solicitud de baja del becario {intern.name} del proyecto {intern.company_id.name}.</p>
                                <p>A continuación, se detallan los datos de la solicitud:
                                <ul>
                                    <li><strong>Usuario:</strong> {user_id.name}</li>
                                    <li><strong>Proyecto:</strong> {intern.company_id.name}</li>
                                    <li><strong>Nombre: </strong> {intern.name}</li>
                                    <li><strong>Enlace:</strong> <a href="{intern_request_link}">Solicitud</a></li>
                                <ul>
                                </p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                email = admin_user.email
                mail_values = {
                    'subject': f'Solicitud de baja de becario',
                    'email_from': request.env.user.email or 'no-reply@example.com',
                    'email_to': email,
                    'body_html': body_html,
                }
                mail = request.env['mail.mail'].create(mail_values)

                mail.send()


        return request.render("portal.email_sent_confirmation")


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
