from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class PortalRequestsCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        """Añade contadores personalizados al portal"""
        values = super()._prepare_home_portal_values(counters)

        # # Contador de solicitudes de gastos - siempre se calcula para que la tarjeta se muestre
        # expense_count = request.env['portal.hr.expensive.request'].search_count([
        #     ('user_id', '=', request.env.user.id)
        # ])
        # values['expense_count'] = expense_count
        #
        # # Contador de solicitudes de facturas - siempre se calcula para que la tarjeta se muestre
        # invoice_request_count = request.env['portal.invoice.request'].search_count([
        #     ('user_id', '=', request.env.user.id)
        # ])
        # values['invoice_request_count'] = invoice_request_count

        return values

    @http.route(['/my/expenses', '/my/expenses/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_expenses(self, page=1, sortby=None, filterby=None, **kw):
        """Muestra el listado de solicitudes de gastos del usuario"""
        user = request.env.user

        # Búsqueda de solicitudes de gastos del usuario
        expenses = request.env['portal.hr.expensive.request'].search([
            ('user_id', '=', user.id)
        ], order='create_date desc')

        values = {
            'expenses': expenses,
            'page_name': 'expense',
            'default_url': '/my/expenses',
        }

        return request.render("portal_requests.portal_my_expenses", values)

    @http.route(['/my/expenses/<int:expense_id>'], type='http', auth="user", website=True)
    def portal_my_expense_detail(self, expense_id, success=None, **kw):
        """Muestra el detalle de una solicitud de gastos"""
        expense = request.env['portal.hr.expensive.request'].browse(expense_id)

        # Verificar que la solicitud pertenece al usuario actual
        if expense.user_id != request.env.user:
            return request.redirect('/my')

        # Generar access_token si no existe (necesario para el chatter)
        expense._portal_ensure_token()

        # Obtener los adjuntos relacionados con esta solicitud
        attachments = request.env['ir.attachment'].search([
            ('res_model', '=', 'portal.hr.expensive.request'),
            ('res_id', '=', expense_id)
        ])

        # Obtener TODOS los mensajes del chatter usando sudo para tener acceso completo
        messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'portal.hr.expensive.request'),
            ('res_id', '=', expense_id)
        ], order='date desc')

        values = {
            'expense': expense,
            'attachments': attachments,
            'messages': messages,
            'page_name': 'expense',
            'success_message': success,
        }

        return request.render("portal_requests.portal_my_expense_detail", values)

    @http.route(['/my/expenses/<int:expense_id>/post_message'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_expense_post_message(self, expense_id, message, **kw):
        """Permite al usuario portal enviar un mensaje en la solicitud de gastos"""
        expense = request.env['portal.hr.expensive.request'].browse(expense_id)

        # Verificar que la solicitud pertenece al usuario actual
        if expense.user_id != request.env.user:
            return request.redirect('/my')

        # Publicar el mensaje
        if message and message.strip():
            expense.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=request.env.user.partner_id.id
            )

        # Redirigir de vuelta al detalle
        return request.redirect(f'/my/expenses/{expense_id}?success=message_posted')

    @http.route(['/my/expenses/<int:expense_id>/request_revision'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_expense_request_revision(self, expense_id, **kw):
        """Solicita una nueva revisión de la solicitud de gastos"""
        expense = request.env['portal.hr.expensive.request'].browse(expense_id)

        # Verificar que la solicitud pertenece al usuario actual
        if expense.user_id != request.env.user:
            return request.redirect('/my')

        # Verificar que el estado es 'to_revise'
        if expense.status == 'to_revise':
            # Ejecutar la acción de aprobar que maneja el cambio de estado
            expense.action_approve()

        # Redirigir de vuelta al detalle de la solicitud con mensaje de éxito
        return request.redirect(f'/my/expenses/{expense_id}?success=revision_requested')

    @http.route(['/my/expenses/thank-you'], type='http', auth="public", website=True)
    def portal_expense_thank_you(self, **kw):
        """Página de confirmación después de enviar una solicitud de gastos"""
        return request.render("portal_requests.hr_expensive_request_thank_you")

    # ==========================================
    # Rutas para Solicitudes de Facturas
    # ==========================================

    @http.route(['/my/invoices', '/my/invoices/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_invoices(self, page=1, sortby=None, filterby=None, **kw):
        """Muestra el listado de solicitudes de facturas del usuario"""
        user = request.env.user

        # Búsqueda de solicitudes de facturas del usuario
        invoice_requests = request.env['portal.invoice.request'].search([
            ('user_id', '=', user.id)
        ], order='create_date desc')

        values = {
            'invoice_requests': invoice_requests,
            'page_name': 'invoice_request',
            'default_url': '/my/invoices',
        }

        return request.render("portal_requests.portal_my_invoices", values)

    @http.route(['/my/invoices/<int:invoice_request_id>'], type='http', auth="user", website=True)
    def portal_my_invoice_detail(self, invoice_request_id, success=None, **kw):
        """Muestra el detalle de una solicitud de factura"""
        invoice_request = request.env['portal.invoice.request'].browse(invoice_request_id)

        # Verificar que la solicitud pertenece al usuario actual
        if invoice_request.user_id != request.env.user:
            return request.redirect('/my')

        # Generar access_token si no existe
        invoice_request._portal_ensure_token()

        # Obtener los adjuntos relacionados con esta solicitud
        attachments = request.env['ir.attachment'].search([
            ('res_model', '=', 'portal.invoice.request'),
            ('res_id', '=', invoice_request_id)
        ])

        # Obtener TODOS los mensajes del chatter usando sudo
        messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'portal.invoice.request'),
            ('res_id', '=', invoice_request_id)
        ], order='date desc')

        values = {
            'invoice_request': invoice_request,
            'attachments': attachments,
            'messages': messages,
            'page_name': 'invoice_request',
            'success_message': success,
        }

        return request.render("portal_requests.portal_my_invoice_detail", values)

    @http.route(['/my/invoices/<int:invoice_request_id>/request_revision'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_invoice_request_revision(self, invoice_request_id, **kw):
        """Solicita una nueva revisión de la solicitud de factura"""
        invoice_request = request.env['portal.invoice.request'].browse(invoice_request_id)

        # Verificar que la solicitud pertenece al usuario actual
        if invoice_request.user_id != request.env.user:
            return request.redirect('/my')

        # Verificar que el estado es 'to_revise'
        if invoice_request.status == 'to_revise':
            # Ejecutar la acción de aprobar que maneja el cambio de estado
            invoice_request.action_approve()

        # Redirigir de vuelta al detalle de la solicitud con mensaje de éxito
        return request.redirect(f'/my/invoices/{invoice_request_id}?success=revision_requested')

    @http.route(['/my/invoices/<int:invoice_request_id>/post_message'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_invoice_post_message(self, invoice_request_id, message, **kw):
        """Permite al usuario portal enviar un mensaje en la solicitud de factura"""
        invoice_request = request.env['portal.invoice.request'].browse(invoice_request_id)

        # Verificar que la solicitud pertenece al usuario actual
        if invoice_request.user_id != request.env.user:
            return request.redirect('/my')

        # Publicar el mensaje
        if message and message.strip():
            invoice_request.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=request.env.user.partner_id.id
            )

        # Redirigir de vuelta al detalle
        return request.redirect(f'/my/invoices/{invoice_request_id}?success=message_posted')
