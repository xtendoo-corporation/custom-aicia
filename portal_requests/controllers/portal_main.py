from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request, route
import base64


class PortalRequestsCustomerPortal(CustomerPortal):

    def _enrich_messages(self, raw_messages):
        """Convierte un recordset de mail.message en lista de dicts,
        construyendo el body desde tracking_value_ids cuando está vacío."""
        messages = []
        for msg in raw_messages:
            body = msg.body or ''
            plain_body = body.replace('<p>', '').replace('</p>', '').replace('<br>', '').replace('<br/>', '').strip()
            if not plain_body and msg.tracking_value_ids:
                tracking_lines = []
                for tracking in msg.tracking_value_ids:
                    if tracking.field_id:
                        field_label = tracking.field_id.field_description
                    elif tracking.field_info:
                        field_label = tracking.field_info.get('desc', '')
                    else:
                        field_label = ''
                    old_val = tracking.old_value_char or (str(tracking.old_value_integer) if tracking.old_value_integer else 'Ninguno')
                    new_val = tracking.new_value_char or (str(tracking.new_value_integer) if tracking.new_value_integer else 'Ninguno')
                    if old_val != new_val:
                        tracking_lines.append(f"<strong>{field_label}:</strong> {old_val} → {new_val}")
                    else:
                        tracking_lines.append(f"<strong>{field_label}:</strong> {new_val}")
                body = '<br/>'.join(tracking_lines)
            # Guardar author como dict simple para evitar problemas de acceso en portal
            author = msg.author_id.sudo()
            author_data = {
                'id': author.id,
                'name': author.name or '',
            } if author else None
            messages.append({
                'author_id': author_data,
                'date': msg.date,
                'body': body,
                'message_type': msg.message_type,
            })
        return messages

    def _can_access_invoice_request(self, invoice_request):
        """Devuelve True si el usuario actual puede acceder a la solicitud de factura:
        - Es el creador de la solicitud, O
        - Es el jefe de equipo del grupo de trabajo asociado a la solicitud.
        """
        user = request.env.user
        if invoice_request.user_id == user:
            return True
        if invoice_request.equip_boss == user:
            return True
        return False

    def _get_accessible_analytic_project_domain(self, user):
        """Dominio de proyectos visibles en portal para el usuario actual.
        - Usuario normal: solo proyectos donde es responsable.
        - Jefe de equipo: propios + proyectos de grupos donde es equip_boss.
        """
        domain = [('responsible_id', '=', user.id)]
        if user.has_group('portal_requests.group_equip_boss'):
            boss_group_ids = request.env['portal.work.group'].sudo().search([
                ('equip_boss', '=', user.id)
            ]).ids
            if boss_group_ids:
                domain = ['|', ('responsible_id', '=', user.id), ('work_group_id', 'in', boss_group_ids)]
        return domain

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

        # Contador de solicitudes de documentos - siempre se calcula para que la tarjeta se muestre
        # document_approval_count = request.env['document.approval'].search_count([
        #     ('user_id', '=', request.env.user.id)
        # ])
        # values['document_approval_count'] = document_approval_count

        # Contador de proyectos analíticos visibles para el usuario portal
        if 'analytic_project_count' in counters:
            analytic_project_count = request.env['account.analytic.account'].search_count(
                self._get_accessible_analytic_project_domain(request.env.user)
            )
            values['analytic_project_count'] = analytic_project_count

        # Contador de solicitudes de proyectos - siempre se calcula para que la tarjeta se muestre
        # project_request_count = request.env['portal.project.request'].search_count([
        #     ('user_id', '=', request.env.user.id)
        # ])
        # values['project_request_count'] = project_request_count

        # Indica si el usuario es Jefe de Equipo (controla visibilidad de la tarjeta en el home)
        values['is_equip_boss'] = request.env.user.has_group('portal_requests.group_equip_boss')

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
        raw_messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'portal.hr.expensive.request'),
            ('res_id', '=', expense_id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')
        messages = self._enrich_messages(raw_messages)

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

        # Búsqueda de solicitudes de facturas: propias + las del equipo si es jefe
        invoice_requests = request.env['portal.invoice.request'].sudo().search([
            '|',
            ('user_id', '=', user.id),
            ('equip_boss', '=', user.id),
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
        invoice_request = request.env['portal.invoice.request'].sudo().browse(invoice_request_id)

        # Verificar acceso: creador o jefe de equipo del grupo de la solicitud
        if not self._can_access_invoice_request(invoice_request):
            return request.redirect('/my')

        # Generar access_token si no existe
        invoice_request._portal_ensure_token()

        # Obtener los adjuntos relacionados con esta solicitud
        attachments = request.env['ir.attachment'].search([
            ('res_model', '=', 'portal.invoice.request'),
            ('res_id', '=', invoice_request_id)
        ])

        # Obtener TODOS los mensajes del chatter usando sudo
        raw_messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'portal.invoice.request'),
            ('res_id', '=', invoice_request_id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')
        messages = self._enrich_messages(raw_messages)

        values = {
            'invoice_request': invoice_request,
            'attachments': attachments,
            'messages': messages,
            'page_name': 'invoice_request',
            'success_message': success,
        }

        return request.render("portal_requests.portal_my_invoice_detail", values)

    @http.route(['/my/invoices/<int:invoice_request_id>/approve'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_invoice_approve(self, invoice_request_id, **kw):
        """Permite al jefe de equipo aprobar una solicitud de factura desde el portal"""
        invoice_request = request.env['portal.invoice.request'].sudo().browse(invoice_request_id)

        # Solo el jefe de equipo puede usar esta acción
        if invoice_request.equip_boss != request.env.user:
            return request.redirect('/my')

        # Solo se puede aprobar cuando está pendiente de aprobación del jefe de equipo
        if invoice_request.status == 'approved_by_boss_group':
            invoice_request.action_approve()

        return request.redirect(f'/my/invoices/{invoice_request_id}?success=approved')

    @http.route(['/my/invoices/<int:invoice_request_id>/request_revision'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_invoice_request_revision(self, invoice_request_id, **kw):
        """Solicita una nueva revisión de la solicitud de factura"""
        invoice_request = request.env['portal.invoice.request'].sudo().browse(invoice_request_id)

        # Verificar acceso: creador o jefe de equipo del grupo de la solicitud
        if not self._can_access_invoice_request(invoice_request):
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
        invoice_request = request.env['portal.invoice.request'].sudo().browse(invoice_request_id)

        # Verificar acceso: creador o jefe de equipo del grupo de la solicitud
        if not self._can_access_invoice_request(invoice_request):
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

    @http.route(['/my/invoices/<int:invoice_request_id>/view_invoice'], type='http', auth="user", website=True)
    def portal_invoice_view_created_invoice(self, invoice_request_id, success=None, **kw):
        """Muestra la factura creada desde la solicitud (aunque no esté a nombre del usuario)"""
        invoice_request = request.env['portal.invoice.request'].sudo().browse(invoice_request_id)

        # Verificar acceso: creador o jefe de equipo del grupo de la solicitud
        if not self._can_access_invoice_request(invoice_request):
            return request.redirect('/my')

        # Verificar que existe una factura creada
        if not invoice_request.invoice_created:
            return request.redirect(f'/my/invoices/{invoice_request_id}')

        # Obtener la factura con sudo() ya que no está a nombre del usuario portal
        invoice = invoice_request.invoice_created.sudo()

        # Obtener TODOS los mensajes del chatter de la factura usando sudo
        messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'account.move'),
            ('res_id', '=', invoice.id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')

        # Renderizar una vista personalizada de la factura
        values = {
            'invoice': invoice,
            'invoice_request': invoice_request,
            'messages': messages,
            'page_name': 'invoice_view',
            'success_message': success,
        }

        return request.render("portal_requests.portal_invoice_view", values)

    @http.route(['/my/invoices/<int:invoice_request_id>/view_invoice/post_message'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_invoice_view_post_message(self, invoice_request_id, message, **kw):
        """Permite al usuario portal enviar un mensaje en la factura creada"""
        invoice_request = request.env['portal.invoice.request'].sudo().browse(invoice_request_id)

        # Verificar acceso: creador o jefe de equipo del grupo de la solicitud
        if not self._can_access_invoice_request(invoice_request):
            return request.redirect('/my')

        # Verificar que existe una factura creada
        if not invoice_request.invoice_created:
            return request.redirect(f'/my/invoices/{invoice_request_id}')

        # Publicar el mensaje en la factura usando sudo()
        if message and message.strip():
            invoice_request.invoice_created.sudo().message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=request.env.user.partner_id.id
            )

        # Redirigir de vuelta a la vista de la factura con mensaje de éxito
        return request.redirect(f'/my/invoices/{invoice_request_id}/view_invoice?success=message_posted')

    @http.route(['/my/invoices/thank-you'], type='http', auth="public", website=True)
    def portal_invoice_thank_you(self, **kw):
        """Página de confirmación después de enviar una solicitud de factura"""
        return request.render("portal_requests.invoice_request_thank_you")

    @http.route(['/my/documents/thank-you'], type='http', auth="public", website=True)
    def portal_document_thank_you(self, **kw):
        """Página de confirmación después de enviar una solicitud de documento"""
        return request.render("portal_requests.document_request_thank_you")

    @http.route(['/my/project_requests/thank-you'], type='http', auth="public", website=True)
    def portal_project_request_thank_you(self, **kw):
        """Página de confirmación después de enviar una solicitud de proyecto"""
        return request.render("portal_requests.project_request_thank_you")

    # ==========================================
    # Rutas para Solicitudes de Documentos
    # ==========================================

    @http.route(['/my/documents', '/my/documents/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_documents(self, page=1, sortby=None, filterby=None, **kw):
        """Muestra el listado de solicitudes de documentos del usuario.
        Si es jefe de equipo, también ve las solicitudes de los grupos que lidera."""
        user = request.env.user

        if user.has_group('portal_requests.group_equip_boss'):
            # Grupos de los que este usuario es jefe
            boss_groups = request.env['portal.work.group'].sudo().search([
                ('equip_boss', '=', user.id)
            ])
            # IDs de usuarios miembros de esos grupos
            member_ids = boss_groups.mapped('user_ids').ids
            # Solicitudes propias + las de los miembros de sus grupos
            documents = request.env['document.approval'].sudo().search([
                ('user_id', 'in', member_ids + [user.id])
            ], order='create_date desc')
        else:
            documents = request.env['document.approval'].search([
                ('user_id', '=', user.id)
            ], order='create_date desc')

        values = {
            'documents': documents,
            'page_name': 'document_approval',
            'default_url': '/my/documents',
        }

        return request.render("portal_requests.portal_my_documents", values)

    @http.route(['/my/documents/<int:document_id>'], type='http', auth="user", website=True)
    def portal_my_document_detail(self, document_id, success=None, **kw):
        """Muestra el detalle de una solicitud de documento"""
        user = request.env.user
        document = request.env['document.approval'].sudo().browse(document_id)

        # Verificar acceso: el creador O el jefe de equipo del grupo de trabajo
        is_owner = document.user_id == user
        is_boss_of_group = False
        if user.has_group('portal_requests.group_equip_boss') and document.work_group_id:
            is_boss_of_group = document.work_group_id.equip_boss == user

        if not is_owner and not is_boss_of_group:
            return request.redirect('/my')

        # Generar access_token si no existe
        document._portal_ensure_token()

        # Obtener los adjuntos relacionados con esta solicitud
        attachments = request.env['ir.attachment'].search([
            ('res_model', '=', 'document.approval'),
            ('res_id', '=', document_id)
        ])

        # Obtener TODOS los mensajes del chatter usando sudo
        raw_messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'document.approval'),
            ('res_id', '=', document_id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')
        messages = self._enrich_messages(raw_messages)

        values = {
            'document': document,
            'attachments': attachments,
            'messages': messages,
            'page_name': 'document_approval',
            'success_message': success,
            'is_equip_boss': is_boss_of_group,
        }

        return request.render("portal_requests.portal_my_document_detail", values)

    @http.route(['/my/documents/<int:document_id>/request_revision'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_document_request_revision(self, document_id, **kw):
        """Solicita revision final: solo el jefe de equipo del grupo de trabajo puede ejecutarlo"""
        user = request.env.user
        document = request.env['document.approval'].sudo().browse(document_id)

        # Solo el jefe de equipo del grupo de trabajo del documento puede ejecutar esto
        is_boss_of_group = False
        if user.has_group('portal_requests.group_equip_boss') and document.work_group_id:
            is_boss_of_group = document.work_group_id.equip_boss == user

        if not is_boss_of_group:
            return request.redirect('/my')

        # Verificar que el estado permite solicitar revision
        if document.status == 'sign_company':
            document.with_user(user).action_solicite_final_revision()

        # Redirigir de vuelta al detalle de la solicitud con mensaje de exito
        return request.redirect(f'/my/documents/{document_id}?success=revision_requested')

    @http.route(['/my/documents/<int:document_id>/post_message'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_document_post_message(self, document_id, message, **kw):
        """Permite al usuario portal enviar un mensaje en la solicitud de documento"""
        user = request.env.user
        document = request.env['document.approval'].sudo().browse(document_id)

        # Verificar acceso: el creador O el jefe de equipo del grupo de trabajo
        is_owner = document.user_id == user
        is_boss_of_group = False
        if user.has_group('portal_requests.group_equip_boss') and document.work_group_id:
            is_boss_of_group = document.work_group_id.equip_boss == user

        if not is_owner and not is_boss_of_group:
            return request.redirect('/my')

        # Publicar el mensaje
        if message and message.strip():
            document.sudo().message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=user.partner_id.id
            )

        # Redirigir de vuelta al detalle
        return request.redirect(f'/my/documents/{document_id}?success=message_posted')

    @http.route(['/my/documents/<int:document_id>/add_attachment'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_document_add_attachment(self, document_id, **post):
        user = request.env.user
        document = request.env['document.approval'].sudo().browse(document_id)
        # Comprobar acceso: propietario o jefe de grupo
        is_owner = document.user_id == user
        is_boss_of_group = user.has_group('portal_requests.group_equip_boss') and document.work_group_id and document.work_group_id.equip_boss == user
        if not is_owner and not is_boss_of_group:
            return request.redirect('/my')
        file_storage = request.httprequest.files.get('attachment')
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/documents/{document_id}')
        filename = file_storage.filename
        mimetype = file_storage.content_type
        file_data = file_storage.read()
        if not file_data:
            return request.redirect(f'/my/documents/{document_id}')
        datas_b64 = base64.b64encode(file_data).decode('ascii')
        request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': datas_b64,
            'res_model': 'document.approval',
            'res_id': document.id,
            'mimetype': mimetype,
        })
        return request.redirect(f'/my/documents/{document_id}')

    # ==========================================
    # Rutas para Proyectos (Cuentas Analíticas)
    # ==========================================

    @http.route(['/my/analytic_projects', '/my/analytic_projects/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_projects(self, page=1, sortby=None, filterby=None, **kw):
        """Muestra el listado de proyectos visibles para el usuario portal."""
        user = request.env.user

        projects = request.env['account.analytic.account'].search(
            self._get_accessible_analytic_project_domain(user),
            order='name asc'
        )

        values = {
            'projects': projects.sudo(),  # sudo() para renderizar campos relacionados en la vista
            'page_name': 'analytic_project',
            'default_url': '/my/analytic_projects',
        }

        return request.render("portal_requests.portal_my_projects", values)

    @http.route(['/my/analytic_projects/<int:project_id>'], type='http', auth="user", website=True)
    def portal_my_project_detail(self, project_id, success=None, **kw):
        print("*"*100)
        print("Accediendo al detalle del proyecto con ID:", project_id)
        print(f"Usuario actual: {request.env.user.name} (ID: {request.env.user.id})")
        print("*"*100)
        """Muestra el detalle de un proyecto (cuenta analítica)"""
        # Buscar el proyecto accesible para el usuario portal (responsable o jefe de su grupo)
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )

        print(f"Proyecto encontrado: {project}")
        if project:
            print(f"Nombre del proyecto: {project.name}")
            print(f"Responsable del proyecto: {project.responsible_id.name if project.responsible_id else 'Sin responsable'}")

        # Si no existe o no es el responsable, redirigir
        if not project:
            print("⚠ No se encontró el proyecto o el usuario no es responsable, redirigiendo a /my")
            return request.redirect('/my')

        # Usar sudo() para renderizar campos relacionados en la vista
        project = project.sudo()

        # Generar access_token si no existe (necesario para el chatter)
        project._portal_ensure_token()

        # Obtener TODOS los mensajes del chatter usando sudo para tener acceso completo
        raw_messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'account.analytic.account'),
            ('res_id', '=', project_id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')

        # Enriquecer mensajes: si el body está vacío, construirlo desde tracking_value_ids
        messages = []
        for msg in raw_messages:
            body = msg.body or ''
            # Detectar body vacío o con solo etiquetas HTML vacías
            plain_body = body.replace('<p>', '').replace('</p>', '').replace('<br>', '').replace('<br/>', '').strip()
            if not plain_body and msg.tracking_value_ids:
                tracking_lines = []
                for tracking in msg.tracking_value_ids:
                    if tracking.field_id:
                        field_label = tracking.field_id.field_description
                    elif tracking.field_info:
                        field_label = tracking.field_info.get('desc', '')
                    else:
                        field_label = ''
                    old_val = tracking.old_value_char or (str(tracking.old_value_integer) if tracking.old_value_integer else 'Ninguno')
                    new_val = tracking.new_value_char or (str(tracking.new_value_integer) if tracking.new_value_integer else 'Ninguno')
                    if old_val != new_val:
                        tracking_lines.append(f"<strong>{field_label}:</strong> {old_val} → {new_val}")
                    else:
                        tracking_lines.append(f"<strong>{field_label}:</strong> {new_val}")
                body = '<br/>'.join(tracking_lines)
            messages.append({
                'author_id': msg.author_id,
                'date': msg.date,
                'body': body,
                'message_type': msg.message_type,
            })

        # Obtener los adjuntos relacionados con este proyecto (cuenta analítica)
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'account.analytic.account'),
            ('res_id', '=', project_id)
        ])

        values = {
            'project': project,
            'messages': messages,
            'attachments': attachments,
            'page_name': 'analytic_project',
            'success_message': success,
        }

        return request.render("portal_requests.portal_my_project_detail", values)

    @http.route(['/my/analytic_projects/<int:project_id>/post_message'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_project_post_message(self, project_id, message, **kw):
        """Permite al usuario portal enviar un mensaje en el proyecto"""
        # Buscar el proyecto accesible para el usuario portal (responsable o jefe de su grupo)
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )

        # Si no existe o no es el responsable, redirigir
        if not project:
            return request.redirect('/my')

        # Publicar el mensaje
        if message and message.strip():
            project.sudo().message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=request.env.user.partner_id.id
            )

        # Redirigir de vuelta al detalle
        return request.redirect(f'/my/analytic_projects/{project_id}?success=message_posted')

    @http.route(['/my/analytic_projects/<int:project_id>/invoices_list'], type='http', auth="user", website=True)
    def portal_project_invoices(self, project_id, **kw):
        """Muestra las facturas asociadas a un proyecto (cuenta analítica)"""
        # Buscar el proyecto accesible para el usuario portal (responsable o jefe de su grupo)
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )

        # Si no existe o no es el responsable, redirigir
        if not project:
            return request.redirect('/my')

        # Buscar facturas que tengan líneas con distribución analítica para este proyecto
        invoice_lines = request.env['account.move.line'].sudo().search([
            ('analytic_distribution', '!=', False),
            ('move_id.move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']),
            ('move_id.state', '!=', 'cancel')
        ])

        # Filtrar las que contienen este analytic account en su distribución
        # analytic_distribution es un JSON como: {"42": 100.0} o {"42,43": 50.0}
        invoice_ids = set()
        for line in invoice_lines:
            if line.analytic_distribution:
                for key in line.analytic_distribution.keys():
                    # Las claves pueden ser "42" o "42,43" (múltiples IDs separados por coma)
                    analytic_ids = [int(id_str) for id_str in key.split(',')]
                    if project_id in analytic_ids:
                        invoice_ids.add(line.move_id.id)
                        break

        # Obtener las facturas con sudo para poder verlas
        invoices = request.env['account.move'].sudo().browse(list(invoice_ids))

        values = {
            'project': project.sudo(),
            'invoices': invoices,
            'page_name': 'analytic_project_invoices',
        }

        return request.render("portal_requests.portal_project_invoices", values)

    @http.route(['/my/analytic_projects/<int:project_id>/invoices_list/<int:invoice_id>'], type='http', auth="user", website=True)
    def portal_project_invoice_detail(self, project_id, invoice_id, success=None, **kw):
        """Muestra el detalle de una factura asociada a un proyecto"""
        # Buscar el proyecto accesible para el usuario portal (responsable o jefe de su grupo)
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )

        # Si no existe o no es el responsable, redirigir
        if not project:
            return request.redirect('/my')

        # Obtener la factura con sudo (ya que el usuario portal no tiene acceso directo)
        invoice = request.env['account.move'].sudo().browse(invoice_id)

        # Si la factura no existe, redirigir al listado
        if not invoice.exists():
            return request.redirect(f'/my/analytic_projects/{project_id}/invoices_list')
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', invoice.id)
        ])


        # Obtener los mensajes del chatter de la factura
        raw_messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'account.move'),
            ('res_id', '=', invoice_id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')
        messages = self._enrich_messages(raw_messages)
        invoice_payments = request.env['account.payment'].sudo().search([
            ('invoice_ids', 'in', [invoice.id]),
        ])

        values = {
            'project': project.sudo(),
            'invoice': invoice,
            'invoice_payments': invoice_payments,
            'messages': messages,
            'page_name': 'analytic_project_invoice_detail',
            'success_message': success,
            'attachments': attachments,
        }

        return request.render("portal_requests.portal_project_invoice_detail", values)

    @http.route(['/my/analytic_projects/<int:project_id>/invoices_list/<int:invoice_id>/payments_list'], type='http', auth="user", website=True)
    def portal_project_invoice_payments(self, project_id, invoice_id, **kw):
        """Muestra los pagos asociados a una factura asociada a un proyecto"""
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )

        if not project:
            return request.redirect('/my')

        invoice = request.env['account.move'].sudo().browse(invoice_id)

        if not invoice.exists():
            return request.redirect(f'/my/analytic_projects/{project_id}/invoices_list')

        payments = request.env['account.payment'].sudo().search([
            ('invoice_ids', 'in', [invoice.id]),
        ])

        return request.render("portal_requests.portal_project_invoice_payments", {
            'project': project.sudo(),
            'invoice': invoice,
            'payments': payments,
            'page_name': 'analytic_project_invoice_payments',
        })

    @route('/my/analytic_projects/<int:project_id>/invoices_list/<int:invoice_id>/add_attachment', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_invoice_add_attachment(self,project_id, invoice_id, **post):
        """Permite al usuario portal subir un adjunto al pago"""
        user = request.env.user
        payment = request.env['account.payment'].sudo().browse(invoice_id)
        # Validar acceso igual que en portal_my_payment_detail
        analytic_domain = [('responsible_id', '=', user.id)]
        if user.has_group('portal_requests.group_equip_boss'):
            work_groups = user.work_group_ids
            if work_groups:
                analytic_domain = ['|', ('responsible_id', '=', user.id), ('work_group_id', 'in', work_groups.ids)]
        projects = request.env['account.analytic.account'].sudo().search(analytic_domain)
        project_ids = projects.ids
        paid_invoices = request.env['account.move'].sudo().search([
            ('analytic_distribution', '!=', False),
            ('move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']),
            ('state', '=', 'posted'),
            ('payment_state', '=', 'paid'),
        ])
        visible_invoice_ids = []
        for inv in paid_invoices:
            analytic_dist = inv.analytic_distribution or {}
            analytic_ids = set(int(id_str) for key in analytic_dist.keys() for id_str in key.split(','))
            if any(pid in analytic_ids for pid in project_ids):
                visible_invoice_ids.append(inv.id)
        if not payment.invoice_ids.filtered(lambda inv: inv.id in visible_invoice_ids):
            return request.not_found()
        # Procesar archivo
        # DEBUG: log post y file_storage
        file_storage = post.get('attachment')
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/payments/{invoice_id}?error=missing_file')
        filename = file_storage.filename
        # Permitir cualquier tipo de archivo, solo limitar tamaño
        max_size = 10 * 1024 * 1024  # 10MB
        mimetype = file_storage.content_type
        file_storage.stream.seek(0, 2)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        if size > max_size:
            return request.redirect(f'/my/payments/{invoice_id}?error=invalid_file')
        # Crear attachment
        import base64
        file_data = file_storage.read()
        datas_b64 = base64.b64encode(file_data).decode('ascii')
        attachment = request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': datas_b64,
            'res_model': 'account.payment',
            'res_id': payment.id,
            'mimetype': mimetype,
        })
        return request.redirect(f'/my/analytic_projects/<int:project_id>/invoices_list/<int:invoice_id>?success=attachment_uploaded')

    @http.route(['/my/analytic_projects/<int:project_id>/invoices_list/<int:invoice_id>/post_message'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_project_invoice_post_message(self, project_id, invoice_id, message, **kw):
        """Permite enviar un mensaje en el chatter de una factura asociada a un proyecto"""
        # Buscar el proyecto accesible para el usuario portal (responsable o jefe de su grupo)
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )

        # Si no existe o no es el responsable, redirigir
        if not project:
            return request.redirect('/my')

        # Obtener la factura con sudo
        invoice = request.env['account.move'].sudo().browse(invoice_id)

        # Publicar el mensaje
        if message and message.strip():
            invoice.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=request.env.user.partner_id.id
            )

        # Redirigir de vuelta al detalle
        return request.redirect(f'/my/analytic_projects/{project_id}/invoices_list/{invoice_id}?success=message_posted')

    # Rutas para Solicitudes de Proyectos
    # =====================================

    @http.route(['/my/project_requests', '/my/project_requests/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_project_requests(self, page=1, sortby=None, **kw):
        """Muestra el listado de solicitudes de proyectos del usuario"""
        # Solo los jefes de equipo pueden acceder
        if not request.env.user.has_group('portal_requests.group_equip_boss'):
            return request.redirect('/my')

        user = request.env.user

        # Buscar solicitudes de proyectos del usuario
        project_requests = request.env['portal.project.request'].search([
            ('user_id', '=', user.id)
        ], order='create_date desc')

        values = {
            'project_requests': project_requests,
            'page_name': 'project_request',
        }

        return request.render("portal_requests.portal_my_project_requests", values)

    @http.route(['/my/project_requests/<int:request_id>'], type='http', auth="user", website=True)
    def portal_my_project_request_detail(self, request_id, success=None, **kw):
        """Muestra el detalle de una solicitud de proyecto"""
        # Solo los jefes de equipo pueden acceder
        if not request.env.user.has_group('portal_requests.group_equip_boss'):
            return request.redirect('/my')

        # Buscar la solicitud del usuario
        project_request = request.env['portal.project.request'].search([
            ('id', '=', request_id),
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        # Si no existe o no es del usuario, redirigir
        if not project_request:
            return request.redirect('/my')

        # Obtener los mensajes del chatter
        raw_messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'portal.project.request'),
            ('res_id', '=', request_id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')
        messages = self._enrich_messages(raw_messages)

        # Obtener los adjuntos generales de la solicitud
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'portal.project.request'),
            ('res_id', '=', request_id)
        ])

        values = {
            'project_request': project_request.sudo(),
            'messages': messages,
            'page_name': 'project_request_detail',
            'success_message': success,
            'attachments': attachments,
        }

        return request.render("portal_requests.portal_my_project_request_detail", values)

    @http.route(['/my/project_requests/<int:request_id>/add_attachment'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_project_request_add_attachment(self, request_id, **post):
        """Permite al usuario portal subir un adjunto a la solicitud de proyecto"""
        # Solo los jefes de equipo pueden acceder
        if not request.env.user.has_group('portal_requests.group_equip_boss'):
            return request.redirect('/my')

        # Buscar la solicitud del usuario
        project_request = request.env['portal.project.request'].search([
            ('id', '=', request_id),
            ('user_id', '=', request.env.user.id)
        ], limit=1)
        if not project_request:
            return request.redirect('/my')

        file_storage = request.httprequest.files.get('attachment')
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/project_requests/{request_id}')
        filename = file_storage.filename
        mimetype = file_storage.content_type
        file_data = file_storage.read()
        if not file_data:
            return request.redirect(f'/my/project_requests/{request_id}')
        import base64
        datas_b64 = base64.b64encode(file_data).decode('ascii')
        request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': datas_b64,
            'res_model': 'portal.project.request',
            'res_id': project_request.id,
            'mimetype': mimetype,
        })
        return request.redirect(f'/my/project_requests/{request_id}')

    @http.route(['/my/project_requests/<int:request_id>/post_message'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_project_request_post_message(self, request_id, message, **kw):
        """Permite enviar un mensaje en el chatter de una solicitud de proyecto"""
        # Solo los jefes de equipo pueden acceder
        if not request.env.user.has_group('portal_requests.group_equip_boss'):
            return request.redirect('/my')

        # Buscar la solicitud del usuario
        project_request = request.env['portal.project.request'].search([
            ('id', '=', request_id),
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        # Si no existe o no es del usuario, redirigir
        if not project_request:
            return request.redirect('/my')

        # Publicar el mensaje
        if message and message.strip():
            project_request.sudo().message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=request.env.user.partner_id.id
            )

        # Redirigir de vuelta al detalle
        return request.redirect(f'/my/project_requests/{request_id}?success=message_posted')

    @http.route(['/my/analytic_projects/<int:project_id>/add_attachment'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_project_add_attachment(self, project_id, **post):
        """Permite al usuario portal subir un adjunto al proyecto analítico"""
        project = request.env['account.analytic.account'].sudo().browse(project_id)
        # Validar acceso: responsable o jefe de grupo
        user = request.env.user
        domain = [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(user)
        accessible = request.env['account.analytic.account'].search(domain, limit=1)
        if not accessible:
            return request.redirect('/my')
        file_storage = post.get('attachment')
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/analytic_projects/{project_id}?error=missing_file')
        filename = file_storage.filename
        mimetype = file_storage.content_type
        file_data = file_storage.read()
        import base64
        datas_b64 = base64.b64encode(file_data).decode('ascii')
        request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': datas_b64,
            'res_model': 'account.analytic.account',
            'res_id': project.id,
            'mimetype': mimetype,
        })
        return request.redirect(f'/my/analytic_projects/{project_id}?success=attachment_uploaded')

    @http.route(['/my/invoices/<int:invoice_request_id>/add_attachment'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_invoice_add_attachment(self, invoice_request_id, **post):
        user = request.env.user
        invoice_request = request.env['portal.invoice.request'].sudo().browse(invoice_request_id)
        # Comprobar acceso: propietario o jefe de grupo
        if not self._can_access_invoice_request(invoice_request):
            return request.redirect('/my')
        file_storage = request.httprequest.files.get('attachment')
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/invoices/{invoice_request_id}')
        filename = file_storage.filename
        mimetype = file_storage.content_type
        file_data = file_storage.read()
        if not file_data:
            return request.redirect(f'/my/invoices/{invoice_request_id}')
        datas_b64 = base64.b64encode(file_data).decode('ascii')
        request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': datas_b64,
            'res_model': 'portal.invoice.request',
            'res_id': invoice_request.id,
            'mimetype': mimetype,
        })
        return request.redirect(f'/my/invoices/{invoice_request_id}')

    @http.route(['/my/expenses/<int:expense_id>/add_attachment'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_expense_add_attachment(self, expense_id, **post):
        """Permite al usuario portal subir un adjunto a la solicitud de gastos"""
        expense = request.env['portal.hr.expensive.request'].sudo().browse(expense_id)
        user = request.env.user
        # Validar acceso: propietario o jefe de grupo (opcional, aquí solo comprobamos existencia)
        if not expense:
            return request.redirect('/my/expenses')
        file_storage = request.httprequest.files.get('attachment')
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/expenses/{expense_id}')
        filename = file_storage.filename
        mimetype = file_storage.content_type
        file_data = file_storage.read()
        if not file_data:
            return request.redirect(f'/my/expenses/{expense_id}')
        import base64
        datas_b64 = base64.b64encode(file_data).decode('ascii')
        request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': datas_b64,
            'res_model': 'portal.hr.expensive.request',
            'res_id': expense.id,
            'mimetype': mimetype,
        })
        return request.redirect(f'/my/expenses/{expense_id}')
