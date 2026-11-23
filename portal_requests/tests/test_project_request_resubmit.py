# -*- coding: utf-8 -*-
"""Test del ciclo rechazo -> reenvío de las Solicitudes de Proyecto.

Bug reportado: cuando Soporte (Director I+D) rechaza una Solicitud de
Proyecto, el Jefe de Equipo/Administrativo no tenía ninguna forma de
corregirla y reenviarla: ``portal.project.request`` no tenía estado
"rechazado" con vuelta atrás (solo los booleanos ``approved``/``is_revised``),
ni ``action_resubmit``, ni ruta de portal, ni botón en la plantilla. La única
salida era crear una solicitud nueva desde cero.

Estos tests cubren el nuevo ``action_resubmit`` (modelo) y la ruta
``/my/project_requests/<id>/resubmit`` (portal), en paralelo a como ya
funcionaba el reenvío de Solicitudes de Documentos
(``tests/test_document_resubmit.py``).
"""
from odoo.exceptions import UserError
from odoo.http import Request
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProjectRequestResubmit(TransactionCase):

    def setUp(self):
        super().setUp()
        self.requester = self.env['res.users'].create({
            'name': 'Jefe de Equipo Proyecto',
            'login': 'project_requester_test',
            'email': 'project_requester_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('portal_requests.group_equip_boss').id])],
        })
        director_group = self.env.ref(
            'portal_requests.group_director_investigation_and_development')
        self.director = self.env['res.users'].create({
            'name': 'Director I+D Proyecto',
            'login': 'director_id_project_test',
            'email': 'director_id_project_test@example.com',
            'group_ids': [(6, 0, [director_group.id])],
        })
        self.project_request = self.env['portal.project.request'].create({
            'user_id': self.requester.id,
            'company_id': self.env.company.id,
            'project_name': 'Proyecto de prueba',
            'type': 'new',
        })

    def test_reject_marks_as_rejected_and_notifies_requester(self):
        mail_before = self.env['mail.mail'].search_count([])
        self.project_request.action_reject()
        self.assertFalse(self.project_request.approved)
        self.assertTrue(self.project_request.is_revised)
        self.assertGreater(
            self.env['mail.mail'].search_count([]), mail_before,
            "El rechazo debe notificar por correo al solicitante",
        )

    def test_resubmit_reopens_to_pending_and_preserves_history(self):
        self.project_request.action_reject()
        messages_after_reject = len(self.project_request.message_ids)
        mail_before = self.env['mail.mail'].search_count([])

        self.project_request.action_resubmit()

        # Vuelve a "Pendiente de Revisión": ni aprobada ni rechazada.
        self.assertFalse(self.project_request.approved)
        self.assertFalse(self.project_request.is_revised)
        # El histórico se conserva y crece (no se borra el chatter anterior).
        self.assertGreater(
            len(self.project_request.message_ids), messages_after_reject,
            "El reenvío debe añadir una nota al histórico sin eliminar las previas",
        )
        # Notifica al grupo aprobador (Director I+D) de la nueva versión.
        self.assertGreater(
            self.env['mail.mail'].search_count([]), mail_before,
            "El reenvío debe notificar al grupo aprobador",
        )

    def test_resubmit_only_allowed_when_rejected(self):
        # Estado inicial (pendiente, no rechazada) -> no se permite reenviar.
        with self.assertRaises(UserError):
            self.project_request.action_resubmit()

    def test_resubmit_not_allowed_when_approved(self):
        self.project_request.approved = True
        self.project_request.is_revised = True
        with self.assertRaises(UserError):
            self.project_request.action_resubmit()


