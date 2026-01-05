from odoo.http import request, Controller, route
from odoo import fields
from datetime import datetime
import base64

class PortalInvoiceController(Controller):

    @route('/portal/project_request', auth='user', website=True)
    def project_request_form(self, **kwargs):
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        allowed_work_groups = request.env['portal.work.group'].search([('user_ids', 'in', user.id)])
        allowed_clients = request.env['res.partner'].search([('company_id', '=', request.env.company.id)])
        project_allowed = request.env['account.analytic.account'].search([
            ('work_group_id', 'in', allowed_work_groups.ids),
            ('active', '=', True)
        ])

        print("*"*100)
        print("allowed_work_groups", allowed_work_groups)
        print("project_allowed", project_allowed)
        print("*"*100)
        # Pasar las compañías permitidas al contexto para que se usen en el formulario
        return request.render('portal_requests.portal_project_request_template', {
            'companies': allowed_companies,
            'work_groups': allowed_work_groups,
            'clients': allowed_clients,
            'actual_company': request.env.company.id,
            'project_allowed': project_allowed,
        })

    @route('/portal/project_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def project_request_submit(self, **post):
        type = post.get('type_id')
        if type == 'new':
            # Procesar los campos de texto
            company_id = post.get('company_id')
            work_group_id = post.get('work_group_id')
            date_start = post.get('date_start')
            date_end = post.get('date_end')
            project_name = post.get('project_name')
            partner_id_char = post.get('partner_id_char')

            # Procesar los archivos usando request.httprequest.files
            signed_contract = request.httprequest.files.get('signed_contract')
            signed_contract_filename = signed_contract.filename if signed_contract else False
            signed_contract_data = signed_contract.read() if signed_contract else False

            budget_file = request.httprequest.files.get('budget_file')
            budget_file_filename = budget_file.filename if budget_file else False
            budget_file_data = budget_file.read() if budget_file else False

            # Crear el registro del proyecto en Odoo
            project = request.env['portal.project.request'].sudo().create({
                'user_id': request.env.user.id,
                'company_id': int(company_id),
                'work_group_id': int(work_group_id),
                'partner_id_char': partner_id_char,
                'date_start': datetime.strptime(date_start, '%Y-%m-%d'),
                'date_end': datetime.strptime(date_end, '%Y-%m-%d'),
                'project_name': project_name,
                'signed_contract': base64.b64encode(signed_contract_data) if signed_contract_data else False,
                'signed_contract_filename': signed_contract_filename,
                'budget_file': base64.b64encode(budget_file_data) if budget_file_data else False,
                'budget_file_filename': budget_file_filename,
                'type': type,
            })
            print(f"Project created: {project}")
            # Procesar archivos adjuntos
            attachments = []
            if signed_contract:
                attachments.append(request.env['ir.attachment'].create({
                    'name': signed_contract.filename,
                    'type': 'binary',
                    'datas': base64.b64encode(signed_contract.read()),
                    'res_model': 'portal.project.request',
                    'res_id': project.id,
                    'mimetype': 'application/pdf',
                }))
                if budget_file:
                    attachments.append(request.env['ir.attachment'].create({
                        'name': budget_file.filename,
                        'type': 'binary',
                        'datas': base64.b64encode(budget_file.read()),
                        'res_model': 'portal.project.request',
                        'res_id': project.id,
                        'mimetype': 'application/pdf',
                    }))
            self.send_project_email(project)

        elif type == 'end':
            company_id = request.env.company.id
            analytic_id = post.get('company_id_end')
            project_end_date = post.get('project_end_date')
            concept = post.get('concept')
            project_name = request.env['account.analytic.account'].browse(int(analytic_id)).name
            project = request.env['portal.project.request'].sudo().create({
                'user_id': request.env.user.id,
                'company_id': int(company_id),
                'analytic_account_id': int(analytic_id),
                'project_name': project_name,
                'date_end': datetime.strptime(project_end_date, '%Y-%m-%d'),
                'concept': concept,
                'type': type,
            })
            self.send_project_email(project)

        return request.redirect('/contactus-thank-you')

    # @route('/portal/project_request/submit', type='http', auth='user', website=True, methods=['POST'])
    # def project_request_submit(self, **post):
    #     type = post.get('type_id')
    #     if type == 'new':
    #         # Procesar los campos de texto
    #         company_id = post.get('company_id')
    #         date_start = post.get('date_start')
    #         date_end = post.get('date_end')
    #         project_name = post.get('project_name')
    #
    #         # Procesar los archivos usando request.httprequest.files
    #         signed_contract = request.httprequest.files.get('signed_contract')
    #         signed_contract_filename = signed_contract.filename if signed_contract else False
    #         signed_contract_data = signed_contract.read() if signed_contract else False
    #
    #         budget_file = request.httprequest.files.get('budget_file')
    #         budget_file_filename = budget_file.filename if budget_file else False
    #         budget_file_data = budget_file.read() if budget_file else False
    #
    #         # Crear el registro del proyecto en Odoo
    #         project = request.env['portal.project.request'].sudo().create({
    #             'user_id': request.env.user.id,
    #             'company_id': int(company_id),
    #             'date_start': datetime.strptime(date_start, '%Y-%m-%d'),
    #             'date_end': datetime.strptime(date_end, '%Y-%m-%d'),
    #             'project_name': project_name,
    #             'signed_contract': base64.b64encode(signed_contract_data) if signed_contract_data else False,
    #             'signed_contract_filename': signed_contract_filename,
    #             'budget_file': base64.b64encode(budget_file_data) if budget_file_data else False,
    #             'budget_file_filename': budget_file_filename,
    #             'type': type,
    #         })
    #         print(f"Project created: {project}")
    #         # Procesar archivos adjuntos
    #         attachments = []
    #         if signed_contract:
    #             attachments.append(request.env['ir.attachment'].create({
    #                 'name': signed_contract.filename,
    #                 'type': 'binary',
    #                 'datas': base64.b64encode(signed_contract.read()),
    #                 'res_model': 'portal.project.request',
    #                 'res_id': project.id,
    #                 'mimetype': 'application/pdf',
    #             }))
    #             if budget_file:
    #                 attachments.append(request.env['ir.attachment'].create({
    #                     'name': budget_file.filename,
    #                     'type': 'binary',
    #                     'datas': base64.b64encode(budget_file.read()),
    #                     'res_model': 'portal.project.request',
    #                     'res_id': project.id,
    #                     'mimetype': 'application/pdf',
    #                 }))
    #         self.send_project_email(project)
    #
    #     elif type == 'end':
    #         company_id = post.get('company_id_end')
    #         project_end_date = post.get('project_end_date')
    #         concept = post.get('concept')
    #         company_name = request.env['res.company'].browse(int(company_id)).name
    #         project = request.env['portal.project.request'].sudo().create({
    #             'user_id': request.env.user.id,
    #             'company_id': int(company_id),
    #             'project_name': company_name,
    #             'date_end': datetime.strptime(project_end_date, '%Y-%m-%d'),
    #             'concept': concept,
    #             'type': type,
    #         })
    #         self.send_project_email(project)
    #
    #
    #
    #     return request.redirect('/contactus-thank-you')

    # Método para enviar el correo electrónico
    def send_project_email(self, project ):
        group = self.env.ref('portal_requests.group_director_investigation_and_development')
        admin_users = group.user_ids
        # admin_users = request.env['res.users'].search(
        #     [('groups_id', 'in', request.env.ref('portal_requests.group_director_investigation_and_development').id)])
        project_request_link = f"/web#id={project.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=portal.project.request&view_type=form"
        if project.type == 'new':
            for admin_user in admin_users:
                admin_name = admin_user.name
                body_html = f"""
                    <p>Estimado/a {admin_name},</p>
                    <p>El usuario {project.user_id.name} ha creado una solicitud de nuevo proyecto para el grupo {project.company_id.name}.</p>
                    <p>A continuación, se detallan los datos de la solicitud:
                    <ul>
                        <li><strong>Usuario:</strong> {project.user_id.name}</li>
                        <li><strong>Grupo:</strong> {project.company_id.name}</li>
                        <li><strong>Nombre del proyecto:</strong> {project.project_name}</li>
                        <li><strong>Fecha de inicio:</strong> {project.date_start.strftime('%d-%m-%Y')}</li>
                        <li><strong>Fecha de fin:</strong> {project.date_end.strftime('%d-%m-%Y')}</li>
                        <li><strong>Enlace:</strong><a href="{project_request_link}">Solicitud</a></li>
                    <ul>
                    </p>
                    <p>Saludos cordiales, Odoo</p>
                """
                email = admin_user.email
                mail_values = {
                    'subject': f'Solicitud de Nuevo Proyecto',
                    'email_from': request.env.user.email or 'no-reply@example.com',
                    'email_to': email,
                    'body_html': body_html,
                }
                mail = request.env['mail.mail'].create(mail_values)
                mail.send()
        else:
            for admin_user in admin_users:
                admin_name = admin_user.name
                body_html = f"""
                               <p>Estimado/a {admin_name},</p>
                               <p>El usuario {project.user_id.name} ha creado una solicitud de finalización de proyecto del grupo {project.company_id.name}.</p>
                               <p>A continuación, se detallan los datos de la solicitud:
                               <ul>
                                   <li><strong>Usuario:</strong> {project.user_id.name}</li>
                                   <li><strong>Grupo:</strong> {project.company_id.name}</li>
                                   <li><strong>Nombre del proyecto:</strong> {project.project_name}</li>
                                   <li><strong>Fecha de fin:</strong> {project.date_end.strftime('%d-%m-%Y')}</li>
                                   <li><strong>Enlace:</strong><a href="{project_request_link}">Solicitud</a></li>
                               <ul>
                               </p>
                               <p>Saludos cordiales, Odoo</p>
                           """
                email = admin_user.email
                mail_values = {
                    'subject': f'Solicitud de Finalización de proyecto',
                    'email_from': request.env.user.email or 'no-reply@example.com',
                    'email_to': email,
                    'body_html': body_html,
                }
                mail = request.env['mail.mail'].create(mail_values)
                mail.send()
            return request.render("portal.email_sent_confirmation")
