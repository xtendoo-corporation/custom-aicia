from odoo.http import request, Controller, route
from odoo import fields
from odoo import http
from datetime import datetime
import json


class PortalPurchaseOrderController(Controller):

    @route('/portal/purchase_order_request', auth='user', website=True)
    def purchase_order_request_form(self, **kwargs):
        companies = request.env['res.company'].search([])
        return request.render('portal_invoice_requests.portal_purchase_order_requests_template', {
            'companies': companies,
        })

    @route('/portal/purchase_order_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def purchase_order_request_submit(self, **post):
        company_id = int(post.get('company_id'))
        partner_id = int(post.get('partner_id'))
        concept = str(post.get('concept'))

        purchase_order = request.env['purchase.order'].sudo().create({
            'company_id': company_id,
            'partner_id': partner_id,
            'date_order': fields.Date.today(),
            'order_line': [(0, 0, {
                'name': 'Concept: ' + concept,
                'product_qty': 1.0,
                'price_unit': 0.0,
            })],
        })

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
