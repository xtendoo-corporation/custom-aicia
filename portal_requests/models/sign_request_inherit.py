from odoo import models, _


class SignRequestInherit(models.Model):
    _inherit = 'sign.request'

    def _get_linked_record_action(self, default_action):
        """Cuando reference_doc es un document.approval, devolvemos siempre
        nuestra acción conocida con domain vacío, evitando que Sign encuentre
        otras acciones con dominios Python no evaluables en el cliente
        (p.ej. [('approved','=',True),('company_id','=',user.company_id.id)])."""
        self.ensure_one()
        if self.reference_doc and self.reference_doc._name == 'document.approval':
            action_ref = self.env.ref(
                'portal_requests.action_document_approval_all',
                raise_if_not_found=False,
            )
            if action_ref:
                action = action_ref._get_action_dict()
                action.update({
                    'views': [(False, 'form')],
                    'view_mode': 'form',
                    'res_id': self.reference_doc.id,
                    'target': 'current',
                    'domain': [],
                    # clearBreadcrumbs fuerza recarga completa del formulario
                    # para que los botones reflejen el estado actualizado
                    'context': {'clearBreadcrumbs': True},
                })
                return action
        return super()._get_linked_record_action(default_action)

    def get_close_values(self):
        """Sincroniza sign_request_id en document.approval antes de construir
        la acción de cierre, para que al volver al formulario los botones
        reflejen el estado correcto (firmado) sin necesidad de recargar
        manualmente."""
        self.ensure_one()
        if self.reference_doc and self.reference_doc._name == 'document.approval':
            doc = self.reference_doc
            # Vincular este sign.request al document.approval si no lo estaba ya
            if not doc.sign_request_id or doc.sign_request_id.id != self.id:
                doc.sudo().write({'sign_request_id': self.id})
        return super().get_close_values()

    def _send_completed_documents(self):
        """Cuando la firma está vinculada a un document.approval, omitimos el
        envío del email de notificación de firma completada. El documento firmado
        se adjunta igualmente al registro gracias al flujo estándar de _sign()."""
        self.ensure_one()
        if self.reference_doc and self.reference_doc._name == 'document.approval':
            # Solo generamos los documentos completados sin enviar emails
            if not self.completed_document_ids:
                self._generate_completed_documents()
            return
        return super()._send_completed_documents()
