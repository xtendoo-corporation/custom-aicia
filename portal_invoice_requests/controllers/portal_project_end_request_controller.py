from odoo.http import request, Controller, route

class PortalProjectEndRequestController(Controller):
    @route('/portal/project_end_request', auth='user', website=True)
    def project_end_request_form(self, **kwargs):
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        # Pasar las compañías permitidas al contexto para que se usen en el formulario
        return request.render('portal_invoice_requests.portal_project_end_request_template', {
            'companies': allowed_companies,
        })

    @route('/portal/project_end_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def project_end_request_submit(self, **post):
        company_id = int(post.get('company_id'))
        project_end_date = post.get('project_end_date')
        concept = post.get('concept')

        project_end = request.env['portal.project.end.request'].sudo().create({
            'company_id': company_id,
            'project_end_date': project_end_date,
            'concept': concept,
        })
