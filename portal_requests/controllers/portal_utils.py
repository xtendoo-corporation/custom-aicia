from odoo.http import request, Controller, route
from odoo import http
import json

class PortalUtils(http.Controller):

    @route('/get_employee_by_company', type='http', auth='public', methods=['GET'], csrf=False)
    def get_employee_by_company(self, **kwargs):
        company_id = int(kwargs.get('company_id'))
        employee_type = str(kwargs.get('employee_type'))
        active = bool(int(kwargs.get('active')))
        employees = request.env['hr.employee'].search([
            ('active', '=', active),
            ('employee_type', '=', employee_type),
            ('company_id', '=', company_id),
        ])
        employees_json = {'employees': [{'id': employee.id, 'name': employee.name} for employee in employees]}
        print("*"*100)
        print("company_id", company_id)
        print("employee_type", employee_type)
        print("active", active)
        print("employees", employees)
        print("employees_json", employees_json)
        print("*"*100)
        return request.make_response(json.dumps({'partners': employees_json}),
                                     headers={'Content-Type': 'application/json'})

    @route('/get_clients_by_company', type='http', auth='public', methods=['GET'], csrf=False)
    def get_clients_by_company(self, **kwargs):
        company_id = kwargs.get('company_id')
        clients = request.env['res.partner'].search([('company_id', '=', int(company_id))])
        clients_json = {'clients': [{'id': client.id, 'name': client.name} for client in clients]}
        return request.make_response(json.dumps({'partners': clients_json}), headers={'Content-Type': 'application/json'})

    @route('/get_clients_by_analytic', type='http', auth='public', methods=['GET'], csrf=False)
    def get_clients_by_analytic(self, **kwargs):
        company_id = kwargs.get('company_id')

        # Buscar cuentas analíticas de la empresa
        analytic_accounts = request.env['account.analytic.account'].sudo().search([
            ('id', '=', int(company_id))
        ])

        # Recopilar clientes del campo partner_id y clientes_asociados
        all_clients = request.env['res.partner'].sudo()

        for account in analytic_accounts:
            # Añadir el cliente principal (partner_id)
            if account.partner_id:
                all_clients |= account.partner_id

            # Añadir los clientes asociados (Many2many)
            if account.clientes_asociados:
                all_clients |= account.clientes_asociados

        # Crear respuesta JSON con clientes únicos - usar sudo() para evitar problemas de permisos
        clients_json = {'clients': [{'id': client.id, 'name': client.name} for client in all_clients]}

        return request.make_response(json.dumps({'partners': clients_json}),
                                     headers={'Content-Type': 'application/json'})

    @route('/get_invoice_by_clients', type='http', auth='public', methods=['GET'], csrf=False)
    def get_invoice_by_clients(self, **kwargs):
        company_id = kwargs.get('company_id')
        client_id = kwargs.get('client_id')
        invoices = request.env['account.move'].search([
            ('company_id', '=', int(company_id)),
            ('partner_id', '=', int(client_id)),
            ('state', '=', 'posted'),
        ])
        invoices_json = {'invoices': [{'id': invoice.id, 'name': invoice.name} for invoice in invoices]}
        return request.make_response(json.dumps({'invoices': invoices_json}),
                                     headers={'Content-Type': 'application/json'})

    @http.route('/get_reason_codes', type='http', auth="user")
    def get_reason_codes(self):
        print("*" * 100)
        print("Metodo get_reason_codes")
        try:
            # Obtener los códigos de razón de la factura electrónica
            reason_codes = request.env['account.move']._fields['l10n_es_edi_facturae_reason_code']._description_selection(request.env)

            # Crear la respuesta JSON con los códigos de razón
            reason_codes_data = [{'code': code, 'description': description} for code, description in reason_codes]

            # Retornar los datos en formato JSON
            return request.make_response(
                json.dumps({'reason_codes': reason_codes_data}),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            print("*"*100)
            print(e)
            print("*"*100)
            return request.make_response(
                json.dumps({'error': str(e)}),
                headers={'Content-Type': 'application/json'},
                status=400
            )

    @route('/get_user_work_groups', type='http', auth='user', methods=['GET'], csrf=False)
    def get_user_work_groups(self, **kwargs):
        user = request.env.user
        work_groups = request.env['portal.work.group'].search([
            ('user_ids', 'in', user.id)
        ])
        work_groups_json = {'work_groups': [{'id': group.id, 'name': group.name, 'code': group.code} for group in work_groups]}
        print("*"*100)
        print("user", user.name)
        print("work_groups", work_groups)
        print("work_groups_json", work_groups_json)
        print("*"*100)
        return request.make_response(json.dumps({'result': work_groups_json}),
                                   headers={'Content-Type': 'application/json'})

    @route('/get_projects_by_work_group', type='http', auth='user', methods=['GET'], csrf=False)
    def get_projects_by_work_group(self, **kwargs):
        user = request.env.user
        # Obtener los grupos de trabajo del usuario
        work_groups = request.env['portal.work.group'].search([
            ('user_ids', 'in', user.id)
        ])
        # Buscar proyectos que pertenezcan a esos grupos de trabajo
        projects = request.env['project.project'].search([
            ('work_group_id', 'in', work_groups.ids),
            ('active', '=', True)
        ])
        projects_json = {
            'projects': [{
                'id': project.id,
                'name': project.name,
                'partner_id': project.partner_id.id,
                'partner_name': project.partner_id.name,
                'work_group_id': project.work_group_id.id,
                'work_group_name': project.work_group_id.name,
                'company_id': project.company_id.id,
                'company_name': project.company_id.name,
            } for project in projects]
        }
        print("*"*100)
        print("user", user.name)
        print("work_groups", work_groups.mapped('name'))
        print("projects", projects.mapped('name'))
        print("projects_json", projects_json)
        print("*"*100)
        return request.make_response(json.dumps({'result': projects_json}),
                                   headers={'Content-Type': 'application/json'})
