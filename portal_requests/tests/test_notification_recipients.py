from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNotificationRecipients(TransactionCase):
    """Blinda los dominios de resolucion de destinatarios usados por los
    controladores de portal (empleado, becario, fin de proyecto y orden de
    compra).

    Todos comparten el patron search([('group_ids', 'in', <grupo>.id)]) sobre
    res.users. En Odoo 19 el campo m2m de grupos en res.users se llama
    'group_ids' (antes 'groups_id'); usar el nombre antiguo lanzaba
    ValueError en tiempo de ejecucion al notificar. Estos tests garantizan
    que el dominio es valido y devuelve exactamente los usuarios del grupo.
    """

    def _search_by_group(self, group):
        return self.env["res.users"].search([("group_ids", "in", group.id)])

    def test_intern_partner_responsible_recipients(self):
        """El dominio del responsable de socios internos localiza al usuario
        que pertenece al grupo y excluye a quien no pertenece."""
        group = self.env.ref(
            "portal_requests.group_intern_partner_responsible"
        )
        member = self.env["res.users"].create(
            {
                "name": "Responsable Interno",
                "login": "resp_interno_test",
                "group_ids": [(4, group.id)],
            }
        )
        outsider = self.env["res.users"].create(
            {
                "name": "Ajeno",
                "login": "ajeno_test",
            }
        )

        recipients = self._search_by_group(group)

        self.assertIn(member, recipients)
        self.assertNotIn(outsider, recipients)

    def test_system_admin_recipients(self):
        """El dominio de administrador del sistema (base.group_system) usado
        por los flujos de fin de proyecto y orden de compra es valido y
        localiza al usuario del grupo."""
        group = self.env.ref("base.group_system")
        member = self.env["res.users"].create(
            {
                "name": "Admin Sistema",
                "login": "admin_sistema_test",
                "group_ids": [(4, group.id)],
            }
        )

        recipients = self._search_by_group(group)

        self.assertIn(member, recipients)

    def test_recipient_domain_uses_valid_field(self):
        """El campo 'group_ids' existe en res.users (regresion del rename de
        Odoo 19); el dominio no debe lanzar excepcion."""
        self.assertIn("group_ids", self.env["res.users"]._fields)
        self.assertNotIn("groups_id", self.env["res.users"]._fields)
        group = self.env.ref("base.group_system")
        self._search_by_group(group)
