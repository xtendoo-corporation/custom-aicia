import re

from markupsafe import Markup

from odoo import http
from odoo.http import request

from ..models.knowledge_article import DEFAULT_MANUAL, MANUAL_ROLES


# Imágenes del cuerpo del artículo: las del módulo (por id XML) y las que se
# añadan después desde el editor de Knowledge (por id de adjunto).
IMAGE_XMLID_RE = re.compile(r'/web/image/portal_requests\.(manual_img_[a-z0-9_]+)')
IMAGE_ID_RE = re.compile(r'/web/image/(\d+)(?:\?[^"\']*)?')
PDF_LINK_RE = re.compile(r'/web/content/portal_requests\.manual_pdf_[a-z_]+\?download=true')
# Párrafo con el enlace al PDF que llevan los artículos para quien los lee en
# Knowledge; en el portal ya está el botón "Descargar PDF".
PDF_PARAGRAPH_RE = re.compile(
    r'<p>\s*<a href="/web/content/portal_requests\.manual_pdf_[a-z_]+\?download=true">.*?</a>\s*</p>', re.S)


class PortalManualController(http.Controller):
    """Manual de usuario de cada rol, guardado en Knowledge y mostrado en el
    portal. El usuario de portal no tiene acceso a Knowledge: se lee el
    artículo de su rol con sudo y sus imágenes y PDF se sirven por rutas que
    solo entregan lo que pertenece a ese artículo."""

    def _manual_key(self, user):
        for group_xmlid, key in MANUAL_ROLES:
            if user.has_group(group_xmlid):
                return key
        return DEFAULT_MANUAL

    def _manual_article(self, user):
        key = self._manual_key(user)
        article = request.env.ref(f'portal_requests.manual_article_{key}', raise_if_not_found=False)
        return key, (article.sudo() if article and article.sudo().active else None)

    def _portal_body(self, article):
        body = str(article.body or '')
        body = PDF_PARAGRAPH_RE.sub('', body, count=1)
        body = PDF_LINK_RE.sub('/my/manual/pdf', body)
        body = IMAGE_XMLID_RE.sub(r'/my/manual/image/\1', body)
        body = IMAGE_ID_RE.sub(r'/my/manual/image/\1', body)
        return Markup(body)

    @http.route(['/my/manual'], type='http', auth='user', website=True)
    def portal_my_manual(self, **kw):
        key, article = self._manual_article(request.env.user)
        pdf = request.env.ref(f'portal_requests.manual_pdf_{key}', raise_if_not_found=False)
        return request.render('portal_requests.portal_my_manual', {
            'page_name': 'manual',
            'article': article,
            'manual_body': self._portal_body(article) if article else '',
            'has_pdf': bool(pdf),
        })

    @http.route(['/my/manual/image/<string:ref>'], type='http', auth='user')
    def portal_my_manual_image(self, ref, **kw):
        """Imagen del manual del usuario. Solo se entrega si aparece en el
        cuerpo de su artículo (así no se puede pedir la de otro rol)."""
        key, article = self._manual_article(request.env.user)
        if not article:
            raise request.not_found()
        body = str(article.body or '')
        attachment = request.env['ir.attachment']
        if ref.isdigit():
            if ref in IMAGE_ID_RE.findall(body):
                attachment = attachment.sudo().browse(int(ref)).exists()
        elif ref in IMAGE_XMLID_RE.findall(body):
            attachment = (request.env.ref(f'portal_requests.{ref}', raise_if_not_found=False)
                          or attachment).sudo()
        if not attachment or attachment._name != 'ir.attachment':
            raise request.not_found()
        return request.env['ir.binary']._get_image_stream_from(attachment).get_response()

    @http.route(['/my/manual/pdf'], type='http', auth='user')
    def portal_my_manual_pdf(self, **kw):
        """PDF del manual del rol del usuario."""
        key = self._manual_key(request.env.user)
        attachment = request.env.ref(f'portal_requests.manual_pdf_{key}', raise_if_not_found=False)
        if not attachment:
            raise request.not_found()
        stream = request.env['ir.binary']._get_stream_from(attachment.sudo(), 'raw')
        return stream.get_response(as_attachment=True)