@tagged('post_install', '-at_install')
class TestProjectRequestResubmitHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = 'project_resubmit_http_test'
        # Como cualquier usuario real de portal: el rol "Jefe de Equipo" se
        # añade sobre un login de portal, no sustituye a base.group_portal
        # (necesario para poder navegar cualquier página del portal, ya que
        # las rutas ``website=True`` exigen acceso de lectura al modelo
        # ``website`` durante el enrutado).
        self.requester = self.env['res.users'].create({
            'name': 'Jefe de Equipo Proyecto HTTP',
            'login': 'project_requester_http_test',
            'password': self.password,
            'email': 'project_requester_http_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_equip_boss').id,
                self.env.ref('base.group_portal').id,
            ])],
        })
        self.outsider = self.env['res.users'].create({
            'name': 'Ajeno Proyecto HTTP',
            'login': 'project_outsider_http_test',
            'password': self.password,
            'email': 'project_outsider_http_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        # Jefe de equipo del mismo grupo de trabajo que el solicitante, pero
        # NO propietario de la solicitud.
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Proyecto HTTP',
            'login': 'project_boss_http_test',
            'password': self.password,
            'email': 'project_boss_http_test@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('portal_requests.group_equip_boss').id,
                self.env.ref('base.group_portal').id,
            ])],
        })
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Proyecto HTTP',
            'code': 'PROJRESUB',
            'user_ids': [(6, 0, [self.boss.id, self.requester.id])],
            'equip_boss': self.boss.id,
        })
        self.project_request = self.env['portal.project.request'].create({
            'user_id': self.requester.id,
            'company_id': self.env.company.id,
            'work_group_id': self.team.id,
            'project_name': 'Proyecto HTTP de prueba',
            'type': 'new',
        })
        self.project_request.action_reject()

    def _resubmit(self, user):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/project_requests/{self.project_request.id}/resubmit',
            data={'csrf_token': Request.csrf_token(self)},
            allow_redirects=False,
        )

    def test_owner_can_resubmit_without_creating_new_request(self):
        count_before = self.env['portal.project.request'].sudo().search_count([])

        response = self._resubmit(self.requester)

        self.assertTrue(
            response.headers.get('Location', '').endswith(
                f'/my/project_requests/{self.project_request.id}?success=resubmitted'
            ),
            "El solicitante debe poder reenviar la solicitud de proyecto "
            "rechazada sin crear una nueva",
        )
        self.assertFalse(self.project_request.approved)
        self.assertFalse(self.project_request.is_revised)
        # No se ha creado ninguna solicitud nueva: es la misma, reabierta.
        self.assertEqual(
            self.env['portal.project.request'].sudo().search_count([]),
            count_before,
        )

    def test_team_boss_can_resubmit(self):
        # Caso pedido por el cliente: el Jefe de Equipo (o Administrativo)
        # del grupo de trabajo debe poder reenviar una solicitud de proyecto
        # rechazada aunque no sea quien la creó originalmente.
        response = self._resubmit(self.boss)
        self.assertTrue(
            response.headers.get('Location', '').endswith(
                f'/my/project_requests/{self.project_request.id}?success=resubmitted'
            ),
            "El jefe de equipo del grupo de trabajo debe poder reenviar "
            "la solicitud, no solo quien la creó",
        )
        self.assertFalse(self.project_request.approved)
        self.assertFalse(self.project_request.is_revised)

    def test_outsider_cannot_resubmit(self):
        response = self._resubmit(self.outsider)
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.project_request.invalidate_recordset()
        self.assertTrue(self.project_request.is_revised)
        self.assertFalse(self.project_request.approved)

    def test_template_shows_resubmit_button_when_rejected(self):
        self.authenticate(self.requester.login, self.password)
        response = self.url_open(f'/my/project_requests/{self.project_request.id}')
        self.assertIn(
            f'/my/project_requests/{self.project_request.id}/resubmit',
            response.text,
            "El botón de reenvío debe mostrarse cuando la solicitud está "
            "rechazada",
        )

    def test_template_shows_resubmit_button_to_team_boss(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open(f'/my/project_requests/{self.project_request.id}')
        self.assertIn(
            f'/my/project_requests/{self.project_request.id}/resubmit',
            response.text,
            "El botón de reenvío debe mostrarse también al jefe de equipo, "
            "no solo a quien creó la solicitud",
        )
