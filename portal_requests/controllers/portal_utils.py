from odoo.http import request, Controller, route
from odoo import http
import json

class PortalUtils(http.Controller):

    @route('/get_clients_by_company', type='http', auth='public', methods=['GET'], csrf=False)
    def get_clients_by_company(self, **kwargs):
        company_id = kwargs.get('company_id')
        clients = request.env['res.partner'].search([('company_id', '=', int(company_id))])
        clients_json = {'clients': [{'id': client.id, 'name': client.name} for client in clients]}
        return request.make_response(json.dumps({'partners': clients_json}), headers={'Content-Type': 'application/json'})

    @route('/get_invoice_by_clients', type='http', auth='public', methods=['GET'], csrf=False)
    def get_invoice_by_clients(self, **kwargs):
        company_id = kwargs.get('company_id')
        client_id = kwargs.get('client_id')
        invoices = request.env['account.move'].search([
            ('company_id', '=', int(company_id)),
            ('partner_id', '=', int(client_id)),
            ('state', '=', 'posted'),
        ])
        print("*"*100)
        print("invoices", invoices)
        print("*"*100)
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
