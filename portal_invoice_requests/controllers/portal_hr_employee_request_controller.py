from odoo.http import request, Controller, route

class PortalHrEmployeeRequestController(Controller):
    @route('/portal/hr_employee_request', auth='user', website=True)
    def hr_employee_request_form(self, **kwargs):
        employee_types = request.env['hr.contract.type'].search([])
        jobs = request.env['hr.job'].search([])
        calendars = request.env['resource.calendar'].search([])
        banks = request.env['res.partner.bank'].search([])
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        return request.render('portal_invoice_requests.portal_hr_employee_request_template', {
            'employee_types': employee_types,
            'jobs': jobs,
            'calendars': calendars,
            'banks': banks,
            'companies': allowed_companies,
        })

    @route('/portal/hr_employee_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def hr_employee_request_submit(self, **post):
        name = post.get('name')
        identification_id = post.get('identification_id')
        mobile_phone = post.get('mobile_phone')
        ssnid = post.get('ssnid')
        confidential_compromise = post.get('confidential_compromise')
        working_life_report = post.get('working_life_report')
        cv = post.get('cv')
        work_email = post.get('work_email')
        prl_annex = post.get('prl_annex')
        employee_type = int(post.get('employee_type'))
        study_field = post.get('study_field')
        job_id = int(post.get('job_id'))
        salary = float(post.get('salary'))
        number_of_pays = int(post.get('number_of_pays'))
        resource_calendar_id = int(post.get('resource_calendar_id'))
        bank_account_id = int(post.get('bank_account_id'))
        team_work_id = int(post.get('team_work_id'))
        project_id = int(post.get('project_id'))

        employee = request.env['portal.hr.employee.request'].sudo().create({
            'name': name,
            'identification_id': identification_id,
            'mobile_phone': mobile_phone,
            'ssnid': ssnid,
            'confidential_compromise': confidential_compromise,
            'working_life_report': working_life_report,
            'cv': cv,
            'work_email': work_email,
            'prl_annex': prl_annex,
            'employee_type': employee_type,
            'study_field': study_field,
            'job_id': job_id,
            'salary': salary,
            'number_of_pays': number_of_pays,
            'resource_calendar_id': resource_calendar_id,
            'bank_account_id': bank_account_id,
            'team_work_id': team_work_id,
            'project_id': project_id,
        })
