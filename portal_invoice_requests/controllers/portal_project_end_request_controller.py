from odoo.http import request, Controller, route

class PortalProjectEndRequestController(Controller):
    @route('/portal/project_end_request', auth='user', website=True)
    def project_end_request_form(self, **kwargs):
        projects = request.env['project.project'].search([])
        return request.render('portal_invoice_requests.portal_project_end_request_template', {
            'projects': projects,
        })

    @route('/portal/project_end_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def project_end_request_submit(self, **post):
        project_id = int(post.get('project_id'))
        project_end_date = post.get('project_end_date')

        project_end = request.env['portal.project.end.request'].sudo().create({
            'project_id': project_id,
            'project_end_date': project_end_date,
        })
