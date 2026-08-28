from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request, route
import base64
import csv
import io

from .portal_pdf_utils import is_pdf


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
        if invoice_request.equip_boss == user or invoice_request.administrative_id == user:
            return True
        return False

    def _get_accessible_analytic_project_domain(self, user):
        """Dominio de proyectos visibles en portal para el usuario actual.
        - Usuario normal: solo proyectos donde es responsable.
        - Jefe de equipo (y Administrativo, que implica el mismo grupo): propios
          + proyectos de grupos donde es equip_boss. El Administrativo ve la
          misma lista que el Jefe de Equipo; lo que no ve es la info económica
          (saldos/presupuestos), que se oculta en la plantilla mediante
          _hide_project_financials().
        """
        domain = [('responsible_id', '=', user.id)]
        if user.has_group('portal_requests.group_equip_boss'):
            boss_group_ids = request.env['portal.work.group'].sudo().search(
                request.env['portal.work.group']._boss_or_administrative_domain(user)
            ).ids
            if boss_group_ids:
                domain = ['|', ('responsible_id', '=', user.id), ('work_group_id', 'in', boss_group_ids)]
        return domain

    def _hide_project_financials(self, user):
        """El perfil Administrativo ve los mismos proyectos que el Jefe de
        Equipo, pero sin datos económicos (saldo/presupuesto)."""
        return user.has_group('portal_requests.group_administrative')

    def _project_request_type_label(self, project_request):
        type_labels = {
            'new': 'Nuevo Proyecto',
            'end': 'Finalizar Proyecto',
        }
        return type_labels.get(project_request.type, project_request.type or 'Sin tipo')

    def _project_request_state_label(self, project_request):
        if project_request.approved and project_request.is_revised:
            return 'Aprobada'
        if not project_request.approved and project_request.is_revised:
            return 'Rechazada'
        return 'Pendiente'

    def _project_request_date_label(self, project_request):
        return project_request.create_date.date().strftime('%d/%m/%Y') if project_request.create_date else 'Sin fecha'

    def _get_project_request_listing_values(self, user, search=None, search_in='all', groupby='none', filterby='all'):
        """Construye una única fuente de verdad para render y exportación."""
        searchbar_inputs = {
            'all': {'input': 'all', 'label': 'Buscar en todo'},
            'project_name': {'input': 'project_name', 'label': 'Solicitud'},
            'type': {'input': 'type', 'label': 'Tipo'},
            'company': {'input': 'company', 'label': 'Compañía'},
            'work_group': {'input': 'work_group', 'label': 'Grupo de Trabajo'},
            'state': {'input': 'state', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha Creación'},
        }
        if search_in not in searchbar_inputs:
            search_in = 'all'

        searchbar_filters = {
            'all': {'input': 'all', 'label': 'Todos'},
            'pending': {'input': 'pending', 'label': 'Pendiente'},
            'approved': {'input': 'approved', 'label': 'Aprobada'},
            'rejected': {'input': 'rejected', 'label': 'Rechazada'},
        }
        if filterby not in searchbar_filters:
            filterby = 'all'

        searchbar_groupby = {
            'none': {'input': 'none', 'label': 'Sin agrupar'},
            'company': {'input': 'company', 'label': 'Compañía'},
            'work_group': {'input': 'work_group', 'label': 'Grupo de Trabajo'},
            'state': {'input': 'state', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha Creación'},
        }
        if groupby not in searchbar_groupby:
            groupby = 'none'

        project_requests = request.env['portal.project.request'].search([
            ('user_id', '=', user.id)
        ], order='create_date desc')

        if filterby == 'pending':
            project_requests = project_requests.filtered(
                lambda project_request: self._project_request_state_label(project_request) == 'Pendiente'
            )
        elif filterby == 'approved':
            project_requests = project_requests.filtered(
                lambda project_request: self._project_request_state_label(project_request) == 'Aprobada'
            )
        elif filterby == 'rejected':
            project_requests = project_requests.filtered(
                lambda project_request: self._project_request_state_label(project_request) == 'Rechazada'
            )

        if search:
            needle = search.strip().lower()
            if needle:
                def _project_request_matches(project_request):
                    values = []
                    if search_in in ('all', 'project_name'):
                        values.append(project_request.project_name or '')
                    if search_in in ('all', 'type'):
                        values.append(self._project_request_type_label(project_request))
                    if search_in in ('all', 'company'):
                        values.append(project_request.company_id.name or '')
                    if search_in in ('all', 'work_group'):
                        values.append(project_request.work_group_id.name or '')
                    if search_in in ('all', 'state'):
                        values.append(self._project_request_state_label(project_request))
                    if search_in in ('all', 'date'):
                        values.append(str(project_request.create_date.date() if project_request.create_date else ''))
                        values.append(self._project_request_date_label(project_request))
                    return any(needle in str(value).lower() for value in values)

                project_requests = project_requests.filtered(_project_request_matches)

        if groupby == 'none':
            project_request_groups = [{'label': '', 'project_requests': project_requests}]
        else:
            group_map = {}
            project_request_groups = []
            for project_request in project_requests:
                if groupby == 'company':
                    label = project_request.company_id.name or 'Sin compañía'
                elif groupby == 'work_group':
                    label = project_request.work_group_id.name or 'Sin grupo de trabajo'
                elif groupby == 'state':
                    label = self._project_request_state_label(project_request)
                else:
                    label = self._project_request_date_label(project_request)

                if label not in group_map:
                    group_map[label] = {'label': label, 'project_requests': request.env['portal.project.request']}
                    project_request_groups.append(group_map[label])
                group_map[label]['project_requests'] |= project_request

        return {
            'project_requests': project_requests,
            'project_request_groups': project_request_groups,
            'searchbar_inputs': searchbar_inputs,
            'searchbar_filters': searchbar_filters,
            'searchbar_groupby': searchbar_groupby,
            'search_in': search_in,
            'search': search,
            'groupby': groupby,
            'filterby': filterby,
        }

    def _document_status_labels(self):
        DocumentApproval = request.env['document.approval']
        return dict(DocumentApproval._fields['status']._description_selection(request.env))

    def _document_status_label(self, document, status_labels=None):
        status_labels = status_labels or self._document_status_labels()
        return status_labels.get(document.status, document.status or 'Sin estado')

    def _document_date_label(self, document):
        return document.create_date.date().strftime('%d/%m/%Y') if document.create_date else 'Sin fecha'

    def _document_type_label(self, document):
        return document.type_id.name or ''

    def _get_document_listing_values(self, user, filterby=None, search=None, search_in='all', groupby='none'):
        """Construye una única fuente de verdad para render y exportación."""
        searchbar_inputs = {
            'all': {'input': 'all', 'label': 'Buscar en todo'},
            'description': {'input': 'description', 'label': 'Descripción'},
            'work_group': {'input': 'work_group', 'label': 'Grupo de Trabajo'},
            'status': {'input': 'status', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha Creación'},
        }
        if search_in not in searchbar_inputs:
            search_in = 'all'

        searchbar_groupby = {
            'none': {'input': 'none', 'label': 'Sin agrupar'},
            'work_group': {'input': 'work_group', 'label': 'Grupo de Trabajo'},
            'status': {'input': 'status', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha Creación'},
        }
        if groupby not in searchbar_groupby:
            groupby = 'none'

        status_labels = self._document_status_labels()

        searchbar_filters = {
            'all': {'input': 'all', 'label': 'Todos'},
        }
        for status_key, status_label in status_labels.items():
            searchbar_filters[status_key] = {
                'input': status_key,
                'label': status_label,
            }
        if filterby not in searchbar_filters:
            filterby = 'all'

        if user.has_group('portal_requests.group_equip_boss'):
            boss_groups = request.env['portal.work.group'].sudo().search(
                request.env['portal.work.group']._boss_or_administrative_domain(user)
            )
            member_ids = boss_groups.mapped('user_ids').ids
            documents = request.env['document.approval'].sudo().search([
                ('user_id', 'in', member_ids + [user.id])
            ], order='create_date desc')
        else:
            documents = request.env['document.approval'].search([
                ('user_id', '=', user.id)
            ], order='create_date desc')

        if filterby != 'all':
            documents = documents.filtered(lambda document: document.status == filterby)

        if search:
            needle = search.strip().lower()
            if needle:
                def _document_matches(document):
                    values = []
                    if search_in in ('all', 'description'):
                        values.append(document.description or '')
                    if search_in in ('all', 'work_group'):
                        values.append(document.work_group_id.name or '')
                    if search_in in ('all', 'status'):
                        values.append(self._document_status_label(document, status_labels))
                        values.append(document.status or '')
                    if search_in in ('all', 'date'):
                        values.append(str(document.create_date.date() if document.create_date else ''))
                        values.append(self._document_date_label(document))
                    return any(needle in str(value).lower() for value in values)

                documents = documents.filtered(_document_matches)

        if groupby == 'none':
            document_groups = [{'label': '', 'documents': documents}]
        else:
            group_map = {}
            document_groups = []
            for document in documents:
                if groupby == 'work_group':
                    label = document.work_group_id.name or 'Sin grupo de trabajo'
                elif groupby == 'status':
                    label = self._document_status_label(document, status_labels)
                else:
                    label = self._document_date_label(document)

                if label not in group_map:
                    group_map[label] = {'label': label, 'documents': documents.browse()}
                    document_groups.append(group_map[label])
                group_map[label]['documents'] |= document

        return {
            'documents': documents,
            'document_groups': document_groups,
            'searchbar_inputs': searchbar_inputs,
            'searchbar_filters': searchbar_filters,
            'searchbar_groupby': searchbar_groupby,
            'search_in': search_in,
            'search': search,
            'groupby': groupby,
            'filterby': filterby,
        }

    def _invoice_request_status_labels(self):
        InvoiceRequest = request.env['portal.invoice.request'].sudo()
        return dict(InvoiceRequest._fields['status']._description_selection(request.env))

    def _invoice_request_type_label(self, invoice_request):
        type_labels = {
            'out_invoice': 'Factura',
            'out_refund': 'Factura Rectificativa',
        }
        return type_labels.get(invoice_request.move_type, invoice_request.move_type or 'Sin tipo')

    def _invoice_request_status_label(self, invoice_request, status_labels=None):
        status_labels = status_labels or self._invoice_request_status_labels()
        return status_labels.get(invoice_request.status, invoice_request.status or 'Sin estado')

    def _invoice_request_date_label(self, invoice_request):
        return invoice_request.create_date.date().strftime('%d/%m/%Y') if invoice_request.create_date else 'Sin fecha'

    def _invoice_request_project_label(self, invoice_request):
        project = invoice_request.analytic_id.sudo()
        return (project.display_name or project.name or 'Sin proyecto') if project else 'Sin proyecto'

    def _invoice_request_amount_search_values(self, invoice_request):
        amount = invoice_request.amount or 0.0
        fixed_amount = f'{amount:.2f}'
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        values = [str(amount), fixed_amount, fixed_amount.replace('.', ','), spanish_amount, f'{spanish_amount} €']
        if float(amount).is_integer():
            values.append(str(int(amount)))
        return values

    def _invoice_request_amount_label(self, invoice_request):
        amount = invoice_request.amount or 0.0
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        currency = invoice_request.currency_id
        symbol = currency.symbol if currency and currency.symbol else '€'
        return f'{spanish_amount} {symbol}'

    def _get_invoice_request_listing_values(self, user, filterby=None, search=None, search_in='all', groupby='none'):
        """Construye una única fuente de verdad para render y exportación."""
        searchbar_inputs = {
            'all': {'input': 'all', 'label': 'Buscar en todo'},
            'type': {'input': 'type', 'label': 'Tipo'},
            'partner': {'input': 'partner', 'label': 'Cliente'},
            'project': {'input': 'project', 'label': 'Proyecto'},
            'amount': {'input': 'amount', 'label': 'Importe'},
            'status': {'input': 'status', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha Creación'},
        }
        if search_in not in searchbar_inputs:
            search_in = 'all'

        status_labels = self._invoice_request_status_labels()

        searchbar_filters = {
            'all': {'input': 'all', 'label': 'Todos'},
        }
        for status_key, status_label in status_labels.items():
            searchbar_filters[status_key] = {
                'input': status_key,
                'label': status_label,
            }
        if filterby not in searchbar_filters:
            filterby = 'all'

        searchbar_groupby = {
            'none': {'input': 'none', 'label': 'Sin agrupar'},
            'type': {'input': 'type', 'label': 'Tipo'},
            'partner': {'input': 'partner', 'label': 'Cliente'},
            'project': {'input': 'project', 'label': 'Proyecto'},
            'status': {'input': 'status', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha Creación'},
        }
        if groupby not in searchbar_groupby:
            groupby = 'none'

        InvoiceRequest = request.env['portal.invoice.request'].sudo()
        invoice_requests = InvoiceRequest.search([
            '|', '|',
            ('user_id', '=', user.id),
            ('equip_boss', '=', user.id),
            ('administrative_id', '=', user.id),
        ], order='create_date desc')

        if filterby != 'all':
            invoice_requests = invoice_requests.filtered(lambda invoice_request: invoice_request.status == filterby)

        if search:
            needle = search.strip().lower()
            if needle:
                def _invoice_request_matches(invoice_request):
                    values = []
                    if search_in in ('all', 'type'):
                        values.append(self._invoice_request_type_label(invoice_request))
                    if search_in in ('all', 'partner'):
                        values.append(invoice_request.partner_id.name or '')
                    if search_in in ('all', 'project'):
                        values.append(self._invoice_request_project_label(invoice_request))
                    if search_in in ('all', 'amount'):
                        values.extend(self._invoice_request_amount_search_values(invoice_request))
                    if search_in in ('all', 'status'):
                        values.append(self._invoice_request_status_label(invoice_request, status_labels))
                        values.append(invoice_request.status or '')
                    if search_in in ('all', 'date'):
                        values.append(str(invoice_request.create_date.date() if invoice_request.create_date else ''))
                        values.append(self._invoice_request_date_label(invoice_request))
                    return any(needle in str(value).lower() for value in values)

                invoice_requests = invoice_requests.filtered(_invoice_request_matches)

        if groupby == 'none':
            invoice_request_groups = [{'label': '', 'invoice_requests': invoice_requests}]
        else:
            group_map = {}
            invoice_request_groups = []
            for invoice_request in invoice_requests:
                if groupby == 'type':
                    label = self._invoice_request_type_label(invoice_request)
                elif groupby == 'partner':
                    label = invoice_request.partner_id.name or 'Sin cliente'
                elif groupby == 'project':
                    label = self._invoice_request_project_label(invoice_request)
                elif groupby == 'status':
                    label = self._invoice_request_status_label(invoice_request, status_labels)
                else:
                    label = self._invoice_request_date_label(invoice_request)

                if label not in group_map:
                    group_map[label] = {'label': label, 'invoice_requests': InvoiceRequest.browse()}
                    invoice_request_groups.append(group_map[label])
                group_map[label]['invoice_requests'] |= invoice_request

        return {
            'invoice_requests': invoice_requests,
            'invoice_request_groups': invoice_request_groups,
            'searchbar_inputs': searchbar_inputs,
            'searchbar_filters': searchbar_filters,
            'searchbar_groupby': searchbar_groupby,
            'search_in': search_in,
            'search': search,
            'groupby': groupby,
            'filterby': filterby,
        }

    def _expense_type_labels(self):
        ExpenseRequest = request.env['portal.hr.expensive.request']
        return dict(ExpenseRequest._fields['type']._description_selection(request.env))

    def _expense_status_labels(self):
        ExpenseRequest = request.env['portal.hr.expensive.request']
        return dict(ExpenseRequest._fields['status']._description_selection(request.env))

    def _expense_type_label(self, expense, type_labels=None):
        type_labels = type_labels or self._expense_type_labels()
        return type_labels.get(expense.type, expense.type or 'Sin tipo')

    def _expense_status_label(self, expense, status_labels=None):
        status_labels = status_labels or self._expense_status_labels()
        return status_labels.get(expense.status, expense.status or 'Sin estado')

    def _expense_date_label(self, expense):
        return expense.create_date.date().strftime('%d/%m/%Y') if expense.create_date else 'Sin fecha'

    def _expense_project_label(self, expense):
        project = expense.project.sudo()
        return project.name if project else 'Sin proyecto'

    def _expense_amount_search_values(self, expense):
        if not expense.invoice_created:
            return []
        amount = expense.invoice_created.sudo().amount_total or 0.0
        fixed_amount = f'{amount:.2f}'
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        values = [str(amount), fixed_amount, fixed_amount.replace('.', ','), spanish_amount, f'{spanish_amount} €']
        if float(amount).is_integer():
            values.append(str(int(amount)))
        return values

    def _expense_amount_label(self, expense):
        if not expense.invoice_created:
            return ''
        amount = expense.invoice_created.sudo().amount_total or 0.0
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        currency = expense.invoice_created.sudo().currency_id
        symbol = currency.symbol if currency and currency.symbol else '€'
        return f'{spanish_amount} {symbol}'

    def _get_expense_listing_values(self, user, filterby=None, search=None, search_in='all', groupby='none'):
        """Construye una única fuente de verdad para render y exportación."""
        searchbar_inputs = {
            'all': {'input': 'all', 'label': 'Buscar en todo'},
            'type': {'input': 'type', 'label': 'Tipo'},
            'project': {'input': 'project', 'label': 'Proyecto'},
            'amount': {'input': 'amount', 'label': 'Importe'},
            'status': {'input': 'status', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha Creación'},
        }
        if search_in not in searchbar_inputs:
            search_in = 'all'

        searchbar_groupby = {
            'none': {'input': 'none', 'label': 'Sin agrupar'},
            'type': {'input': 'type', 'label': 'Tipo'},
            'project': {'input': 'project', 'label': 'Proyecto'},
            'status': {'input': 'status', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha Creación'},
        }
        if groupby not in searchbar_groupby:
            groupby = 'none'

        type_labels = self._expense_type_labels()
        status_labels = self._expense_status_labels()

        searchbar_filters = {
            'all': {'input': 'all', 'label': 'Todos'},
        }
        for status_key, status_label in status_labels.items():
            searchbar_filters[status_key] = {
                'input': status_key,
                'label': status_label,
            }
        if filterby not in searchbar_filters:
            filterby = 'all'

        expenses = request.env['portal.hr.expensive.request'].search([
            ('user_id', '=', user.id)
        ], order='create_date desc')

        if filterby != 'all':
            expenses = expenses.filtered(lambda expense: expense.status == filterby)

        if search:
            needle = search.strip().lower()
            if needle:
                def _expense_matches(expense):
                    values = []
                    if search_in in ('all', 'type'):
                        values.append(self._expense_type_label(expense, type_labels))
                    if search_in in ('all', 'project'):
                        values.append(self._expense_project_label(expense))
                    if search_in in ('all', 'amount'):
                        values.extend(self._expense_amount_search_values(expense))
                    if search_in in ('all', 'status'):
                        values.append(self._expense_status_label(expense, status_labels))
                        values.append(expense.status or '')
                    if search_in in ('all', 'date'):
                        values.append(str(expense.create_date.date() if expense.create_date else ''))
                        values.append(self._expense_date_label(expense))
                    return any(needle in str(value).lower() for value in values)

                expenses = expenses.filtered(_expense_matches)

        if groupby == 'none':
            expense_groups = [{'label': '', 'expenses': expenses}]
        else:
            group_map = {}
            expense_groups = []
            for expense in expenses:
                if groupby == 'type':
                    label = self._expense_type_label(expense, type_labels)
                elif groupby == 'project':
                    label = self._expense_project_label(expense)
                elif groupby == 'status':
                    label = self._expense_status_label(expense, status_labels)
                else:
                    label = self._expense_date_label(expense)

                if label not in group_map:
                    group_map[label] = {'label': label, 'expenses': request.env['portal.hr.expensive.request']}
                    expense_groups.append(group_map[label])
                group_map[label]['expenses'] |= expense

        return {
            'expenses': expenses,
            'expense_groups': expense_groups,
            'expense_project_names': {
                expense.id: self._expense_project_label(expense)
                for expense in expenses
            },
            'searchbar_inputs': searchbar_inputs,
            'searchbar_filters': searchbar_filters,
            'searchbar_groupby': searchbar_groupby,
            'search_in': search_in,
            'search': search,
            'groupby': groupby,
            'filterby': filterby,
        }

    def _analytic_project_state_label(self, project):
        return 'Activo' if project.active else 'Inactivo'

    def _analytic_project_balance_label(self, project):
        amount = project.balance or 0.0
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        currency = project.currency_id
        symbol = currency.symbol if currency and currency.symbol else '€'
        return f'{spanish_amount} {symbol}'

    def _get_analytic_project_listing_values(self, user, search=None, search_in='all', groupby='none'):
        """Construye una única fuente de verdad para render y exportación."""
        searchbar_inputs = {
            'all': {'input': 'all', 'label': 'Buscar en todo'},
            'name': {'input': 'name', 'label': 'Nombre del Proyecto'},
            'partner': {'input': 'partner', 'label': 'Cliente'},
            'responsible': {'input': 'responsible', 'label': 'Responsable'},
            'work_group': {'input': 'work_group', 'label': 'Grupo de Trabajo'},
        }
        if search_in not in searchbar_inputs:
            search_in = 'all'

        searchbar_groupby = {
            'none': {'input': 'none', 'label': 'Sin agrupar'},
            'partner': {'input': 'partner', 'label': 'Cliente'},
            'responsible': {'input': 'responsible', 'label': 'Responsable'},
            'work_group': {'input': 'work_group', 'label': 'Grupo de Trabajo'},
            'state': {'input': 'state', 'label': 'Estado'},
        }
        if groupby not in searchbar_groupby:
            groupby = 'none'

        domain = self._get_accessible_analytic_project_domain(user)
        if search:
            if search_in == 'name':
                domain += [('name', 'ilike', search)]
            elif search_in == 'partner':
                domain += [('partner_id.name', 'ilike', search)]
            elif search_in == 'responsible':
                domain += [('responsible_id.name', 'ilike', search)]
            elif search_in == 'work_group':
                domain += [('work_group_id.name', 'ilike', search)]
            else:
                domain += [
                    '|', '|', '|',
                    ('name', 'ilike', search),
                    ('partner_id.name', 'ilike', search),
                    ('responsible_id.name', 'ilike', search),
                    ('work_group_id.name', 'ilike', search),
                ]

        projects = request.env['account.analytic.account'].search(
            domain,
            order='name asc'
        )

        projects_sudo = projects.sudo()
        if groupby == 'none':
            project_groups = [{'label': '', 'projects': projects_sudo}]
        else:
            group_map = {}
            project_groups = []
            for project in projects_sudo:
                if groupby == 'partner':
                    label = project.partner_id.name or 'Sin cliente'
                elif groupby == 'responsible':
                    label = project.responsible_id.name or 'Sin responsable'
                elif groupby == 'work_group':
                    label = project.work_group_id.name or 'Sin grupo de trabajo'
                else:
                    label = self._analytic_project_state_label(project)

                if label not in group_map:
                    group_map[label] = {'label': label, 'projects': request.env['account.analytic.account'].sudo()}
                    project_groups.append(group_map[label])
                group_map[label]['projects'] |= project

        return {
            'projects': projects_sudo,
            'project_groups': project_groups,
            'searchbar_inputs': searchbar_inputs,
            'searchbar_groupby': searchbar_groupby,
            'search_in': search_in,
            'search': search,
            'groupby': groupby,
            'hide_financials': self._hide_project_financials(user),
        }

    def _project_invoice_type_labels(self):
        return {
            'out_invoice': 'Factura Cliente',
            'out_refund': 'Nota Crédito Cliente',
            'in_invoice': 'Factura Proveedor',
            'in_refund': 'Nota Crédito Proveedor',
        }

    def _project_invoice_state_labels(self):
        return {
            'draft': 'Borrador',
            'posted': 'Publicada',
            'cancel': 'Cancelada',
        }

    def _project_invoice_payment_state_labels(self):
        return {
            'paid': 'Pagada',
            'partial': 'Pago Parcial',
            'not_paid': 'No Pagada',
            'in_payment': 'En pago',
            'reversed': 'Revertida',
            'blocked': 'Bloqueada',
            'invoicing_legacy': 'Sistema anterior',
        }

    def _project_invoice_date_value(self, invoice):
        return invoice.invoice_date or invoice.date or (invoice.create_date.date() if invoice.create_date else False)

    def _project_invoice_date_label(self, invoice):
        invoice_date = self._project_invoice_date_value(invoice)
        return invoice_date.strftime('%d/%m/%Y') if invoice_date else 'Sin fecha'

    def _project_invoice_amount_search_values(self, invoice):
        amount = invoice.amount_total or 0.0
        fixed_amount = f'{amount:.2f}'
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        values = [str(amount), fixed_amount, fixed_amount.replace('.', ','), spanish_amount, f'{spanish_amount} €']
        if float(amount).is_integer():
            values.append(str(int(amount)))
        return values

    def _project_invoice_amount_label(self, invoice):
        amount = invoice.amount_total or 0.0
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        currency = invoice.currency_id
        symbol = currency.symbol if currency and currency.symbol else '€'
        return f'{spanish_amount} {symbol}'

    def _get_project_invoice_listing_values(self, project, search=None, search_in='all', groupby='none', filterby='all'):
        """Construye una única fuente de verdad para render y exportación de facturas de proyecto."""
        invoice_lines = request.env['account.move.line'].sudo().search([
            ('analytic_distribution', '!=', False),
            ('move_id.move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']),
            ('move_id.state', '!=', 'cancel')
        ])

        invoice_ids = set()
        for line in invoice_lines:
            if line.analytic_distribution:
                for key in line.analytic_distribution.keys():
                    analytic_ids = [int(id_str) for id_str in key.split(',')]
                    if project.id in analytic_ids:
                        invoice_ids.add(line.move_id.id)
                        break

        searchbar_inputs = {
            'all': {'input': 'all', 'label': 'Buscar en todo'},
            'name': {'input': 'name', 'label': 'Número'},
            'partner': {'input': 'partner', 'label': 'Cliente/Proveedor'},
            'type': {'input': 'type', 'label': 'Tipo'},
            'date': {'input': 'date', 'label': 'Fecha'},
            'amount': {'input': 'amount', 'label': 'Importe Total'},
            'state': {'input': 'state', 'label': 'Estado'},
            'payment_state': {'input': 'payment_state', 'label': 'Estado de pago'},
        }
        if search_in not in searchbar_inputs:
            search_in = 'all'

        searchbar_filters = {
            'all': {'input': 'all', 'label': 'Todos'},
            'customer': {'input': 'customer', 'label': 'Facturas de cliente'},
            'supplier': {'input': 'supplier', 'label': 'Facturas de proveedores'},
        }
        if filterby not in searchbar_filters:
            filterby = 'all'

        searchbar_groupby = {
            'none': {'input': 'none', 'label': 'Sin agrupar'},
            'type': {'input': 'type', 'label': 'Tipo'},
            'partner': {'input': 'partner', 'label': 'Cliente/Proveedor'},
            'date': {'input': 'date', 'label': 'Fecha'},
            'state': {'input': 'state', 'label': 'Estado'},
            'payment_state': {'input': 'payment_state', 'label': 'Estado de pago'},
        }
        if groupby not in searchbar_groupby:
            groupby = 'none'

        type_labels = self._project_invoice_type_labels()
        state_labels = self._project_invoice_state_labels()
        payment_state_labels = self._project_invoice_payment_state_labels()

        invoices = request.env['account.move'].sudo().browse(list(invoice_ids)).sorted(
            lambda inv: (str(inv.invoice_date or inv.date or inv.create_date or ''), inv.name or ''),
            reverse=True,
        )
        if filterby == 'customer':
            invoices = invoices.filtered(lambda inv: inv.move_type in ('out_invoice', 'out_refund'))
        elif filterby == 'supplier':
            invoices = invoices.filtered(lambda inv: inv.move_type in ('in_invoice', 'in_refund'))

        if search:
            needle = search.strip().lower()
            if needle:
                def _invoice_matches(inv):
                    values = []
                    if search_in in ('all', 'name'):
                        values.append(inv.name or '')
                    if search_in in ('all', 'partner'):
                        values.append(inv.partner_id.name or '')
                    if search_in in ('all', 'type'):
                        values.append(type_labels.get(inv.move_type, inv.move_type or ''))
                    if search_in in ('all', 'date'):
                        values.append(str(self._project_invoice_date_value(inv) or ''))
                        values.append(self._project_invoice_date_label(inv))
                    if search_in in ('all', 'amount'):
                        values.extend(self._project_invoice_amount_search_values(inv))
                    if search_in in ('all', 'state'):
                        values.append(state_labels.get(inv.state, inv.state or ''))
                    if search_in in ('all', 'payment_state'):
                        values.append(payment_state_labels.get(inv.payment_state, inv.payment_state or ''))
                    return any(needle in str(value).lower() for value in values)

                invoices = invoices.filtered(_invoice_matches)

        if groupby == 'none':
            invoice_groups = [{'label': '', 'invoices': invoices}]
        else:
            group_map = {}
            invoice_groups = []
            for invoice in invoices:
                if groupby == 'type':
                    label = type_labels.get(invoice.move_type, invoice.move_type or 'Sin tipo')
                elif groupby == 'partner':
                    label = invoice.partner_id.name or 'Sin cliente/proveedor'
                elif groupby == 'date':
                    label = self._project_invoice_date_label(invoice)
                elif groupby == 'state':
                    label = state_labels.get(invoice.state, invoice.state or 'Sin estado')
                else:
                    label = payment_state_labels.get(invoice.payment_state, invoice.payment_state or 'Sin estado de pago')

                if label not in group_map:
                    group_map[label] = {'label': label, 'invoices': request.env['account.move'].sudo()}
                    invoice_groups.append(group_map[label])
                group_map[label]['invoices'] |= invoice

        return {
            'project': project.sudo(),
            'invoices': invoices,
            'invoice_groups': invoice_groups,
            'searchbar_inputs': searchbar_inputs,
            'searchbar_filters': searchbar_filters,
            'searchbar_groupby': searchbar_groupby,
            'search_in': search_in,
            'search': search,
            'groupby': groupby,
            'filterby': filterby,
        }

    def _project_associated_payment_state_labels(self):
        return {
            'draft': 'Borrador',
            'in_process': 'En proceso',
            'paid': 'Pagado',
            'posted': 'Publicado',
            'cancel': 'Cancelado',
            'cancelled': 'Cancelado',
        }

    def _project_associated_payment_date_value(self, payment):
        return payment.date or (payment.create_date.date() if payment.create_date else False)

    def _project_associated_payment_date_label(self, payment):
        payment_date = self._project_associated_payment_date_value(payment)
        return payment_date.strftime('%d/%m/%Y') if payment_date else 'Sin fecha'

    def _project_associated_payment_amount_search_values(self, payment):
        amount = payment.amount or 0.0
        fixed_amount = f'{amount:.2f}'
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        values = [str(amount), fixed_amount, fixed_amount.replace('.', ','), spanish_amount, f'{spanish_amount} €']
        if float(amount).is_integer():
            values.append(str(int(amount)))
        return values

    def _project_associated_payment_amount_label(self, payment):
        amount = payment.amount or 0.0
        spanish_amount = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        currency = payment.currency_id
        symbol = currency.symbol if currency and currency.symbol else '€'
        return f'{spanish_amount} {symbol}'

    def _get_project_invoice_payment_listing_values(self, project, invoice, search=None, search_in='all', groupby='none', filterby='all'):
        """Construye una única fuente de verdad para render y exportación de pagos asociados."""
        searchbar_inputs = {
            'all': {'input': 'all', 'label': 'Buscar en todo'},
            'name': {'input': 'name', 'label': 'Referencia'},
            'date': {'input': 'date', 'label': 'Fecha'},
            'amount': {'input': 'amount', 'label': 'Importe'},
            'state': {'input': 'state', 'label': 'Estado'},
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

        searchbar_groupby = {
            'none': {'input': 'none', 'label': 'Sin agrupar'},
            'state': {'input': 'state', 'label': 'Estado'},
            'date': {'input': 'date', 'label': 'Fecha'},
        }
        if groupby not in searchbar_groupby:
            groupby = 'none'

        state_labels = self._project_associated_payment_state_labels()
        payments = request.env['account.payment'].sudo().search([
            ('invoice_ids', 'in', [invoice.id]),
        ], order='date desc, name desc')

        invoice_is_customer = invoice.move_type in ('out_invoice', 'out_refund')
        invoice_is_supplier = invoice.move_type in ('in_invoice', 'in_refund')

        if filterby == 'customer' and not invoice_is_customer:
            payments = payments.browse()
        elif filterby == 'supplier' and not invoice_is_supplier:
            payments = payments.browse()

        if search:
            needle = search.strip().lower()
            if needle:
                def _payment_matches(payment):
                    values = []
                    if search_in in ('all', 'name'):
                        values.append(payment.name or '')
                    if search_in in ('all', 'date'):
                        values.append(str(self._project_associated_payment_date_value(payment) or ''))
                        values.append(self._project_associated_payment_date_label(payment))
                    if search_in in ('all', 'amount'):
                        values.extend(self._project_associated_payment_amount_search_values(payment))
                    if search_in in ('all', 'state'):
                        values.append(state_labels.get(payment.state, payment.state or ''))
                    return any(needle in str(value).lower() for value in values)

                payments = payments.filtered(_payment_matches)

        if groupby == 'none':
            payment_groups = [{'label': '', 'payments': payments}]
        else:
            group_map = {}
            payment_groups = []
            for payment in payments:
                if groupby == 'state':
                    label = state_labels.get(payment.state, payment.state or 'Sin estado')
                else:
                    label = self._project_associated_payment_date_label(payment)

                if label not in group_map:
                    group_map[label] = {'label': label, 'payments': request.env['account.payment'].sudo()}
                    payment_groups.append(group_map[label])
                group_map[label]['payments'] |= payment

        # Reutilizamos exactamente los mismos valores para render y exportación.
        return {
            'project': project.sudo(),
            'invoice': invoice,
            'payments': payments,
            'payment_groups': payment_groups,
            'searchbar_inputs': searchbar_inputs,
            'searchbar_groupby': searchbar_groupby,
            'searchbar_filters': searchbar_filters,
            'search_in': search_in,
            'search': search,
            'groupby': groupby,
            'filterby': filterby,
        }

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
    def portal_my_expenses(self, page=1, sortby=None, filterby=None, search=None, search_in='all', groupby='none', **kw):
        """Muestra el listado de solicitudes de gastos del usuario"""
        values = self._get_expense_listing_values(
            request.env.user,
            filterby=filterby,
            search=search,
            search_in=search_in,
            groupby=groupby,
        )
        values.update({
            'page_name': 'expense',
            'default_url': '/my/expenses',
        })

        return request.render("portal_requests.portal_my_expenses", values)

    @http.route(['/my/expenses/export'], type='http', auth="user", website=True)
    def portal_my_expenses_export(self, filterby=None, search=None, search_in='all', groupby='none', **kw):
        """Exporta a CSV las solicitudes visibles en portal, compatible con Excel."""
        values = self._get_expense_listing_values(
            request.env.user,
            filterby=filterby,
            search=search,
            search_in=search_in,
            groupby=groupby,
        )

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Tipo', 'Proyecto', 'Importe', 'Estado', 'Fecha de Creación'])

        type_labels = self._expense_type_labels()
        status_labels = self._expense_status_labels()

        for expense_group in values['expense_groups']:
            if values['groupby'] != 'none':
                writer.writerow([f"Grupo: {expense_group['label']}", '', '', '', ''])
            for expense in expense_group['expenses']:
                writer.writerow([
                    self._expense_type_label(expense, type_labels),
                    self._expense_project_label(expense),
                    self._expense_amount_label(expense),
                    self._expense_status_label(expense, status_labels),
                    self._expense_date_label(expense),
                ])

        filename = 'solicitudes_gastos'
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
    def portal_my_invoices(self, page=1, sortby=None, filterby=None, search=None, search_in='all', groupby='none', **kw):
        """Muestra el listado de solicitudes de facturas del usuario"""
        values = self._get_invoice_request_listing_values(
            request.env.user,
            filterby=filterby,
            search=search,
            search_in=search_in,
            groupby=groupby,
        )
        values.update({
            'page_name': 'invoice_request',
            'default_url': '/my/invoices',
        })

        return request.render("portal_requests.portal_my_invoices", values)

    @http.route(['/my/invoices/export'], type='http', auth="user", website=True)
    def portal_my_invoices_export(self, filterby=None, search=None, search_in='all', groupby='none', **kw):
        """Exporta a CSV las solicitudes visibles en portal, compatible con Excel."""
        values = self._get_invoice_request_listing_values(
            request.env.user,
            filterby=filterby,
            search=search,
            search_in=search_in,
            groupby=groupby,
        )

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Tipo', 'Cliente', 'Proyecto', 'Importe', 'Estado', 'Fecha de Creación'])

        status_labels = self._invoice_request_status_labels()

        for invoice_request_group in values['invoice_request_groups']:
            if values['groupby'] != 'none':
                writer.writerow([f"Grupo: {invoice_request_group['label']}", '', '', '', '', ''])
            for invoice_request in invoice_request_group['invoice_requests']:
                writer.writerow([
                    self._invoice_request_type_label(invoice_request),
                    invoice_request.partner_id.name or '',
                    self._invoice_request_project_label(invoice_request),
                    self._invoice_request_amount_label(invoice_request),
                    self._invoice_request_status_label(invoice_request, status_labels),
                    self._invoice_request_date_label(invoice_request),
                ])

        filename = 'solicitudes_facturas'
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
    def portal_my_documents(self, page=1, sortby=None, filterby=None, search=None, search_in='all', groupby='none', **kw):
        """Muestra el listado de solicitudes de documentos del usuario.
        Si es jefe de equipo, también ve las solicitudes de los grupos que lidera."""
        values = self._get_document_listing_values(
            request.env.user,
            filterby=filterby,
            search=search,
            search_in=search_in,
            groupby=groupby,
        )
        values.update({
            'page_name': 'document_approval',
            'default_url': '/my/documents',
        })

        return request.render("portal_requests.portal_my_documents", values)

    @http.route(['/my/documents/export'], type='http', auth="user", website=True)
    def portal_my_documents_export(self, filterby=None, search=None, search_in='all', groupby='none', **kw):
        """Exporta a CSV las solicitudes visibles en portal, compatible con Excel."""
        values = self._get_document_listing_values(
            request.env.user,
            filterby=filterby,
            search=search,
            search_in=search_in,
            groupby=groupby,
        )

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Tipo', 'Descripción', 'Grupo de Trabajo', 'Estado', 'Fecha de Creación'])

        status_labels = self._document_status_labels()

        for document_group in values['document_groups']:
            if values['groupby'] != 'none':
                writer.writerow([f"Grupo: {document_group['label']}", '', '', '', ''])
            for document in document_group['documents']:
                writer.writerow([
                    self._document_type_label(document),
                    document.description or '',
                    document.work_group_id.name or '',
                    self._document_status_label(document, status_labels),
                    self._document_date_label(document),
                ])

        filename = 'solicitudes_documentos'
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

    @http.route(['/my/documents/<int:document_id>'], type='http', auth="user", website=True)
    def portal_my_document_detail(self, document_id, success=None, **kw):
        """Muestra el detalle de una solicitud de documento"""
        user = request.env.user
        document = request.env['document.approval'].sudo().browse(document_id)

        # Verificar acceso: el creador O el jefe de equipo del grupo de trabajo
        is_owner = document.user_id == user
        is_boss_of_group = False
        if user.has_group('portal_requests.group_equip_boss') and document.work_group_id:
            is_boss_of_group = document.work_group_id._is_boss_or_administrative(user)

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
            'is_owner': is_owner,
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
            is_boss_of_group = document.work_group_id._is_boss_or_administrative(user)

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
            is_boss_of_group = document.work_group_id._is_boss_or_administrative(user)

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
        is_boss_of_group = user.has_group('portal_requests.group_equip_boss') and document.work_group_id and document.work_group_id._is_boss_or_administrative(user)
        if not is_owner and not is_boss_of_group:
            return request.redirect('/my')
        file_storage = request.httprequest.files.get('attachment')
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/documents/{document_id}')
        if not is_pdf(file_storage):
            return request.redirect(f'/my/documents/{document_id}?error=invalid_file')
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

    @http.route(['/my/documents/<int:document_id>/resubmit'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_document_resubmit(self, document_id, **post):
        """Permite al solicitante subir una nueva versión de un documento
        rechazado y reenviar la solicitud dentro del mismo flujo."""
        user = request.env.user
        document = request.env['document.approval'].sudo().browse(document_id)
        if not document.exists() or document.user_id != user:
            return request.redirect('/my')
        if document.status != 'rejected':
            return request.redirect(f'/my/documents/{document_id}')
        file_storage = request.httprequest.files.get('attachment')
        if not file_storage or not hasattr(file_storage, 'filename'):
            return request.redirect(f'/my/documents/{document_id}?error=missing_file')
        if not is_pdf(file_storage):
            return request.redirect(f'/my/documents/{document_id}?error=invalid_file')
        file_data = file_storage.read()
        if not file_data:
            return request.redirect(f'/my/documents/{document_id}?error=missing_file')
        request.env['ir.attachment'].sudo().create({
            'name': file_storage.filename,
            'datas': base64.b64encode(file_data),
            'res_model': 'document.approval',
            'res_id': document.id,
            'type': 'binary',
            'mimetype': file_storage.content_type or 'application/pdf',
        })
        document.action_resubmit()
        return request.redirect(f'/my/documents/{document_id}?success=resubmitted')

    # ==========================================
    # Rutas para Proyectos (Cuentas Analíticas)
    # ==========================================

    @http.route(['/my/analytic_projects', '/my/analytic_projects/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_projects(self, page=1, sortby=None, filterby=None, search=None, search_in='all', groupby='none', **kw):
        """Muestra el listado de proyectos visibles para el usuario portal."""
        values = self._get_analytic_project_listing_values(
            request.env.user,
            search=search,
            search_in=search_in,
            groupby=groupby,
        )
        values.update({
            'page_name': 'analytic_project',
            'default_url': '/my/analytic_projects',
        })

        return request.render("portal_requests.portal_my_projects", values)

    @http.route(['/my/analytic_projects/export'], type='http', auth="user", website=True)
    def portal_my_projects_export(self, search=None, search_in='all', groupby='none', **kw):
        """Exporta a CSV los proyectos visibles en portal, compatible con Excel."""
        values = self._get_analytic_project_listing_values(
            request.env.user,
            search=search,
            search_in=search_in,
            groupby=groupby,
        )

        hide_financials = values['hide_financials']
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        header = ['Nombre del Proyecto', 'Cliente']
        if not hide_financials:
            header.append('Saldo')
        header.append('Estado')
        writer.writerow(header)

        for project_group in values['project_groups']:
            if values['groupby'] != 'none':
                writer.writerow([f"Grupo: {project_group['label']}", ''] + ([''] if not hide_financials else []) + [''])
            for project in project_group['projects']:
                row = [project.name or '', project.partner_id.name or '']
                if not hide_financials:
                    row.append(self._analytic_project_balance_label(project))
                row.append(self._analytic_project_state_label(project))
                writer.writerow(row)

        filename = 'mis_proyectos'
        if values['groupby'] != 'none':
            filename += f"_agrupado_{values['groupby']}"
        filename += '.csv'

        csv_content = '\ufeff' + output.getvalue()
        headers = [
            ('Content-Type', 'text/csv; charset=utf-8'),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
        ]
        return request.make_response(csv_content.encode('utf-8'), headers=headers)

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
            'hide_financials': self._hide_project_financials(request.env.user),
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
    def portal_project_invoices(self, project_id, search=None, search_in='all', groupby='none', filterby='all', **kw):
        """Muestra las facturas asociadas a un proyecto (cuenta analítica)"""
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )
        if not project:
            return request.redirect('/my')
        values = self._get_project_invoice_listing_values(
            project,
            search=search,
            search_in=search_in,
            groupby=groupby,
            filterby=filterby,
        )
        values.update({
            'page_name': 'analytic_project_invoices',
            'default_url': f'/my/analytic_projects/{project_id}/invoices_list',
        })

        return request.render("portal_requests.portal_project_invoices", values)

    @http.route(['/my/analytic_projects/<int:project_id>/invoices_list/export'], type='http', auth="user", website=True)
    def portal_project_invoices_export(self, project_id, search=None, search_in='all', groupby='none', filterby='all', **kw):
        """Exporta a CSV las facturas visibles del proyecto, compatible con Excel."""
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )
        if not project:
            return request.redirect('/my')

        values = self._get_project_invoice_listing_values(
            project,
            search=search,
            search_in=search_in,
            groupby=groupby,
            filterby=filterby,
        )

        type_labels = self._project_invoice_type_labels()
        state_labels = self._project_invoice_state_labels()
        payment_state_labels = self._project_invoice_payment_state_labels()

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Número', 'Tipo', 'Cliente/Proveedor', 'Fecha', 'Importe Total', 'Estado', 'Estado de pago'])

        for invoice_group in values['invoice_groups']:
            if values['groupby'] != 'none':
                writer.writerow([f"Grupo: {invoice_group['label']}", '', '', '', '', '', ''])
            for invoice in invoice_group['invoices']:
                writer.writerow([
                    invoice.name or '',
                    type_labels.get(invoice.move_type, invoice.move_type or ''),
                    invoice.partner_id.name or '',
                    self._project_invoice_date_label(invoice),
                    self._project_invoice_amount_label(invoice),
                    state_labels.get(invoice.state, invoice.state or ''),
                    payment_state_labels.get(invoice.payment_state, invoice.payment_state or ''),
                ])

        filename = f'facturas_proyecto_{project.id}'
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
    def portal_project_invoice_payments(self, project_id, invoice_id, search=None, search_in='all', groupby='none', filterby='all', **kw):
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

        values = self._get_project_invoice_payment_listing_values(
            project,
            invoice,
            search=search,
            search_in=search_in,
            groupby=groupby,
            filterby=filterby,
        )

        values.update({
            'page_name': 'analytic_project_invoice_payments',
            'default_url': f'/my/analytic_projects/{project_id}/invoices_list/{invoice_id}/payments_list',
        })
        return request.render("portal_requests.portal_project_invoice_payments", values)

    @http.route(['/my/analytic_projects/<int:project_id>/invoices_list/<int:invoice_id>/payments_list/export'], type='http', auth="user", website=True)
    def portal_project_invoice_payments_export(self, project_id, invoice_id, search=None, search_in='all', groupby='none', filterby='all', **kw):
        """Exporta a CSV los pagos visibles de la factura del proyecto, compatible con Excel."""
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )

        if not project:
            return request.redirect('/my')

        invoice = request.env['account.move'].sudo().browse(invoice_id)
        if not invoice.exists():
            return request.redirect(f'/my/analytic_projects/{project_id}/invoices_list')

        values = self._get_project_invoice_payment_listing_values(
            project,
            invoice,
            search=search,
            search_in=search_in,
            groupby=groupby,
            filterby=filterby,
        )
        state_labels = self._project_associated_payment_state_labels()

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Referencia', 'Fecha', 'Importe', 'Estado'])

        for payment_group in values['payment_groups']:
            if values['groupby'] != 'none':
                writer.writerow([f"Grupo: {payment_group['label']}", '', '', ''])
            for payment in payment_group['payments']:
                writer.writerow([
                    payment.name or '',
                    self._project_associated_payment_date_label(payment),
                    self._project_associated_payment_amount_label(payment),
                    state_labels.get(payment.state, payment.state or ''),
                ])

        filename = f'pagos_factura_proyecto_{project.id}_{invoice.id}'
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

    @http.route(['/my/analytic_projects/<int:project_id>/invoices_list/<int:invoice_id>/payments_list/<int:payment_id>'], type='http', auth="user", website=True)
    def portal_project_invoice_payment_detail(self, project_id, invoice_id, payment_id, success=None, **kw):
        """Muestra el detalle de un pago asociado a una factura asociada a un proyecto"""
        project = request.env['account.analytic.account'].search(
            [('id', '=', project_id)] + self._get_accessible_analytic_project_domain(request.env.user),
            limit=1
        )

        if not project:
            return request.redirect('/my')

        invoice = request.env['account.move'].sudo().browse(invoice_id)
        if not invoice.exists():
            return request.redirect(f'/my/analytic_projects/{project_id}/invoices_list')

        payment = request.env['account.payment'].sudo().browse(payment_id)
        if not payment.exists() or invoice.id not in payment.invoice_ids.ids:
            return request.redirect(f'/my/analytic_projects/{project_id}/invoices_list/{invoice_id}/payments_list')

        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'account.payment'),
            ('res_id', '=', payment.id)
        ])
        raw_messages = request.env['mail.message'].sudo().search([
            ('model', '=', 'account.payment'),
            ('res_id', '=', payment.id),
            ('subtype_id.internal', '!=', True),
        ], order='date desc')
        messages = self._enrich_messages(raw_messages)

        return request.render("portal_requests.portal_project_invoice_payment_detail", {
            'project': project.sudo(),
            'invoice': invoice,
            'payment': payment,
            'payment_visible_invoices': payment.invoice_ids.filtered(lambda inv: inv.id == invoice.id).sudo(),
            'attachments': attachments,
            'messages': messages,
            'page_name': 'analytic_project_invoice_payment_detail',
            'success_message': success,
        })

    @route('/my/analytic_projects/<int:project_id>/invoices_list/<int:invoice_id>/add_attachment', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_invoice_add_attachment(self,project_id, invoice_id, **post):
        """Permite al usuario portal subir un adjunto al pago"""
        user = request.env.user
        payment = request.env['account.payment'].sudo().browse(invoice_id)
        # Validar acceso igual que en portal_my_payment_detail
        analytic_domain = [('responsible_id', '=', user.id)]
        if user.has_group('portal_requests.group_equip_boss') and not user.has_group('portal_requests.group_administrative'):
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
        if not is_pdf(file_storage):
            return request.redirect(f'/my/payments/{invoice_id}?error=invalid_file')
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
    def portal_my_project_requests(self, page=1, sortby=None, search=None, search_in='all', groupby='none', filterby='all', **kw):
        """Muestra el listado de solicitudes de proyectos del usuario"""
        # Solo los jefes de equipo pueden acceder
        if not request.env.user.has_group('portal_requests.group_equip_boss'):
            return request.redirect('/my')

        values = self._get_project_request_listing_values(
            request.env.user,
            search=search,
            search_in=search_in,
            groupby=groupby,
            filterby=filterby,
        )
        values.update({
            'page_name': 'project_request',
            'default_url': '/my/project_requests',
        })

        return request.render("portal_requests.portal_my_project_requests", values)

    @http.route(['/my/project_requests/export'], type='http', auth="user", website=True)
    def portal_my_project_requests_export(self, search=None, search_in='all', groupby='none', filterby='all', **kw):
        """Exporta a CSV las solicitudes visibles en portal, compatible con Excel."""
        if not request.env.user.has_group('portal_requests.group_equip_boss'):
            return request.redirect('/my')

        values = self._get_project_request_listing_values(
            request.env.user,
            search=search,
            search_in=search_in,
            groupby=groupby,
            filterby=filterby,
        )

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Solicitud', 'Tipo', 'Grupo de Trabajo', 'Estado', 'Fecha Creación'])

        for project_request_group in values['project_request_groups']:
            if values['groupby'] != 'none':
                writer.writerow([f"Grupo: {project_request_group['label']}", '', '', '', ''])
            for project_request in project_request_group['project_requests']:
                writer.writerow([
                    project_request.project_name or '',
                    self._project_request_type_label(project_request),
                    project_request.work_group_id.name or '',
                    self._project_request_state_label(project_request),
                    self._project_request_date_label(project_request),
                ])

        filename = 'solicitudes_proyectos'
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
        if not is_pdf(file_storage):
            return request.redirect(f'/my/project_requests/{request_id}?error=invalid_file')
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
        if not is_pdf(file_storage):
            return request.redirect(f'/my/analytic_projects/{project_id}?error=invalid_file')
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
        if not is_pdf(file_storage):
            return request.redirect(f'/my/invoices/{invoice_request_id}?error=invalid_file')
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
        if not is_pdf(file_storage):
            return request.redirect(f'/my/expenses/{expense_id}?error=invalid_file')
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
