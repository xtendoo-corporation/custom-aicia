from odoo.http import request, Controller, route
import logging

_logger = logging.getLogger(__name__)

class PortalPaymentController(Controller):
    def _enrich_messages(self, raw_messages):
        """Convierte un recordset de mail.message en lista de dicts, igual que en facturas/gastos."""
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

    def _get_accessible_project_ids(self, user):
        analytic_domain = [('responsible_id', '=', user.id)]
        if user.has_group('portal_requests.group_equip_boss'):
            work_groups = user.work_group_ids
            if work_groups:
                analytic_domain = ['|', ('responsible_id', '=', user.id), ('work_group_id', 'in', work_groups.ids)]
        return request.env['account.analytic.account'].sudo().search(analytic_domain).ids

    def _get_visible_invoice_ids(self, user):
        project_ids = self._get_accessible_project_ids(user)
        if not project_ids:
            return set()
        paid_invoices = request.env['account.move'].sudo().search([
            ('analytic_distribution', '!=', False),
            ('move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']),
            ('state', '=', 'posted'),
            ('payment_state', '=', 'paid'),
        ])
        visible_invoice_ids = set()
        for inv in paid_invoices:
            analytic_dist = inv.analytic_distribution or {}
            analytic_ids = set(int(id_str) for key in analytic_dist.keys() for id_str in key.split(','))
            if any(pid in analytic_ids for pid in project_ids):
                visible_invoice_ids.add(inv.id)
        return visible_invoice_ids

    def _get_accessible_payment_and_invoices(self, payment_id, user=None):
        user = user or request.env.user
        payment = request.env['account.payment'].sudo().browse(payment_id)
        if not payment.exists():
            return request.env['account.payment'], request.env['account.move']
        visible_invoice_ids = self._get_visible_invoice_ids(user)
        visible_invoices = payment.invoice_ids.filtered(lambda inv: inv.id in visible_invoice_ids).sudo()
        if not visible_invoices:
            return request.env['account.payment'], request.env['account.move']
        return payment, visible_invoices

    def _get_accessible_invoice_related_payments(self, payment_id, invoice_id, user=None):
        user = user or request.env.user
        payment, visible_invoices = self._get_accessible_payment_and_invoices(payment_id, user)
        if not payment:
            return request.env['account.payment'], request.env['account.move'], request.env['account.payment']
        invoice = visible_invoices.filtered(lambda inv: inv.id == invoice_id)
        if not invoice:
            return request.env['account.payment'], request.env['account.move'], request.env['account.payment']
        related_payments = request.env['account.payment'].sudo().search([
            ('invoice_ids', 'in', [invoice.id]),
        ])
        return payment, invoice, related_payments

    def _split_payment_entries_by_type(self, payments, visible_invoice_ids=None):
        visible_invoice_ids = set(visible_invoice_ids or [])
        customer_move_types = {'out_invoice', 'out_refund'}
        supplier_move_types = {'in_invoice', 'in_refund'}
        customer_entries = []
        supplier_entries = []

        for payment in payments:
            visible_invoices = payment.invoice_ids
            if visible_invoice_ids:
                visible_invoices = visible_invoices.filtered(lambda inv: inv.id in visible_invoice_ids)

            customer_invoices = visible_invoices.filtered(lambda inv: inv.move_type in customer_move_types)
            supplier_invoices = visible_invoices.filtered(lambda inv: inv.move_type in supplier_move_types)

            if customer_invoices and not supplier_invoices:
                customer_entries.append({'payment': payment, 'invoices': customer_invoices})
            elif supplier_invoices and not customer_invoices:
                supplier_entries.append({'payment': payment, 'invoices': supplier_invoices})
            elif customer_invoices and supplier_invoices:
                if payment.partner_type == 'supplier':
                    supplier_entries.append({'payment': payment, 'invoices': supplier_invoices})
                else:
                    customer_entries.append({'payment': payment, 'invoices': customer_invoices})
            elif visible_invoices:
                if payment.partner_type == 'supplier':
                    supplier_entries.append({'payment': payment, 'invoices': visible_invoices})
                else:
                    customer_entries.append({'payment': payment, 'invoices': visible_invoices})

        return customer_entries, supplier_entries

    @route('/my/payments', auth='user', website=True)
    def portal_my_payments(self, **kwargs):
        user = request.env.user
        project_ids = self._get_accessible_project_ids(user)
        _logger.warning(f"[PORTAL PAYMENTS] Proyectos accesibles: {project_ids}")
        # Buscar facturas pagadas asociadas a esos proyectos (cabecera)
        visible_invoice_ids = list(self._get_visible_invoice_ids(user))
        _logger.warning(f"[PORTAL PAYMENTS] Facturas pagadas visibles: {visible_invoice_ids}")
        # Log temporal: mostrar los campos de relación en todos los pagos
        all_payments = request.env['account.payment'].sudo().search([])
        for pay in all_payments:
            _logger.warning(f"[PORTAL PAYMENTS][DEBUG] Pago {pay.id}: invoice_ids={pay.invoice_ids.ids}, reconciled_invoice_ids={getattr(pay, 'reconciled_invoice_ids', False) and pay.reconciled_invoice_ids.ids}")
        # Buscar pagos asociados a esas facturas
        payments = request.env['account.payment'].sudo().search([
            ('invoice_ids', 'in', visible_invoice_ids),
            # Quitar filtro de estado para mostrar todos los pagos relacionados
        ])
        _logger.warning(f"[PORTAL PAYMENTS] Pagos visibles finales: {payments.ids}")
        customer_payment_entries, supplier_payment_entries = self._split_payment_entries_by_type(payments, visible_invoice_ids)
        return request.render('portal_requests.portal_my_payments', {
            'payments': payments,
            'customer_payment_entries': customer_payment_entries,
            'supplier_payment_entries': supplier_payment_entries,
            'page_name': 'payments',  # Para breadcrumbs
        })

    @route('/my/payments/<int:payment_id>', auth='user', website=True)
    def portal_my_payment_detail(self, payment_id, **kwargs):
        user = request.env.user
        payment, visible_invoices = self._get_accessible_payment_and_invoices(payment_id, user)
        if not payment:
            return request.not_found()
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'account.payment'),
            ('res_id', '=', payment.id)
        ])
        # Buscar mensajes igual que en facturas/gastos
        raw_messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'account.payment'),
            ('res_id', '=', payment.id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')
        messages = self._enrich_messages(raw_messages)
        return request.render('portal_requests.portal_my_payment_detail', {
            'payment': payment,
            'payment_visible_invoices': visible_invoices,
            'attachments': attachments,
            'messages': messages,
            'page_name': 'payment',  # Necesario para breadcrumbs
            'success_message': kwargs.get('success'),
        })

    @route('/my/payments/<int:payment_id>/invoices_list', auth='user', website=True)
    def portal_my_payment_invoices(self, payment_id, **kwargs):
        payment, visible_invoices = self._get_accessible_payment_and_invoices(payment_id)
        if not payment:
            return request.not_found()
        return request.render('portal_requests.portal_payment_invoices', {
            'payment': payment,
            'invoices': visible_invoices,
            'page_name': 'payment_invoices',
        })

    @route('/my/payments/<int:payment_id>/invoices_list/<int:invoice_id>', auth='user', website=True)
    def portal_my_payment_invoice_detail(self, payment_id, invoice_id, **kwargs):
        payment, invoice, invoice_payments = self._get_accessible_invoice_related_payments(payment_id, invoice_id)
        if not payment:
            return request.not_found()
        if not invoice:
            return request.not_found()
        return request.render('portal_requests.portal_payment_invoice_detail', {
            'payment': payment,
            'invoice': invoice,
            'invoice_payments': invoice_payments,
            'page_name': 'payment_invoice_detail',
            'success_message': kwargs.get('success'),
        })

    @route('/my/payments/<int:payment_id>/invoices_list/<int:invoice_id>/payments_list', auth='user', website=True)
    def portal_my_payment_invoice_payments(self, payment_id, invoice_id, **kwargs):
        payment, invoice, invoice_payments = self._get_accessible_invoice_related_payments(payment_id, invoice_id)
        if not payment or not invoice:
            return request.not_found()
        return request.render('portal_requests.portal_invoice_payments', {
            'payment': payment,
            'invoice': invoice,
            'payments': invoice_payments,
            'page_name': 'invoice_payments',
        })

    @route('/my/payments/<int:payment_id>/post_message', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_payment_post_message(self, payment_id, message, redirect_url=None, **kw):
        """Permite al usuario portal enviar un mensaje en el pago"""
        user = request.env.user
        payment, visible_invoices = self._get_accessible_payment_and_invoices(payment_id, user)
        if not payment or not visible_invoices:
            return request.not_found()
        # Publicar el mensaje
        if message and message.strip():
            payment.sudo().message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=user.partner_id.id
            )
        # Redirigir de vuelta al detalle
        target = redirect_url or f'/my/payments/{payment_id}'
        return request.redirect(f'{target}?success=message_posted')

    @route('/my/payments/<int:payment_id>/add_attachment', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_payment_add_attachment(self, payment_id, redirect_url=None, **post):
        """Permite al usuario portal subir un adjunto al pago"""
        user = request.env.user
        payment, visible_invoices = self._get_accessible_payment_and_invoices(payment_id, user)
        if not payment or not visible_invoices:
            return request.not_found()
        target = redirect_url or f'/my/payments/{payment_id}'
        # Procesar archivo
        # DEBUG: log post y file_storage
        _logger.warning(f"[PORTAL PAYMENTS][DEBUG] POST keys: {list(post.keys())}")
        file_storage = post.get('attachment')
        _logger.warning(f"[PORTAL PAYMENTS][DEBUG] file_storage: {file_storage}")
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'{target}?error=missing_file')
        filename = file_storage.filename
        _logger.warning(f"[PORTAL PAYMENTS][DEBUG] filename: {filename}")
        # Permitir cualquier tipo de archivo, solo limitar tamaño
        max_size = 10 * 1024 * 1024  # 10MB
        mimetype = file_storage.content_type
        _logger.warning(f"[PORTAL PAYMENTS][DEBUG] mimetype: {mimetype}")
        file_storage.stream.seek(0, 2)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        _logger.warning(f"[PORTAL PAYMENTS][DEBUG] size: {size}")
        if size > max_size:
            return request.redirect(f'{target}?error=invalid_file')
        # Crear attachment
        import base64
        file_data = file_storage.read()
        datas_b64 = base64.b64encode(file_data).decode('ascii')
        _logger.warning(f"[PORTAL PAYMENTS][DEBUG] datas_b64 length: {len(datas_b64)}")
        attachment = request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': datas_b64,
            'res_model': 'account.payment',
            'res_id': payment.id,
            'mimetype': mimetype,
        })
        return request.redirect(f'{target}?success=attachment_uploaded')
