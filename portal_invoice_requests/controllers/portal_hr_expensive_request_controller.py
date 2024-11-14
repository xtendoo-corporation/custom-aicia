from odoo.http import request, Controller, route

class PortalHrExpensiveRequestController(Controller):
    @route('/portal/hr_expensive_request', auth='user', website=True)
    def hr_expensive_request_form(self, **kwargs):
        products = request.env['product.product'].search([])
        employees = request.env['hr.employee'].search([])
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        return request.render('portal_invoice_requests.portal_hr_expensive_request_template', {
            'products': products,
            'employees': employees,
            'companies': allowed_companies,
        })

    @route('/portal/hr_expensive_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def hr_expensive_request_submit(self, **post):
        name = post.get('name')
        product_id = int(post.get('product_id'))
        total_amount_currency = float(post.get('total_amount_currency'))
        employee_id = int(post.get('employee_id'))
        date = post.get('date')
        company_id = int(post.get('company_id'))

        expensive = request.env['portal.hr.expensive.request'].sudo().create({
            'name': name,
            'product_id': product_id,
            'total_amount_currency': total_amount_currency,
            'employee_id': employee_id,
            'date': date,
            'company_id': company_id,
        })

        return request.redirect('/portal/hr_expensive_request')
