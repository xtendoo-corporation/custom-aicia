from odoo.http import request, Controller, route
import base64

class PortalApprovalRequestController(Controller):
    @route('/portal/approval_request', auth='user', website=True)
    def approval_request_form(self, **kwargs):
        user = request.env.user
        approver_id = request.env['res.users'].search([])

        return request.render('portal_invoice_requests.portal_approval_request_template', {
            'approver_id': approver_id,
        })

    @route('/portal/approval_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def approval_request_submit(self, **post):
        user_id = request.env.user.id
        approval_type = post.get('approval_type')
        approver_id = int(post.get('approver_id'))

        # Crear el registro de solicitud.
        approval_data = {
            'name': approval_type,
            'category_id': request.env.ref('portal_invoice_requests.approval_category_data_general_approval_aicia').id,
            'approval_type': approval_type,
            'approver_id': approver_id,
        }

        self.create_approval_request(approval_data)
        return request.redirect('/contactus-thank-you')

    def create_approval_request(self, approval_data):
        return request.env['approval.request'].sudo().create(approval_data)



    #modelo approval.request
    #proporcionar un name segun un selection
    #listar category_id y mostrar solo la categoria que yo quiera
    #approval.approver
    #añadir un segun el selection user_id
    #required true siempre
    #ver si las respuestas en el chatter funcionan bien
