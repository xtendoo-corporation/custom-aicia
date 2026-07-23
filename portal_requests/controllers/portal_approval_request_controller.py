from odoo.http import request, Controller, route
import base64

from .portal_pdf_utils import ensure_pdf


class PortalApprovalRequestController(Controller):
    @route('/portal/approval_request', auth='user', website=True)
    def approval_request_form(self, **kwargs):
        user = request.env.user
        allowed_work_groups = request.env['portal.work.group'].search([('user_ids', 'in', user.id)])
        return request.render('portal_requests.portal_approval_request_template', {'work_groups': allowed_work_groups})

    @route('/portal/approval_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def approval_request_submit(self, **post):
        # Obtener el usuario actual
        user_id = request.env.user.id
        # Obtener los datos del formulario
        approval_type = post.get('approval_type')
        description = post.get('description')
        is_company_signed = post.get('company_signed')
        user_id = request.env.user.id
        work_group_id = post.get('work_group')

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
        approval_type_record = request.env['type.approval'].sudo().search([('name', '=', approval_type)], limit=1)

        if not approval_type_record:
            return request.redirect(
                '/error-page')  # Redirige a una página de error si no se encuentra el tipo de aprobación

        # Crear un nuevo registro en `document.approval`
        new_document_approval = request.env['document.approval'].sudo().create({
            'type_id': approval_type_record.id,
            'description': description,
            'company_id': request.env.user.company_id.id,
            'user_id': request.env.user.id,
            'is_company_signed': is_company_signed,
            'work_group_id': work_group_id,
        })


        attachments = request.httprequest.files.getlist('file')
        ensure_pdf(*attachments)
        for attachment in attachments:
            attachment_data = {
                'name': attachment.filename,
                'res_model': 'document.approval',
                'res_id': new_document_approval.id,
                'datas': base64.b64encode(attachment.read()),
                'type': 'binary',
            }
            request.env['ir.attachment'].sudo().create(attachment_data)
        self.send_request_email(approval_type, new_document_approval)


        return request.redirect('/my/documents/thank-you')

    def send_request_email(self, move_text, document_id):

        env = request.env

        group = request.env.ref('portal_requests.group_director_investigation_and_development').sudo()
        admin_users = group.user_ids

        document_request_link = (
            f"/web#id={document_id.id}"
            f"&cids=1-24-28-29-32-25-30-31"
            f"&menu_id=899&active_id=1"
            f"&model=document.approval&view_type=form"
        )

        user = env.user

        print("*" * 100)
        print("admin_users", admin_users)

        for admin_user in admin_users:

            print("admin_user", admin_user)

            email = admin_user.email
            if not email:
                continue

            body_html = f"""
                <p>Estimado/a {admin_user.name},</p>
                <p>El usuario {user.name} ha creado una solicitud de nuevo documento.</p>
                <ul>
                    <li><strong>Usuario:</strong> {user.name}</li>
                    <li><strong>Tipo:</strong> {move_text}</li>
                    <li>
                        <strong>Enlace:</strong>
                        <a href="{document_request_link}">Solicitud</a>
                    </li>
                </ul>
                <p>Saludos cordiales, Odoo</p>
            """

            mail_values = {
                'subject': 'Solicitud de documento',
                'email_from': user.email or 'no-reply@example.com',
                'email_to': email,
                'body_html': body_html,
            }

            try:
                mail = env['mail.mail'].sudo().create(mail_values)
                env.cr.commit()  # 🔥 ESTO ES LO QUE FALTABA
                mail.sudo().send()  # opcional, pero correcto

            except Exception as e:
                env.cr.rollback()
                print("ERROR enviando mail a", email, e)

        return request.render("portal.email_sent_confirmation")

