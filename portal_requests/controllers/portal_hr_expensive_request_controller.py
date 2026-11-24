from odoo.http import request, Controller, route
import base64

from .portal_pdf_utils import ensure_pdf

class PortalHrExpensiveRequestController(Controller):
    # Por encima de este importe el gasto requiere al Director Gerente.
    DIRECTOR_THRESHOLD = 10000.0

    @staticmethod
    def _parse_amount(value):
        """Importe del formulario: admite coma o punto decimal. Un valor no
        numérico se trata como cero (el formulario lo rechaza)."""
        try:
            return float((value or '').strip().replace(',', '.'))
        except ValueError:
            return 0.0

    @staticmethod
    def _uploaded_files(field_name):
        return [
            file_storage for file_storage in request.httprequest.files.getlist(field_name)
            if file_storage and file_storage.filename
        ]

    @staticmethod
    def _create_attachment(expensive, file_storage, name=None):
        return request.env['ir.attachment'].sudo().create({
            'name': name or file_storage.filename,
            'res_model': 'portal.hr.expensive.request',
            'res_id': expensive.id,
            'datas': base64.b64encode(file_storage.read()),
            'type': 'binary',
            'mimetype': file_storage.content_type or 'application/pdf',
        })

    @route('/portal/hr_expensive_request', auth='user', website=True)
    def hr_expensive_request_form(self, **kwargs):
        # Obtener el usuario actual
        user = request.env.user
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
        liquidation_amount = 0.0
        ticket_files = invoice_files = []
        payment_order_file = None
        if expensive_type == 'liquidacion_gastos':
            liquidation_amount = self._parse_amount(post.get('liquidation_amount'))
            ticket_files = self._uploaded_files('ticket_files')
            invoice_files = self._uploaded_files('invoice_files')
            if liquidation_amount <= 0 or not (ticket_files or invoice_files):
                return request.redirect('/portal/hr_expensive_request?error=liquidation')
            payment_order_file = next(iter(self._uploaded_files('payment_order_file')), None)
            if payment_order_file and not payment_order_file.filename.lower().endswith(('.xlsx', '.xls', '.xlsm', '.ods')):
                return request.redirect('/portal/hr_expensive_request?error=payment_order')
            ensure_pdf(*ticket_files, *invoice_files)
            # En la liquidación el umbral se decide con el total declarado.
            is_more = liquidation_amount > self.DIRECTOR_THRESHOLD
        requester = request.env['res.users'].sudo().browse(int(user_id))
        # A petición del cliente, el Administrativo vuelve a pasar por la
        # aprobación del Jefe de Equipo: solo el propio Jefe de Equipo
        # solicita directamente al Responsable de Compras (o de
        # Clientes/Becarios para gratificaciones).
        if int(requester.id) == int(work_group_id.equip_boss.id):
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
            'liquidation_amount': liquidation_amount,
        })
        if expensive_type == 'liquidacion_gastos':
            for ticket_file in ticket_files:
                self._create_attachment(expensive, ticket_file)
            invoice_attachments = request.env['ir.attachment'].sudo()
            for invoice_file in invoice_files:
                invoice_attachments |= self._create_attachment(expensive, invoice_file)
            expensive.employee_invoice_attachment_ids = invoice_attachments
            if payment_order_file:
                expensive.payment_order_attachment_ids = self._create_attachment(
                    expensive, payment_order_file, name="orden_pago_" + payment_order_file.filename)
        else:
            attachments = self._uploaded_files('file')
            # La gratificación solo admite un documento (el formulario).
            if expensive_type == 'gratificacion':
                attachments = attachments[:1]
            inventory_attachment = next(iter(self._uploaded_files('inventory_file')), None)
            ensure_pdf(*attachments, inventory_attachment)
            for attachment in attachments:
                self._create_attachment(expensive, attachment)
            if inventory_attachment:
                self._create_attachment(
                    expensive, inventory_attachment, name="inventario_" + inventory_attachment.filename)
        self.send_request_email(user_to_notify,user_name, company_name, expensive)

        return request.redirect('/my/expenses/thank-you')

    def send_request_email(self,to_notify_users, user_name,company_name, expensive_request):
        backend_link = f"/web#id={expensive_request.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=portal.hr.expensive.request&view_type=form"
        for admin_user in to_notify_users:
            admin_name = admin_user.name
            # El Jefe de Equipo es usuario de portal: enlace al portal.
            expensive_request_link = expensive_request._notify_link_for(admin_user, backend_link)
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
            mail = request.env['mail.mail'].sudo().create(mail_values)

            mail.send()

        return request.render("portal.email_sent_confirmation")
