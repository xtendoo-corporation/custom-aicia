# -*- coding: utf-8 -*-
"""Tests del umbral de 10.000 € en las solicitudes de gasto.

Cubren el requisito de AICIA: el Director Gerente (DG) solo debe intervenir y
recibir notificación cuando el importe supera los 10.000 € (campo ``is_more``).
Por debajo del umbral, el segundo aprobador cierra la solicitud (estado
``approve``) sin notificar al DG.

La lógica está en ``portal.hr.expensive.request.action_approve``. El método de
creación de factura (``_create_purchase_invoice``) queda fuera del alcance de
estos tests (crea ``account.move`` y dispara escaneo AI); se sustituye por un
no-op para aislar la decisión de umbral.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestExpenseThreshold(TransactionCase):

    def setUp(self):
        super().setUp()
        plan = self.env["account.analytic.plan"].create({"name": "Plan Umbral Test"})
        self.project = self.env["account.analytic.account"].create(
            {"name": "Proyecto Umbral", "plan_id": plan.id}
        )
        self.requester = self.env["res.users"].create(
            {
                "name": "Solicitante Gasto",
                "login": "gasto_requester_test",
                "email": "gasto_requester_test@example.com",
            }
        )
        # Segundo aprobador: Responsable de personal y compras.
        approver_group = self.env.ref(
            "portal_requests.group_personnel_purchase_responsible"
        )
        self.approver = self.env["res.users"].create(
            {
                "name": "Responsable Compras",
                "login": "compras_approver_test",
                "email": "compras_approver_test@example.com",
                "group_ids": [
                    (4, self.env.ref("base.group_user").id),
                    (4, approver_group.id),
                ],
            }
        )
        # Director Gerente: receptor de la notificación por encima del umbral.
        director_group = self.env.ref("portal_requests.group_director_manager")
        self.director = self.env["res.users"].create(
            {
                "name": "Director Gerente",
                "login": "dg_test",
                "email": "dg_test@example.com",
                "group_ids": [
                    (4, self.env.ref("base.group_user").id),
                    (4, director_group.id),
                ],
            }
        )

    def _create_request(self, is_more):
        return self.env["portal.hr.expensive.request"].create(
            {
                "type": "bienes_servicios",
                "project": self.project.id,
                "user_id": self.requester.id,
                "status": "approved_purchase_responsible",
                "is_more": is_more,
            }
        )

    def _mails_to_director(self):
        return self.env["mail.mail"].search_count(
            [("email_to", "=", self.director.email)]
        )

    def test_over_threshold_escalates_and_notifies_director(self):
        """>10.000 €: se escala al DG y se le notifica."""
        request = self._create_request(is_more=True)
        before = self._mails_to_director()

        request.with_user(self.approver).action_approve()

        self.assertEqual(
            request.status,
            "approved_director",
            "Por encima del umbral debe escalarse al Director Gerente",
        )
        self.assertEqual(
            self._mails_to_director(),
            before + 1,
            "El Director Gerente debe ser notificado por encima del umbral",
        )

    def test_under_threshold_closes_without_notifying_director(self):
        """<10.000 €: el segundo aprobador cierra sin notificar al DG."""
        request = self._create_request(is_more=False)
        before = self._mails_to_director()

        with patch.object(
            type(request), "_create_purchase_invoice", lambda self: None
        ):
            request.with_user(self.approver).action_approve()

        self.assertEqual(
            request.status,
            "approve",
            "Por debajo del umbral la solicitud queda aprobada directamente",
        )
        self.assertEqual(
            self._mails_to_director(),
            before,
            "El Director Gerente no debe recibir notificación bajo el umbral",
        )
