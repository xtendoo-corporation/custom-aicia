# -*- coding: utf-8 -*-
"""Test del sufijo ``_firmado`` aplicado al nombre de los documentos firmados."""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSignedSuffix(TransactionCase):

    def setUp(self):
        super().setUp()
        self.SignRequest = self.env['sign.request']

    def test_adds_suffix_before_extension(self):
        self.assertEqual(
            self.SignRequest._append_signed_suffix('contrato.pdf'),
            'contrato_firmado.pdf',
        )

    def test_adds_suffix_without_extension(self):
        self.assertEqual(
            self.SignRequest._append_signed_suffix('contrato'),
            'contrato_firmado',
        )

    def test_is_idempotent(self):
        self.assertEqual(
            self.SignRequest._append_signed_suffix('contrato_firmado.pdf'),
            'contrato_firmado.pdf',
        )

    def test_handles_empty_name(self):
        self.assertEqual(self.SignRequest._append_signed_suffix(''), '')
        self.assertEqual(self.SignRequest._append_signed_suffix(False), False)
