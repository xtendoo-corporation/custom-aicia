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

    @route('/my/payments', auth='user', website=True)
    def portal_my_payments(self, **kwargs):
        user = request.env.user
        analytic_domain = [('responsible_id', '=', user.id)]
        if user.has_group('portal_requests.group_equip_boss'):
            work_groups = user.work_group_ids
            if work_groups:
                analytic_domain = ['|', ('responsible_id', '=', user.id), ('work_group_id', 'in', work_groups.ids)]
        projects = request.env['account.analytic.account'].sudo().search(analytic_domain)
        project_ids = projects.ids
        _logger.warning(f"[PORTAL PAYMENTS] Proyectos accesibles: {project_ids}")
        # Buscar facturas pagadas asociadas a esos proyectos (cabecera)
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
        return request.render('portal_requests.portal_my_payments', {
            'payments': payments,
            'page_name': 'payments',  # Para breadcrumbs
        })

    @route('/my/payments/<int:payment_id>', auth='user', website=True)
    def portal_my_payment_detail(self, payment_id, **kwargs):
        user = request.env.user
        payment = request.env['account.payment'].sudo().browse(payment_id)
        analytic_domain = [('responsible_id', '=', user.id)]
        if user.has_group('portal_requests.group_equip_boss'):
            work_groups = user.work_group_ids
            if work_groups:
                analytic_domain = ['|', ('responsible_id', '=', user.id), ('work_group_id', 'in', work_groups.ids)]
        projects = request.env['account.analytic.account'].sudo().search(analytic_domain)
        project_ids = projects.ids
        # Buscar facturas pagadas asociadas a esos proyectos
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
        # Comprobar si el pago está asociado a alguna de esas facturas
        if not payment.invoice_ids.filtered(lambda inv: inv.id in visible_invoice_ids):
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
            'attachments': attachments,
            'messages': messages,
            'page_name': 'payment',  # Necesario para breadcrumbs
        })

    @route('/my/payments/<int:payment_id>/post_message', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_payment_post_message(self, payment_id, message, **kw):
        """Permite al usuario portal enviar un mensaje en el pago"""
        user = request.env.user
        payment = request.env['account.payment'].sudo().browse(payment_id)
        # Comprobar acceso: el usuario debe poder ver el pago (como en portal_my_payment_detail)
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
        # Publicar el mensaje
        if message and message.strip():
            payment.sudo().message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=user.partner_id.id
            )
        # Redirigir de vuelta al detalle
        return request.redirect(f'/my/payments/{payment_id}?success=message_posted')

    @route('/my/payments/<int:payment_id>/add_attachment', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_payment_add_attachment(self, payment_id, **post):
        """Permite al usuario portal subir un adjunto al pago"""
        user = request.env.user
        payment = request.env['account.payment'].sudo().browse(payment_id)
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
        _logger.warning(f"[PORTAL PAYMENTS][DEBUG] POST keys: {list(post.keys())}")
        file_storage = post.get('attachment')
        _logger.warning(f"[PORTAL PAYMENTS][DEBUG] file_storage: {file_storage}")
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/payments/{payment_id}?error=missing_file')
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
            return request.redirect(f'/my/payments/{payment_id}?error=invalid_file')
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
        return request.redirect(f'/my/payments/{payment_id}?success=attachment_uploaded')
