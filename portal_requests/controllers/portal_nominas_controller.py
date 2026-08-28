# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging
import base64

_logger = logging.getLogger(__name__)


class PortalNominasController(http.Controller):

    # ---------------------------------------------------------
    # LISTADO /my/nomina
    # ---------------------------------------------------------
    @http.route(['/my/nomina'], type='http', auth="user", website=True)
    def portal_my_nomina(self, search=None, groupby='none', **kw):

        user = request.env.user

        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        _logger.warning("\n\n🔥 ===== NOMINA PORTAL DEBUG =====")
        _logger.warning("USER: %s (%s)", user.id, user.login)
        _logger.warning("EMPLOYEE: %s - %s", employee.id, employee.name)

        if not employee:
            _logger.error("❌ No employee linked to user")
            return request.render("portal.portal_no_data", {})

        domain = [
            ('res_model', '=', 'hr.employee'),
            ('res_id', '=', employee.id),
            ('name', 'ilike', 'nomina_')
        ]

        if search:
            domain.append(('name', 'ilike', search))

        attachments = request.env['ir.attachment'].sudo().search(
            domain,
            order="create_date desc"
        )

        _logger.warning("DOMAIN: %s", domain)
        _logger.warning("ATTACHMENTS FOUND: %s", len(attachments))

        for att in attachments:
            _logger.warning(
                "ATT -> id=%s name=%s res_model=%s res_id=%s",
                att.id, att.name, att.res_model, att.res_id
            )

        # -------------------------
        # GROUPING POR AÑO
        # -------------------------
        groups = {}
        for att in attachments:
            parts = att.name.split('_')
            year = parts[-1].split('.')[0] if len(parts) >= 3 else 'Sin año'
            groups.setdefault(year, []).append(att)

        payment_groups = [
            {'label': k, 'entries': v}
            for k, v in groups.items()
        ]

        return request.render("portal_requests.portal_my_nomina_template", {
            'attachments': attachments,
            'payment_groups': payment_groups,
            'groupby': groupby or 'none',
            'search': search or '',
            'searchbar_groupby': {
                'none': {'label': 'Sin agrupar'},
                'year': {'label': 'Año'}
            },
            'default_url': '/my/nomina',
            'keep_query': request.httprequest.args.to_dict,
        })

    # ---------------------------------------------------------
    # 🔥 DOWNLOAD CON DEBUG + FIX REAL
    # ---------------------------------------------------------
    @http.route(['/my/nomina/download/<int:attachment_id>'], type='http', auth="user", website=True)
    def download_nomina(self, attachment_id, **kw):

        user = request.env.user

        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', user.id)
        ], limit=1)

        attachment = request.env['ir.attachment'].sudo().browse(attachment_id)

        _logger.warning("\n\n🔥 ===== DOWNLOAD DEBUG =====")
        _logger.warning("USER: %s (%s)", user.id, user.login)
        _logger.warning("EMPLOYEE: %s", employee.id)
        _logger.warning("ATTACHMENT ID: %s", attachment_id)

        if not attachment.exists():
            _logger.error("❌ Attachment does not exist")
            return request.not_found()

        _logger.warning("ATTACHMENT FOUND: %s", attachment.name)
        _logger.warning("RES_MODEL: %s", attachment.res_model)
        _logger.warning("RES_ID: %s", attachment.res_id)

        # seguridad
        if attachment.res_model != 'hr.employee':
            _logger.error("❌ Wrong res_model")
            return request.not_found()

        if attachment.res_id != employee.id:
            _logger.error("❌ Access denied (wrong employee)")
            return request.not_found()

        try:
            content = base64.b64decode(attachment.datas or b'')

            headers = [
                ('Content-Type', attachment.mimetype or 'application/pdf'),
                ('Content-Disposition', f'attachment; filename="{attachment.name}"')
            ]

            _logger.warning("✅ DOWNLOAD SUCCESS: %s", attachment.name)

            return request.make_response(content, headers)

        except Exception as e:
            _logger.exception("❌ DOWNLOAD ERROR: %s", str(e))
            return request.not_found()
