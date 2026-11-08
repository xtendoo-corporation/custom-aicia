# -*- coding: utf-8 -*-
"""Contadores del home del portal (``/my``).

El JS ``portal_home_counters`` asigna ``textContent`` al placeholder
``[data-placeholder_count=<clave>]`` de cada clave devuelta por
``/my/counters``; una clave sin placeholder rompe ``/my`` con
``TypeError: Cannot set properties of null``. Se valida que:
- ``/my/counters`` solo devuelve claves de contador, nunca ``is_equip_boss``;
- ``/my`` sigue mostrando la tarjeta de Solicitudes de Proyectos solo al
  Jefe de Equipo.
"""
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPortalHomeCounters(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = "portal_counters_test"
        self.user = self.env["res.users"].create(
            {
                "name": "Usuario Contadores",
                "login": "portal_counters_test",
                "password": self.password,
                "email": "portal_counters_test@example.com",
                "group_ids": [(4, self.env.ref("base.group_user").id)],
            }
        )

    def _make_equip_boss(self):
        self.user.group_ids = [
            (4, self.env.ref("portal_requests.group_equip_boss").id)
        ]

    def _counters(self, counters):
        self.authenticate(self.user.login, self.password)
        return self.make_jsonrpc_request(
            "/my/counters", {"counters": counters}
        )

    def test_counters_only_return_count_keys(self):
        self._make_equip_boss()
        result = self._counters(["analytic_project_count"])
        self.assertIn("analytic_project_count", result)
        self.assertNotIn("is_equip_boss", result)
        self.assertTrue(all(key.endswith("_count") for key in result))

    def test_counters_empty_request(self):
        result = self._counters([])
        self.assertNotIn("is_equip_boss", result)

    def test_home_shows_project_requests_card_for_equip_boss(self):
        self._make_equip_boss()
        self.authenticate(self.user.login, self.password)
        response = self.url_open("/my")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/my/project_requests", response.text)

    def test_home_renders_counters_spinner(self):
        """El JS elimina ``.o_portal_doc_spinner`` tras cargar contadores."""
        self.authenticate(self.user.login, self.password)
        response = self.url_open("/my")
        self.assertEqual(response.status_code, 200)
        self.assertIn("o_portal_doc_spinner", response.text)

    def test_home_hides_project_requests_card_for_regular_user(self):
        self.authenticate(self.user.login, self.password)
        response = self.url_open("/my")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/my/project_requests", response.text)
