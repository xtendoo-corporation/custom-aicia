from odoo.http import request, Controller, route
import base64

class PortalHrExpensiveRequestController(Controller):
    @route('/portal/hr_expensive_request', auth='user', website=True)
    def hr_expensive_request_form(self, **kwargs):
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        # Obtener las compañías permitidas para el usuario logueado
        allowed_work_groups = request.env['portal.work.group'].search([('equip_boss', '=', user.id)])
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
        print("*"*50)
        print("antes del if")
        print("*"*50)
        print("request")
        if user_id == work_group_id.equip_boss.id:
            status = 'approved_purchase_responsible'
        print("despues del if")
        expensive = request.env['portal.hr.expensive.request'].sudo().create({
            'type': expensive_type,
            'user_id': user_id,
            'status': status,
            'project': project,

        })
        attachments = request.httprequest.files.getlist('file')
        print("-"*50)
        print("attachments", attachments)
        print("-"*50)
        for attachment in attachments:
            attachment_data = {
                'name': attachment.filename,
                'res_model': 'portal.hr.expensive.request',
                'res_id': expensive.id,
                'datas': base64.b64encode(attachment.read()),
                'type': 'binary',
            }
            request.env['ir.attachment'].create(attachment_data)
        #self.send_request_email(approval_type, new_document_approval)

        return request.redirect('/contactus-thank-you')

