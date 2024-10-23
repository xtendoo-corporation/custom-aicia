from odoo.http import request, Controller, route
from odoo import http
import json

class PortalUtils(Controller):

    @http.route('/get_partners_by_company', type='http', auth="user")
    def get_partners_by_company(self, company_id):
        try:
            # Buscar partners relacionados con la compañía seleccionada
            partners = request.env['res.partner'].search([('company_id', '=', int(company_id))])

            # Crear la respuesta JSON con los datos de los partners
            partners_data = [{'id': partner.id, 'name': partner.name} for partner in partners]

            # Retornar los datos en formato JSON
            return request.make_response(
                json.dumps({'partners': partners_data}),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'error': str(e)}),
                headers={'Content-Type': 'application/json'},
                status=400
            )

    @http.route('/get_reason_codes', type='http', auth="user")
    def get_reason_codes(self):
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
