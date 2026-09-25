# -*- coding: utf-8 -*-
"""Tests de la validación de PDF usada al subir adjuntos desde el portal.

Se valida que ``is_pdf`` acepte solo ficheros con extensión ``.pdf`` y cabecera
mágica ``%PDF``, y que ``ensure_pdf`` lance ``UserError`` ante ficheros no válidos
sin consumir el stream (para no romper la lectura posterior en los controllers).
"""
import io

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.portal_requests.controllers.portal_pdf_utils import (
    is_pdf,
    ensure_pdf,
)


class _FakeUpload:
    """Sustituto de werkzeug FileStorage: expone ``filename`` y ``stream``."""

    def __init__(self, filename, content):
        self.filename = filename
        self.stream = io.BytesIO(content)


@tagged('post_install', '-at_install')
class TestPortalPdfUtils(TransactionCase):

    def test_is_pdf_valid(self):
        upload = _FakeUpload('doc.pdf', b'%PDF-1.7 contenido')
        self.assertTrue(is_pdf(upload))

    def test_is_pdf_does_not_consume_stream(self):
        content = b'%PDF-1.7 contenido'
        upload = _FakeUpload('doc.pdf', content)
        is_pdf(upload)
        self.assertEqual(
            upload.stream.read(), content,
            "is_pdf debe restaurar la posición del stream para no romper "
            "la lectura posterior del controller",
        )

    def test_is_pdf_rejects_wrong_extension(self):
        upload = _FakeUpload('doc.docx', b'%PDF-1.7 contenido')
        self.assertFalse(is_pdf(upload))

    def test_is_pdf_rejects_fake_header(self):
        upload = _FakeUpload('doc.pdf', b'PK\x03\x04 esto es un zip')
        self.assertFalse(is_pdf(upload))

    def test_is_pdf_rejects_empty(self):
        self.assertFalse(is_pdf(None))
        self.assertFalse(is_pdf(_FakeUpload('', b'%PDF')))

    def test_ensure_pdf_ok_ignores_empty_slots(self):
        valid = _FakeUpload('a.pdf', b'%PDF-1.4')
        empty = _FakeUpload('', b'')
        # No debe lanzar: los huecos vacíos se ignoran (adjuntos opcionales).
        ensure_pdf(valid, empty)

    def test_ensure_pdf_raises_on_non_pdf(self):
        bad = _FakeUpload('a.pdf', b'no soy un pdf')
        with self.assertRaises(UserError):
            ensure_pdf(bad)
