from odoo.http import request, Controller, route
import base64


class PortalApprovalRequestController(Controller):
    @route('/portal/approval_request', auth='user', website=True)
    def approval_request_form(self, **kwargs):
        return request.render('portal_invoice_requests.portal_approval_request_template', {})

    @route('/portal/approval_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def approval_request_submit(self, **post):
        # Obtener el usuario actual
        user_id = request.env.user.id
        # Obtener los datos del formulario
        approval_type = post.get('approval_type')
        description = post.get('description')

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

        print("*"*50)
        print(new_document_approval)

        return request.redirect('/contactus-thank-you')
