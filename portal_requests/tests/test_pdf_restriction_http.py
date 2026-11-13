# -*- coding: utf-8 -*-
"""Test funcional HTTP de la restricción de formato PDF en el portal.

Ejercita la ruta real ``/portal/approval_request/submit`` (auth de usuario,
propia del módulo, sin colisión con rutas de ``account``/``portal``), que
aplica ``ensure_pdf`` sobre los ficheros aportados. Cubre el caso de uso
reportado por AICIA: "obligar a subir documentos únicamente en formato PDF".

Se comprueba de extremo a extremo:
- un fichero no-PDF hace que ``ensure_pdf`` lance ``UserError``: la solicitud
  no se completa (no redirige al agradecimiento) y no persiste ni la
  ``document.approval`` ni el adjunto (la transacción se revierte);
- un PDF válido completa el flujo: redirige a ``/my/documents/thank-you`` y crea
  la ``document.approval`` con su adjunto.
"""
from odoo.http import Request
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPdfRestrictionHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = "portal_pdf_http_test"
        self.user = self.env["res.users"].create(
            {
                "name": "Solicitante Portal",
                "login": "pdf_http_test",
                "password": self.password,
                "email": "pdf_http_test@example.com",
                "group_ids": [(4, self.env.ref("base.group_user").id)],
            }
        )
        # El tipo de aprobación al que mapea 'sign_nda' en el controlador.
        self.approval_type = self.env["type.approval"].search(
            [("name", "=", "Solicitud de firma NDA")], limit=1
        )
        self.assertTrue(
            self.approval_type,
            "Debe existir el tipo de aprobación 'Solicitud de firma NDA'",
        )
        self.work_group = self.env["portal.work.group"].create(
            {
                "name": "Equipo PDF Test",
                "code": "PDFTEST",
                "user_ids": [(4, self.user.id)],
            }
        )

    def _doc_count(self):
        return self.env["document.approval"].sudo().search_count(
            [("user_id", "=", self.user.id)]
        )

    def _attachment_count(self):
        return self.env["ir.attachment"].sudo().search_count(
            [("res_model", "=", "document.approval")]
        )

    def _submit(self, filename, content, content_type):
        self.authenticate(self.user.login, self.password)
        return self.url_open(
            "/portal/approval_request/submit",
            data={
                "csrf_token": Request.csrf_token(self),
                "approval_type": "sign_nda",
                "description": "Solicitud de prueba",
                "work_group": self.work_group.id,
            },
            files={"file": (filename, content, content_type)},
            allow_redirects=False,
        )

    def test_non_pdf_upload_is_rejected(self):
        docs_before = self._doc_count()
        att_before = self._attachment_count()

        response = self._submit(
            "documento.txt", b"esto no es un pdf", "text/plain"
        )

        self.assertNotEqual(
            response.headers.get("Location", ""),
            "/my/documents/thank-you",
            "Un no-PDF no debe completar la solicitud",
        )
        self.assertEqual(
            self._doc_count(),
            docs_before,
            "Un no-PDF no debe persistir la solicitud (transacción revertida)",
        )
        self.assertEqual(
            self._attachment_count(),
            att_before,
            "Un no-PDF no debe crear ningún adjunto",
        )

    def test_fake_pdf_extension_is_rejected(self):
        """Extensión .pdf pero sin cabecera %PDF: debe rechazarse igualmente."""
        docs_before = self._doc_count()
        att_before = self._attachment_count()

        response = self._submit(
            "falso.pdf", b"contenido sin cabecera pdf", "application/pdf"
        )

        self.assertNotEqual(
            response.headers.get("Location", ""), "/my/documents/thank-you"
        )
        self.assertEqual(self._doc_count(), docs_before)
        self.assertEqual(self._attachment_count(), att_before)

    def test_valid_pdf_upload_is_accepted(self):
        docs_before = self._doc_count()
        att_before = self._attachment_count()

        response = self._submit(
            "documento.pdf",
            b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n",
            "application/pdf",
        )

        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(
            response.headers.get("Location", "").endswith(
                "/my/documents/thank-you"
            ),
            "Un PDF válido debe completar la solicitud",
        )
        self.assertEqual(
            self._doc_count(),
            docs_before + 1,
            "Un PDF válido debe crear la solicitud",
        )
        self.assertEqual(
            self._attachment_count(),
            att_before + 1,
            "Un PDF válido debe crear su adjunto",
        )
