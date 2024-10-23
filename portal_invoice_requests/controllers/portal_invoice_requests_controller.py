from odoo.http import request, Controller, route
from odoo import fields

class PortalInvoiceController(Controller):
    @route('/portal/invoice_request', auth='user', website=True)
    def invoice_request_form(self, **kwargs):
        companies = request.env['res.company'].search([])
        options = request.env['account.move']._fields['l10n_es_edi_facturae_reason_code']._description_selection(request.env)
        return request.render('portal_invoice_requests.portal_invoice_request_template', {
            'companies': companies,
            'options': options,
        })

    @route('/portal/invoice_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def invoice_request_submit(self, **post):
        company_id = int(post.get('company_id'))
        partner_id = int(post.get('partner_id'))
        amount = float(post.get('amount'))
        notes = post.get('notes')
        move_type = post.get('move_type')
        date = post.get('date')
        l10n_es_edi_facturae_reason_code = post.get('l10n_es_edi_facturae_reason_code')

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




