from odoo import models


class PortalRequestNotifyMixin(models.AbstractModel):
    """Notificación homogénea al solicitante en cada cambio de estado.

    Los modelos con un campo Selection de estado indican su nombre en
    ``_notify_state_field`` y la notificación se dispara automáticamente en
    ``write``. Los modelos que derivan su estado de varios campos booleanos
    llaman a ``_notify_requester_state`` desde sus métodos de acción.
    """

    _name = "portal.request.notify.mixin"
    _description = "Notificación al solicitante en cambios de estado"

    # Campo Selection de estado a vigilar en write(); False para vigilancia manual.
    _notify_state_field = False
    # Ruta base del portal para el enlace al detalle (sin barra final); False -> /my.
    _notify_portal_route = False

    def _notify_get_recipient(self):
        self.ensure_one()
        if "user_id" in self._fields:
            return self.user_id
        return self.env["res.users"].browse()

    def _notify_get_portal_url(self):
        self.ensure_one()
        base_url = self.get_base_url()
        if self._notify_portal_route:
            return f"{base_url}{self._notify_portal_route}/{self.id}"
        return f"{base_url}/my"

    def _notify_get_title(self):
        self.ensure_one()
        if "computed_name" in self._fields and self.computed_name:
            return self.computed_name
        if "display_name" in self._fields and self.display_name:
            return self.display_name
        return self._description or self._name

    def _notify_state_label(self):
        self.ensure_one()
        field_name = self._notify_state_field
        field = self._fields.get(field_name) if field_name else None
        if field and field.type == "selection":
            value = self[field_name]
            return dict(field._description_selection(self.env)).get(value, value)
        return self[field_name] if field_name else ""

    def _notify_link_for(self, recipient, backend_link):
        """Enlace para un correo según el destinatario: un usuario de portal
        (p.ej. el Jefe de Equipo) no puede abrir el backend, así que recibe el
        enlace al detalle de la solicitud en el portal."""
        self.ensure_one()
        if recipient.share:
            return self._notify_get_portal_url()
        return backend_link

    def _notify_requester_state(self, state_label, note=None):
        """Envía un correo estándar al solicitante informando del nuevo estado.
        ``note`` (opcional) se añade al cuerpo, p.ej. el motivo de un rechazo."""
        Mail = self.env["mail.mail"].sudo()
        email_from = self.env.company.email or "no-reply@aicia.es"
        for record in self:
            recipient = record._notify_get_recipient()
            if not recipient or not recipient.email:
                continue
            url = record._notify_get_portal_url()
            title = record._notify_get_title()
            note_html = f"<p><strong>Motivo:</strong> <em>{note}</em></p>" if note else ""
            body_html = f"""
                <p>Estimado/a {recipient.name},</p>
                <p>El estado de su solicitud "<strong>{title}</strong>" ha cambiado a:
                   <strong>{state_label}</strong>.</p>
                {note_html}
                <p><a href="{url}">Ver la solicitud en el portal</a></p>
                <p>Saludos cordiales.</p>
            """
            Mail.create({
                "subject": f"Actualización de su solicitud: {state_label}",
                "email_from": email_from,
                "email_to": recipient.email,
                "body_html": body_html,
            }).send()

    def write(self, vals):
        watch = bool(self._notify_state_field) and self._notify_state_field in vals
        previous = {}
        if watch:
            previous = {record.id: record[self._notify_state_field] for record in self}
        result = super().write(vals)
        if watch:
            for record in self:
                if record[self._notify_state_field] != previous.get(record.id):
                    record._notify_requester_state(record._notify_state_label())
        return result
