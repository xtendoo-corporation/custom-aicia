# -*- coding: utf-8 -*-
"""Test de la trazabilidad de rechazo de documentos.

Al rechazar, la solicitud queda en estado ``rejected`` (no se cierra el flujo) y
se notifica al solicitante. Al reenviar (``action_resubmit``) la solicitud vuelve
al inicio del circuito conservando el histórico en el chatter y cancelando la
firma pendiente previa si existiera.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDocumentResubmit(TransactionCase):

    def setUp(self):
        super().setUp()
        self.type_approval = self.env.ref('portal_requests.type_approval_nda')
        # Solicitante (portal) con email para poder notificarle el rechazo.
        self.requester = self.env['res.users'].create({
            'name': 'Solicitante Doc',
            'login': 'doc_requester_test',
            'email': 'doc_requester_test@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        # Director I+D con email: receptor de la notificación de reenvío.
        director_group = self.env.ref(
            'portal_requests.group_director_investigation_and_development')
        self.director = self.env['res.users'].create({
            'name': 'Director I+D',
            'login': 'director_id_test',
            'email': 'director_id_test@example.com',
            'group_ids': [(6, 0, [director_group.id])],
        })
        self.document = self.env['document.approval'].create({
            'type_id': self.type_approval.id,
            'description': 'Documento de prueba',
            'user_id': self.requester.id,
        })

    def test_reject_keeps_flow_open_and_notifies(self):
        mail_before = self.env['mail.mail'].search_count([])
        self.document.action_reject()
        self.assertEqual(self.document.status, 'rejected')
        # Se ha generado una notificación por correo al solicitante.
        self.assertGreater(
            self.env['mail.mail'].search_count([]), mail_before,
            "El rechazo debe notificar por correo al solicitante",
        )

    def test_resubmit_reopens_and_preserves_history(self):
        self.document.action_reject()
        messages_after_reject = len(self.document.message_ids)
        self.document.action_resubmit()
        # Vuelve al inicio del circuito de aprobación.
        self.assertEqual(self.document.status, 'approved_by_director_i_d')
        self.assertFalse(self.document.is_company_signed)
        # El histórico se conserva y crece (no se borra el chatter anterior).
        self.assertGreater(
            len(self.document.message_ids), messages_after_reject,
            "El reenvío debe añadir una nota al histórico sin eliminar las previas",
        )

    def test_resubmit_only_allowed_when_rejected(self):
        # Estado inicial (no rechazado) → no se permite reenviar.
        with self.assertRaises(UserError):
            self.document.action_resubmit()
