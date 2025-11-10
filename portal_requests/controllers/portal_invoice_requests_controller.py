from odoo.http import request, Controller, route

class PortalInvoiceController(Controller):
    @route('/portal/invoice_request', auth='user', website=True)
    def invoice_request_form(self, **kwargs):
        # Obtener el usuario actual
        user = request.env.user
        # Obtener las compañías permitidas para el usuario logueado
        allowed_companies = user.company_ids
        allowed_work_groups = request.env['portal.work.group'].search([('user_ids', 'in', user.id)])
        allowed_companies = request.env['account.analytic.account'].search([('work_group_id', 'in', allowed_work_groups.ids)])
        options = request.env['account.move']._fields['l10n_es_edi_facturae_reason_code']._description_selection(
            request.env)
        return request.render('portal_requests.portal_invoice_request_template', {
            'companies': allowed_companies,
            'options': options,
        })

    @route('/portal/invoice_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def invoice_request_submit(self, **post):
        user_id = request.env.user.id
        analytic_id = int(post.get('company_id'))
        partner_id = int(post.get('partner_id'))
        amount = float(post.get('amount'))
        notes = post.get('notes')
        move_type = post.get('move_type')
        date = post.get('date')
        invoice_to_refund = post.get('invoice_id')
        print("/"*100)
        print("invoice_to_refund",invoice_to_refund)
        print("/"*100)
        l10n_es_edi_facturae_reason_code = post.get('l10n_es_edi_facturae_reason_code')
        # Obtener la descripción asociada al código seleccionado
        reason_description = dict(
            request.env['account.move']._fields['l10n_es_edi_facturae_reason_code'].selection).get(
            l10n_es_edi_facturae_reason_code)
        if move_type == 'out_invoice':
            l10n_es_edi_facturae_reason_code = ""
            invoice_to_refund = False
        invoice_request = request.env['portal.invoice.request'].sudo().create({
            'user_id': user_id,
            'analytic_id': analytic_id,
            'partner_id': partner_id,
            'amount': amount,
            'notes': notes,
            'move_type': move_type,
            'date': date,
            'l10n_es_edi_facturae_reason_code': l10n_es_edi_facturae_reason_code,
            'invoice_to_refund': invoice_to_refund,
        })
        if move_type == 'out_invoice':
            move_text = "factura"
        else:
            invoice_name = request.env['account.move'].sudo().search([('id', '=', invoice_to_refund)]).name
            move_text = "factura rectificativa para la factura " + invoice_name
        self.send_request_email(move_text,invoice_request.user_id.name,invoice_request.analytic_id.name,invoice_request.partner_id.name, invoice_request.notes, invoice_request.invoice_to_refund, invoice_request)
        return request.redirect('/contactus-thank-you')

    def send_request_email(self, move_text, user_name,company_name, partner_name, notes, invoice_to_refund, invoice_request):
        admin_users = request.env['res.users'].search(
            [('groups_id', 'in', request.env.ref('portal_requests.group_partner_responsible').id)])
        invoice_request_link = f"/web#id={invoice_request.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=portal.invoice.request&view_type=form"
        for admin_user in admin_users:
            admin_name = admin_user.name
            body_html = f"""
                        <p>Estimado/a {admin_name},</p>
                        <p>El usuario {user_name} ha creado una solicitud de {move_text} en el proyecto {company_name}.</p>
                        <p>A continuación, se detallan los datos de la solicitud:
                        <ul>
                            <li><strong>Usuario:</strong> {user_name}</li>
                            <li><strong>Proyecto:</strong> {company_name}</li>
                            <li><strong>Proveedor:</strong> {partner_name}</li>
                            <li><strong>Concepto:</strong> {notes}</li>
                            <li><strong>Enlace:</strong> <a href="{invoice_request_link}">Solicitud</a></li>
                        <ul>
                        </p>
                        <p>Saludos cordiales, Odoo</p>
                    """
            email = admin_user.email
            mail_values = {
                'subject': f'Solicitud de {move_text}',
                'email_from': request.env.user.email or 'no-reply@example.com',
                'email_to': email,
                'body_html': body_html,
            }
            mail = request.env['mail.mail'].create(mail_values)

            mail.send()

        return request.render("portal.email_sent_confirmation")
