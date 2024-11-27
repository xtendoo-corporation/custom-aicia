from odoo.http import request, Controller, route

from odoo.custom.src.odoo.odoo.tools.safe_eval import datetime


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
        #obtener fecha actual
        fecha_actual = datetime.now()

        # Buscar la categoría correspondiente en `document.page`
        category = request.env['document.page'].search([('name', '=', approval_type), ('type', '=', 'category')], limit=1)
        if not category:
            return request.redirect('/error-page')  # Redirige a una página de error si no se encuentra la categoría

        # Crear un nuevo registro en `document.page` como hijo de la categoría
        new_document = request.env['document.page'].create({
            'name': f"Solicitud de {category.name}",  # Asignar un nombre al documento
            'parent_id': category.id,  # Asignar la categoría como el padre
            'approval_required': True,  # Si aplica, basado en la categoría
            'draft_summary': description,  # Asignar descripción si corresponde
            'draft_name': description,  # Asignar descripción si corresponde
        })

        # # (Opcional) Crear un registro en `portal.approval.request` relacionado con el documento
        # approval_request = request.env['portal.approval.request'].create({
        #     'user_id': user_id,
        #     'approval_type': approval_type,
        #     'description': description,
        #     'category_id': category.id,  # Relacionar con la categoría
        # })

        return request.redirect('/contactus-thank-you')
