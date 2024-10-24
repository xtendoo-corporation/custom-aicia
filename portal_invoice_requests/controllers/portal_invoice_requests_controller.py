from odoo.http import request, Controller, route

class PortalInvoiceController(Controller):
    @route('/portal/invoice_request', auth='user', website=True)
    def invoice_request_form(self, **kwargs):
        companies = request.env['res.company'].search([])
        options = request.env['account.move']._fields['l10n_es_edi_facturae_reason_code']._description_selection(
            request.env)
        return request.render('portal_invoice_requests.portal_invoice_request_template', {
            'companies': companies,
            'options': options,
        })

    @route('/portal/invoice_request/submit', type='http', auth='user', website=True, methods=['POST'])
    def invoice_request_submit(self, **post):
        user_id = request.env.user.id
        company_id = int(post.get('company_id'))
        partner_id = int(post.get('partner_id'))
        amount = float(post.get('amount'))
        notes = post.get('notes')
        move_type = post.get('move_type')
        date = post.get('date')
        l10n_es_edi_facturae_reason_code = post.get('l10n_es_edi_facturae_reason_code')
        # Obtener la descripción asociada al código seleccionado
        reason_description = dict(
            request.env['account.move']._fields['l10n_es_edi_facturae_reason_code'].selection).get(
            l10n_es_edi_facturae_reason_code)

        if move_type == 'out_invoice':
            invoice = request.env['account.move'].sudo().create({
                'move_type': 'out_invoice',
                'partner_id': partner_id,
                'company_id': company_id,
                'invoice_date': date,
                'invoice_line_ids': [(0, 0, {
                    'name': notes,
                    'quantity': 1.0,
                    'price_unit': amount,
                })]
            })
        elif move_type == 'out_refund':
            invoice = request.env['account.move'].sudo().create({
                'move_type': 'out_refund',
                'partner_id': partner_id,
                'company_id': company_id,
                'invoice_date': date,
                'ref': reason_description,
                'invoice_line_ids': [
                    (0, 0, {
                        'name': notes,
                        'quantity': 1.0,
                        'price_unit': amount,
                    })
                ],
            })

        invoice_url = f"/web#id={invoice.id}&model=account.move&view_type=form&menu_id=132&action=256"

        self.send_invoice_email(invoice, invoice_url)


        return request.redirect('/contactus-thank-you')

    # Enviar correo electrónico con los detalles de la factura
    def send_invoice_email(self, invoice, invoice_url):
        # Obtener el creador de la factura
        user_id = invoice.user_id
        company_name = invoice.company_id.name

        # Crear el cuerpo del mensaje de correo
        if invoice.move_type == 'out_invoice':
            body_html = f"""
                           <p>Hello,</p>
                           <p>The user {user_id.name} has requested an invoice for the project {company_name}.</p>
                           <ul>
                               <li><strong>User:</strong> {user_id.name}</li>
                               <li><strong>Project:</strong> {company_name}</li>
                               <li><strong>Link:</strong> <a href="{invoice_url}">Invoice</a></li>
                           <ul>
                           <p>Best regards,<br/>Odoo</p>
               """
        elif invoice.move_type == 'out_refund':
            body_html = f"""
                           <p>Hello,</p>
                           <p>The user {user_id.name} has requested an invoice for the project {company_name}.</p>
                           <ul>
                               <li><strong>User:</strong> {user_id.name}</li>
                               <li><strong>Project:</strong> {company_name}</li>
                               <li><strong>Link:</strong> <a href="{invoice_url}">Invoice</a></li>
                               <li><strong>Reason:</strong> {invoice.ref}</li>
                           <ul>
                           <p>Best regards,<br/>Odoo</p>
               """

        # Obtener los usuarios del grupo de administradores de ajustes (base.group_system)
        admin_users = request.env['res.users'].search([('groups_id', 'in', request.env.ref('base.group_system').id)])

        # Filtrar usuarios que tienen un correo electrónico válido
        email_list = admin_users.mapped('email')
        email_list = [email for email in email_list if email]  # Solo correos no vacíos

        # Crear los valores para el correo
        mail_values = {
            'subject': f'Invoice request: {invoice.name}',
            'email_from': request.env.user.email,
            'email_to': ','.join(email_list),
            'body_html': body_html,
        }

        # Crear el correo en el sistema
        mail = request.env['mail.mail'].create(mail_values)

        # Enviar el correo
        mail.send()

        return request.render("portal.email_sent_confirmation")

