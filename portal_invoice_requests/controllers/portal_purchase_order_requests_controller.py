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
            'order_line': [
                (0, 0, {
                    'name': concept,
                    'display_type': 'line_note',
                    'product_id': False,
                    'product_qty': 0.0,
                    'product_uom': False,
                    'price_unit': 0.0,
                    'taxes_id': False,
                }),
            ],
        })

        purchase_order_url = f"/web#menu_id=286&action=467&model=purchase.order&view_type=form&id={purchase_order.id}"

        self.send_purchase_order_email(purchase_order, purchase_order_url, concept)

        return request.redirect('/contactus-thank-you')

    # Enviar correo electrónico con los detalles de la orden de compra
    def send_purchase_order_email(self, purchase_order, purchase_order_url, concept):
        # Obtener el creador de la factura
        user_id = purchase_order.user_id
        company_name = purchase_order.company_id.name

        # Obtener los usuarios del grupo de administradores de ajustes (base.group_system)
        admin_users = request.env['res.users'].search([('groups_id', 'in', request.env.ref('base.group_system').id)])

        # Filtrar usuarios que tienen un correo electrónico válido
        email_list = admin_users.mapped('email')
        email_list = [email for email in email_list if email]  # Solo correos no vacíos

        body_html = f"""
            <p>Estimado/a Administrador/a,</p>
            <p>El usuario {user_id.name} ha creado una solicitud de orden de compra para el proyecto {company_name}.</p>
            <p>A continuación, se detallan los datos de la solicitud:
            <ul>
                <li><strong>Usuario:</strong> {user_id.name}</li>
                <li><strong>Proyecto:</strong> {company_name}</li>
                <li><strong>Proveedor:</strong> {purchase_order.partner_id.name}</li>
                <li><strong>REF:</strong> {purchase_order.name}</li>
                <li><strong>Concepto:</strong> {concept}</li>
            <ul>
            </p>
            <p>Para ver la orden de compra, haga clic en el siguiente enlace: <a href="{purchase_order_url}">{purchase_order.name}</a></p>
            <p>Saludos cordiales, Odoo</p>
        """

        # Crear los valores para el correo
        mail_values = {
            'subject': f'Invoice request: {purchase_order.name}',
            'email_from': request.env.user.email,
            'email_to': ','.join(email_list),
            'body_html': body_html,
        }

        # Crear el correo en el sistema
        mail = request.env['mail.mail'].create(mail_values)

        # Enviar el correo
        mail.send()

        return request.render("portal.email_sent_confirmation")
