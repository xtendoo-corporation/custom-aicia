from odoo.http import request, Controller, route
from odoo import fields
from odoo import http
import json


class PortalInvoiceController(Controller):
    @route('/portal/invoice_request', auth='user', website=True)
    def invoice_request_form(self, **kwargs):
        companies = request.env['res.company'].search([])
        return request.render('portal_invoice_requests.portal_invoice_request_template', {
            'companies': companies,
        })

    @route('/portal/invoice_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def invoice_request_submit(self, **post):
        company_id = int(post.get('company_id'))
        partner_id = int(post.get('partner_id'))
        amount = float(post.get('amount'))
        notes = post.get('notes')

        invoice = request.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': partner_id,
            'company_id': company_id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {
                'name': notes,
                'quantity': 1.0,
                'price_unit': amount,
            })],
        })

        return request.redirect('/contactus-thank-you')

    @http.route('/get_partners_by_company', type='http', auth="user")
    def get_partners_by_company(self, company_id):
        try:
            partners = request.env['res.partner'].search([('company_ids', 'in', int(company_id))])

            partners_data = [{'id': partner.id, 'name': partner.name} for partner in partners]

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
