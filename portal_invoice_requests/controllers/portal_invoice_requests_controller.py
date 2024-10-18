from odoo.http import request, Controller, route
from odoo import fields

class PortalInvoiceController(Controller):
    @route('/portal/invoice_request', auth='user', website=True)
    def invoice_request_form(self, **kwargs):
        companies = request.env['res.company'].search([])
        partners = request.env['res.partner'].search([])
        return request.render('portal_invoice_requests.portal_invoice_request_template', {
            'companies': companies,
            'partners': partners,
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

        return request.redirect('/thank-you-page')
