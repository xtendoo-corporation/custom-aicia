from odoo.http import request, Controller, route
import base64

class PortalApprovalRequestController(Controller):
    @route('/portal/approval_request', auth='user', website=True)
    def approval_request_form(self, **kwargs):
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        return request.render('portal_invoice_requests.portal_hr_employee_request_template', {
            'companies': allowed_companies,
            #averiguar si aprovals es multicompañia
        })

    @route('/portal/approval_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def approval_request_submit(self, **post):
        user_id = request.env.user.id
        company_id = int(post.get('company_id'))
        #averiguar si approvals es multicompañia

        approval_data = request.env['portal.approval.request'].sudo().create({
            'user_id': user_id,
            'company_id': company_id,
        })
        return request.redirect('/my/home')

    #modelo approval.request
    #proporcionar un name segun un selection
    #listar category_id y mostrar solo la categoria que yo quiera
    #approval.approver
    #añadir un segun el selection user_id
    #required true siempre
    #ver si las respuestas en el chatter funcionan bien
