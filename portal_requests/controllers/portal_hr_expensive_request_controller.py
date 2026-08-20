from odoo.http import request, Controller, route
import base64

from .portal_pdf_utils import ensure_pdf

class PortalHrExpensiveRequestController(Controller):
    @route('/portal/hr_expensive_request', auth='user', website=True)
    def hr_expensive_request_form(self, **kwargs):
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        # Obtener las compañías permitidas para el usuario logueado
        allowed_work_groups = request.env['portal.work.group'].search(
            request.env['portal.work.group']._boss_or_administrative_domain(user)
        )
        allowed_companies = request.env['account.analytic.account'].search([
            ('responsible_id', '=', user.id)
        ])

        if allowed_work_groups and user.has_group('portal_requests.group_equip_boss'):
            wg_companies = request.env['account.analytic.account'].search(
                [('work_group_id', 'in', allowed_work_groups.ids)]
            )
            allowed_companies = allowed_companies | wg_companies
        if user.has_group('portal_requests.group_manager'):
            manager_groups = request.env['portal.work.group'].search([('user_ids', 'in', user.id)])
            if manager_groups:
                allowed_companies = allowed_companies | request.env['account.analytic.account'].search(
                    [('work_group_id', 'in', manager_groups.ids)]
                )
        return request.render('portal_requests.portal_hr_expensive_request_template', {
            'companies': allowed_companies,
        })

    @route('/portal/hr_expensive_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def hr_expensive_request_submit(self, **post):
        expensive_type = post.get('expensive_type')
        user_id = post.get('user_id')
        status = 'approved_by_boss_group'
        project = int(post.get('company_id'))
        work_group_id = request.env['account.analytic.account'].sudo().browse(project).work_group_id
        user_to_notify = [work_group_id.equip_boss]
        user_name = request.env['res.users'].sudo().browse(int(user_id)).name
        company_name = request.env['account.analytic.account'].sudo().browse(project).name
        is_more = post.get('is_more')
        #Si solicita el jefe de equipo
        if int(user_id) == int(work_group_id.equip_boss.id):
            status = 'approved_purchase_responsible'
            # Usar sudo para evitar error de permisos al acceder a grupos desde portal
            group_xmlid = (
                'portal_requests.group_intern_partner_responsible'
                if expensive_type == 'gratificacion'
                else 'portal_requests.group_personnel_purchase_responsible'
            )
            group = request.env.ref(group_xmlid).sudo()
            user_to_notify = group.user_ids
        expensive = request.env['portal.hr.expensive.request'].sudo().create({
            'type': expensive_type,
            'user_id': user_id,
            'status': status,
            'project': project,
            'is_more': is_more,
        })
        attachments = request.httprequest.files.getlist('file')
        # La gratificación solo admite un documento (el formulario).
        if expensive_type == 'gratificacion':
            attachments = attachments[:1]
        inventory_attachment = request.httprequest.files.get('inventory_file')
        ensure_pdf(*attachments, inventory_attachment)

        for attachment in attachments:
            attachment_data = {
                'name': attachment.filename,
                'res_model': 'portal.hr.expensive.request',
                'res_id': expensive.id,
                'datas': base64.b64encode(attachment.read()),
                'type': 'binary',
                'mimetype': attachment.content_type or 'application/pdf',
            }
            request.env['ir.attachment'].sudo().create(attachment_data)
        if inventory_attachment:
            name=inventory_attachment.filename
            name="inventario_" + name
            inventory_attachment_data = {
                'name': name,
                'res_model': 'portal.hr.expensive.request',
                'res_id': expensive.id,
                'datas': base64.b64encode(inventory_attachment.read()),
                'type': 'binary',
                'mimetype': inventory_attachment.content_type or 'application/pdf',
            }
            request.env['ir.attachment'].sudo().create(inventory_attachment_data)
        self.send_request_email(user_to_notify,user_name, company_name, expensive)

        return request.redirect('/my/expenses/thank-you')

    def send_request_email(self,to_notify_users, user_name,company_name, expensive_request):
        expensive_request_link = f"/web#id={expensive_request.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=portal.hr.expensive.request&view_type=form"
        for admin_user in to_notify_users:
            admin_name = admin_user.name
            body_html = f"""
                        <p>Estimado/a {admin_name},</p>
                        <p>El usuario {user_name} ha creado una solicitud de gasto en el proyecto {company_name}.</p>
                        <p>A continuación, se detallan los datos de la solicitud:
                        <ul>
                            <li><strong>Usuario:</strong> {user_name}</li>
                            <li><strong>Proyecto:</strong> {company_name}</li>
                            <li><strong>Enlace:</strong> <a href="{expensive_request_link}">Solicitud</a></li>
                        <ul>
                        </p>
                        <p>Saludos cordiales, Odoo</p>
                    """
            email = admin_user.email
            mail_values = {
                'subject': f'Solicitud de Gasto',
                'email_from': request.env.user.email or 'no-reply@example.com',
                'email_to': email,
                'body_html': body_html,
            }
            mail = request.env['mail.mail'].create(mail_values)

            mail.send()

        return request.render("portal.email_sent_confirmation")
