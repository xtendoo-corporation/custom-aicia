# -*- coding: utf-8 -*-
"""Tests de las notificaciones automáticas de cambio de estado.

Cubren el requisito de AICIA de "activar notificaciones automáticas por correo
para todos los cambios de estado". La lógica vive en
``portal.request.notify.mixin``: al escribir el campo de estado vigilado
(``_notify_state_field``), si el valor cambia, se envía un correo al solicitante.

Se usa ``document.approval`` como modelo representativo (vigila ``status``).
"""
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStateChangeNotifications(TransactionCase):

    def setUp(self):
        super().setUp()
        self.type_approval = self.env.ref("portal_requests.type_approval_nda")
        self.requester = self.env["res.users"].create(
            {
                "name": "Solicitante Estado",
                "login": "estado_requester_test",
                "email": "estado_requester_test@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        self.document = self.env["document.approval"].create(
            {
                "type_id": self.type_approval.id,
                "description": "Documento notificaciones",
                "user_id": self.requester.id,
            }
        )

    def _mails_to_requester(self):
        return self.env["mail.mail"].search_count(
            [("email_to", "=", self.requester.email)]
        )

    def test_state_change_notifies_requester(self):
        """Cambiar el estado genera un correo automático al solicitante."""
        before = self._mails_to_requester()

        self.document.write({"status": "approved_by_director_gerente"})

        self.assertEqual(
            self._mails_to_requester(),
            before + 1,
            "Cada cambio de estado debe notificar por correo al solicitante",
        )

    def test_same_state_write_does_not_notify(self):
        """Escribir el mismo estado no debe generar notificación (idempotente)."""
        before = self._mails_to_requester()

        self.document.write({"status": self.document.status})

        self.assertEqual(
            self._mails_to_requester(),
            before,
            "Escribir el mismo estado no debe enviar correo",
        )

    def test_two_consecutive_changes_notify_twice(self):
        """Dos transiciones distintas generan dos notificaciones."""
        before = self._mails_to_requester()

        self.document.write({"status": "approved_by_director_gerente"})
        self.document.write({"status": "sign_company"})

        self.assertEqual(self._mails_to_requester(), before + 2)

    def test_requester_without_email_is_not_notified(self):
        """Si el solicitante no tiene email, no se intenta notificar."""
        self.requester.email = False
        mails_before = self.env["mail.mail"].search_count([])

        self.document.write({"status": "approved_by_director_gerente"})

        self.assertEqual(
            self.env["mail.mail"].search_count([]),
            mails_before,
            "Sin email no debe crearse ningún correo",
        )
