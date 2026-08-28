from odoo.http import request, Controller, route
import csv
import io
import logging

from .portal_pdf_utils import is_pdf

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
        # group_administrative implica group_equip_boss (mismas funciones que
        # Jefe de Equipo) pero no debe acceder al histórico de pagos/facturas de los
        # proyectos del equipo, que es información económica.
        if user.has_group('portal_requests.group_equip_boss') and not user.has_group('portal_requests.group_administrative'):
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

    def _build_payment_entries(self, payments, visible_invoice_ids=None):
        visible_invoice_ids = set(visible_invoice_ids or [])
        customer_move_types = {'out_invoice', 'out_refund'}
        supplier_move_types = {'in_invoice', 'in_refund'}
        entries = []

        for payment in payments:
            visible_invoices = payment.invoice_ids
            if visible_invoice_ids:
                visible_invoices = visible_invoices.filtered(lambda inv: inv.id in visible_invoice_ids)

            customer_invoices = visible_invoices.filtered(lambda inv: inv.move_type in customer_move_types)
            supplier_invoices = visible_invoices.filtered(lambda inv: inv.move_type in supplier_move_types)

            if customer_invoices and not supplier_invoices:
                payment_type = 'customer'
                invoices = customer_invoices
            elif supplier_invoices and not customer_invoices:
                payment_type = 'supplier'
                invoices = supplier_invoices
            elif customer_invoices and supplier_invoices:
                if payment.partner_type == 'supplier':
                    payment_type = 'supplier'
                    invoices = supplier_invoices
                else:
                    payment_type = 'customer'
                    invoices = customer_invoices
            elif visible_invoices:
                if payment.partner_type == 'supplier':
                    payment_type = 'supplier'
                else:
                    payment_type = 'customer'
                invoices = visible_invoices
            else:
                continue

            entries.append({
                'payment': payment,
                'invoices': invoices,
                'payment_type': payment_type,
                'type_label': 'Cliente' if payment_type == 'customer' else 'Proveedor',
            })

        return entries

    def _payment_state_labels(self):
        return {
            'draft': 'Borrador',
            'in_process': 'En proceso',
            'paid': 'Pagado',
            'posted': 'Publicado',
            'cancel': 'Cancelado',
            'cancelled': 'Cancelado',
        }

    def _payment_date_value(self, payment):
        return payment.date or (payment.create_date.date() if payment.create_date else False)

    def _payment_date_label(self, payment):
        payment_date = self._payment_date_value(payment)
        return payment_date.strftime('%d/%m/%Y') if payment_date else 'Sin fecha'

    def _payment_amount_search_values(self, payment):
        amount = payment.amount or 0.0
        fixed_amount = f'{amount:.2f}'
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        values = [str(amount), fixed_amount, fixed_amount.replace('.', ','), spanish_amount, f'{spanish_amount} €']
        if float(amount).is_integer():
            values.append(str(int(amount)))
        return values

    def _payment_amount_label(self, payment):
        amount = payment.amount or 0.0
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        currency = payment.currency_id
        symbol = currency.symbol if currency and currency.symbol else '€'
        return f'{spanish_amount} {symbol}'

    def _payment_invoice_names_label(self, invoices):
        return ', '.join(invoices.mapped('name')) if invoices else '-'

    def _get_payment_listing_values(self, user, search=None, search_in='all', groupby='none', filterby='all'):
        """Construye una única fuente de verdad para render y exportación de Mis Pagos."""
        project_ids = self._get_accessible_project_ids(user)
        _logger.warning(f"[PORTAL PAYMENTS] Proyectos accesibles: {project_ids}")
        visible_invoice_ids = list(self._get_visible_invoice_ids(user))
        _logger.warning(f"[PORTAL PAYMENTS] Facturas pagadas visibles: {visible_invoice_ids}")
        all_payments = request.env['account.payment'].sudo().search([])
        for pay in all_payments:
            _logger.warning(f"[PORTAL PAYMENTS][DEBUG] Pago {pay.id}: invoice_ids={pay.invoice_ids.ids}, reconciled_invoice_ids={getattr(pay, 'reconciled_invoice_ids', False) and pay.reconciled_invoice_ids.ids}")
        payments = request.env['account.payment'].sudo().search([
            ('invoice_ids', 'in', visible_invoice_ids),
        ], order='date desc, name desc')
        _logger.warning(f"[PORTAL PAYMENTS] Pagos visibles finales: {payments.ids}")
        payment_entries = self._build_payment_entries(payments, visible_invoice_ids)

        searchbar_inputs = {
            'all': {'input': 'all', 'label': 'Buscar en todo'},
            'name': {'input': 'name', 'label': 'Referencia'},
            'invoice': {'input': 'invoice', 'label': 'Factura'},
            'date': {'input': 'date', 'label': 'Fecha'},
            'amount': {'input': 'amount', 'label': 'Importe'},
            'state': {'input': 'state', 'label': 'Estado'},
            'type': {'input': 'type', 'label': 'Tipo'},
        }
        if search_in not in searchbar_inputs:
            search_in = 'all'

        searchbar_filters = {
            'all': {'input': 'all', 'label': 'Todos'},
            'customer': {'input': 'customer', 'label': 'Pagos de clientes'},
            'supplier': {'input': 'supplier', 'label': 'Pagos de proveedores'},
        }
        if filterby not in searchbar_filters:
            filterby = 'all'
        payments_header_title = 'Mis Pagos' if filterby == 'all' else searchbar_filters.get(filterby, searchbar_filters['all']).get('label', 'Mis Pagos')

        searchbar_groupby = {
            'none': {'input': 'none', 'label': 'Sin agrupar'},
            'type': {'input': 'type', 'label': 'Tipo'},
            'state': {'input': 'state', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha'},
        }
        if groupby not in searchbar_groupby:
            groupby = 'none'

        state_labels = self._payment_state_labels()

        if filterby != 'all':
            payment_entries = [entry for entry in payment_entries if entry['payment_type'] == filterby]

        if search:
            needle = search.strip().lower()
            if needle:
                def _entry_matches(entry):
                    payment = entry['payment']
                    invoices = entry['invoices']
                    values = []

                    if search_in in ('all', 'name'):
                        values.append(payment.name or '')
                    if search_in in ('all', 'invoice'):
                        values.extend(invoices.mapped('name'))
                    if search_in in ('all', 'date'):
                        values.append(str(self._payment_date_value(payment) or ''))
                        values.append(self._payment_date_label(payment))
                    if search_in in ('all', 'amount'):
                        values.extend(self._payment_amount_search_values(payment))
                    if search_in in ('all', 'state'):
                        values.append(state_labels.get(payment.state, payment.state or ''))
                        values.append(payment.state or '')
                    if search_in in ('all', 'type'):
                        values.append(entry['type_label'])

                    return any(needle in str(value).lower() for value in values)

                payment_entries = [entry for entry in payment_entries if _entry_matches(entry)]

        if groupby == 'none':
            payment_groups = [{'label': '', 'entries': payment_entries}]
        else:
            group_map = {}
            payment_groups = []
            for entry in payment_entries:
                payment = entry['payment']
                if groupby == 'type':
                    label = entry['type_label']
                elif groupby == 'state':
                    label = state_labels.get(payment.state, payment.state or 'Sin estado')
                else:
                    label = self._payment_date_label(payment)

                if label not in group_map:
                    group_map[label] = {'label': label, 'entries': []}
                    payment_groups.append(group_map[label])
                group_map[label]['entries'].append(entry)

        # Reutilizamos exactamente los mismos datos para la tabla y la exportación.
        return {
            'payments': payments,
            'payment_entries': payment_entries,
            'payment_groups': payment_groups,
            'payments_header_title': payments_header_title,
            'searchbar_inputs': searchbar_inputs,
            'searchbar_filters': searchbar_filters,
            'searchbar_groupby': searchbar_groupby,
            'search_in': search_in,
            'search': search,
            'groupby': groupby,
            'filterby': filterby,
        }

    @route('/my/payments', auth='user', website=True)
    def portal_my_payments(self, search=None, search_in='all', groupby='none', filterby='all', **kwargs):
        values = self._get_payment_listing_values(
            request.env.user,
            search=search,
            search_in=search_in,
            groupby=groupby,
            filterby=filterby,
        )
        values.update({
            'page_name': 'payments',  # Para breadcrumbs
            'default_url': '/my/payments',
        })
        return request.render('portal_requests.portal_my_payments', values)

    @route('/my/payments/export', auth='user', website=True)
    def portal_my_payments_export(self, search=None, search_in='all', groupby='none', filterby='all', **kwargs):
        """Exporta a CSV los pagos visibles en portal, compatible con Excel."""
        values = self._get_payment_listing_values(
            request.env.user,
            search=search,
            search_in=search_in,
            groupby=groupby,
            filterby=filterby,
        )
        state_labels = self._payment_state_labels()

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Referencia', 'Tipo', 'Fecha', 'Importe', 'Estado', 'Factura'])

        for payment_group in values['payment_groups']:
            if values['groupby'] != 'none':
                writer.writerow([f"Grupo: {payment_group['label']}", '', '', '', '', ''])
            for entry in payment_group['entries']:
                payment = entry['payment']
                writer.writerow([
                    payment.name or '',
                    entry['type_label'],
                    self._payment_date_label(payment),
                    self._payment_amount_label(payment),
                    state_labels.get(payment.state, payment.state or ''),
                    self._payment_invoice_names_label(entry['invoices']),
                ])

        filename = 'mis_pagos'
        if values['filterby'] != 'all':
            filename += f"_{values['filterby']}"
        if values['groupby'] != 'none':
            filename += f"_agrupado_{values['groupby']}"
        filename += '.csv'

        csv_content = '\ufeff' + output.getvalue()
        headers = [
            ('Content-Type', 'text/csv; charset=utf-8'),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
        ]
        return request.make_response(csv_content.encode('utf-8'), headers=headers)

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
        if not is_pdf(file_storage):
            return request.redirect(f'{target}?error=invalid_file')
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
