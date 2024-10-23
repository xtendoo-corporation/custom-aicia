from odoo.http import request, Controller, route
from odoo import fields

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

        return request.redirect('/contactus-thank-you')
