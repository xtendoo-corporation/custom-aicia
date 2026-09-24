# -*- coding: utf-8 -*-
"""Test HTTP de quién puede reenviar (resubmit) un documento rechazado.

Antes de este fix, la ruta ``/my/documents/<id>/resubmit`` (y el botón de la
plantilla ``portal_my_document_detail``) solo comprobaban
``document.user_id == user`` (el propietario/solicitante). Esto dejaba fuera
al Jefe de Equipo/Administrativo del grupo de trabajo del documento, que ya
podía ver el documento y pedir la revisión final (``is_boss_of_group``/
``is_equip_boss``), pero no podía reenviarlo tras un rechazo: tenía que
pedirle al solicitante original que lo hiciera.
"""
from odoo.http import Request
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestDocumentResubmitAccess(HttpCase):

    def setUp(self):
        super().setUp()
        self.type_approval = self.env.ref('portal_requests.type_approval_nda')
        self.password = 'doc_resubmit_access_test'

        equip_boss_group = self.env.ref('portal_requests.group_equip_boss')
        # Como cualquier usuario real de portal: el rol "Jefe de Equipo" se
        # añade sobre un login de portal, no sustituye a base.group_portal
        # (necesario para poder navegar cualquier página del portal, ya que
        # las rutas ``website=True`` exigen acceso de lectura al modelo
        # ``website`` durante el enrutado).
        self.boss = self.env['res.users'].create({
            'name': 'Jefe de Equipo Resubmit',
            'login': 'equip_boss_resubmit_test',
            'password': self.password,
            'email': 'equip_boss_resubmit_test@example.com',
            'group_ids': [(6, 0, [equip_boss_group.id, self.env.ref('base.group_portal').id])],
        })
        self.requester = self.env['res.users'].create({
            'name': 'Solicitante Resubmit',
            'login': 'requester_resubmit_test',
            'password': self.password,
            'email': 'requester_resubmit_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.outsider = self.env['res.users'].create({
            'name': 'Ajeno Resubmit',
            'login': 'outsider_resubmit_test',
            'password': self.password,
            'email': 'outsider_resubmit_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })

        # El jefe de equipo es boss del grupo al que pertenece el solicitante,
        # pero NO es el propietario del documento.
        self.team = self.env['portal.work.group'].create({
            'name': 'Equipo Resubmit',
            'code': 'RESUB',
            'user_ids': [(6, 0, [self.boss.id, self.requester.id])],
            'equip_boss': self.boss.id,
        })

        self.document = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Documento rechazado de prueba',
            'user_id': self.requester.id,
            'work_group_id': self.team.id,
        })
        self.document.action_reject()

    def _resubmit(self, user):
        self.authenticate(user.login, self.password)
        return self.url_open(
            f'/my/documents/{self.document.id}/resubmit',
            data={'csrf_token': Request.csrf_token(self)},
            files={
                'attachment': (
                    'correccion.pdf',
                    b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n',
                    'application/pdf',
                )
            },
            allow_redirects=False,
        )

    def test_owner_can_resubmit(self):
        response = self._resubmit(self.requester)
        self.assertTrue(
            response.headers.get('Location', '').endswith(
                f'/my/documents/{self.document.id}?success=resubmitted'
            ),
            "El propietario debe poder reenviar el documento rechazado",
        )
        self.assertEqual(self.document.status, 'approved_by_equip_boss')

    def test_team_boss_can_resubmit(self):
        # Caso reportado: el Jefe de Equipo (no propietario) debe poder
        # reenviar un documento rechazado de su equipo, igual que ya podía
        # pedir la revisión final o comentar en el chatter.
        response = self._resubmit(self.boss)
        self.assertTrue(
            response.headers.get('Location', '').endswith(
                f'/my/documents/{self.document.id}?success=resubmitted'
            ),
            "El jefe de equipo del grupo de trabajo debe poder reenviar "
            "un documento rechazado, no solo el propietario",
        )
        self.assertEqual(self.document.status, 'approved_by_equip_boss')

    def test_outsider_cannot_resubmit(self):
        response = self._resubmit(self.outsider)
        self.assertTrue(response.headers.get('Location', '').endswith('/my'))
        self.document.invalidate_recordset()
        self.assertEqual(self.document.status, 'rejected')

    def test_template_shows_resubmit_button_to_team_boss(self):
        self.authenticate(self.boss.login, self.password)
        response = self.url_open(f'/my/documents/{self.document.id}')
        self.assertIn(
            f'/my/documents/{self.document.id}/resubmit',
            response.text,
            "El botón de reenvío debe mostrarse también al jefe de equipo, "
            "no solo al propietario del documento",
        )
