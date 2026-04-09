from odoo import models, fields, api, _


class PortalInvoiceRequest(models.Model):
    _name = 'portal.invoice.request'
    _description = 'Portal Invoice Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _rec_name = 'computed_name'

    user_id = fields.Many2one('res.users', string='User', required=True)

    analytic_id = fields.Many2one('account.analytic.account', string='Proyecto', required=True)
    responsible_id = fields.Many2one('res.users', related='analytic_id.responsible_id', string='Responsable', store=True)
    work_group_id = fields.Many2one('portal.work.group', related='analytic_id.work_group_id', string='Grupo de Trabajo', store=True)
    equip_boss = fields.Many2one('res.users', related='work_group_id.equip_boss', string='Jefe de Equipo', store=True)

    partner_id = fields.Many2one('res.partner', string='Client', required=True)
    amount = fields.Float(string='Amount', required=True)
    notes = fields.Text(string='Invoice Concept')
    move_type = fields.Selection([
        ('out_invoice', 'Customer Invoice'),
        ('out_refund', 'Customer Credit Note'),
    ], string='Type', default='out_invoice', required=True)
    date = fields.Date(string='Date')
    l10n_es_edi_facturae_reason_code = fields.Selection(
        selection=lambda self: self.env['account.move']._fields[
            'l10n_es_edi_facturae_reason_code']._description_selection(self.env),
        string='Spanish Facturae EDI Reason Code',
        default='10'
    )
    approved = fields.Boolean(string='Approved', default=False)
    is_revised = fields.Boolean(string='Is revised', default=False, store=True)
    invoice_created = fields.Many2one('account.move', string='Invoice Created')
    invoice_to_refund = fields.Many2one('account.move', string='Invoice to Refund')

    invoice_count = fields.Integer(default=1, string='Invoice Count')
    computed_name = fields.Char('Computed Name', compute='_compute_name')
    send_draft = fields.Boolean(string='Enviar Borrador de Factura', default=False)
    status = fields.Selection([('to_revise', 'Volver a revisar'),
                               ('approved_by_boss_group', 'Aprobación del Jefe de Equipo'),
                               ('approved_by_client_responsible', 'Aprobación del Responsable de clientes'),
                               ('approve', 'Aprobada'), ("rejected", 'Rechazada')
                               ], 'Estado',
                              default='approved_by_boss_group', tracking=True)

    def _compute_name(self):
        for record in self:
            record.computed_name = F"Solicitud de Factura para {record.analytic_id.name}"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.user_id and record.user_id.partner_id:
                record.message_subscribe(partner_ids=[record.user_id.partner_id.id])
        return records

    show_solicitar_revision = fields.Boolean(
        string='Mostrar Solicitar Revisión',
        compute='_compute_show_solicitar_revision',
        store=False,
    )

    show_approve_button = fields.Boolean(
        string='Mostrar Botón Aprobar',
        compute='_compute_show_approve_button',
        store=False,
    )

    @api.depends('status', 'equip_boss')
    def _compute_show_approve_button(self):
        user = self.env.user
        for rec in self:
            rec.show_approve_button = (
                rec.status == 'approved_by_boss_group' and
                rec.equip_boss == user
            )

    @api.depends('status')
    def _compute_show_solicitar_revision(self):
        is_boss = self.env.user.sudo().has_group('portal_requests.group_equip_boss') or self.env.user.sudo().has_group('portal_requests.group_intern_partner_responsible')
        for rec in self:
            rec.show_solicitar_revision = (rec.status == 'to_revise') and (not is_boss)

    def show_notificacion(self, title_char, text, type_char):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': type_char,
                'message': text,
                'title': title_char,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def _send_invoice_request_mail(self,type, users_to_send, move_text, user_name, company_name, partner_name, notes=""):
            invoice_request_link = f"/web#id={self.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=portal.invoice.request&view_type=form"
            if type == 'to_revise':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>Se ha solicitado una nueva revisión de {move_text}, por parte de {user_name}.</p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{invoice_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Nueva Revisión de {move_text}',
                        'email_from': self.env.user.email or '',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()
            if type == 'approved_by_boss_group':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>La solicitud de {move_text} en el proyecto {company_name} ha sido aprobada por el jefe de equipo ({user_name}).</p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{invoice_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Solicitud de {move_text}',
                        'email_from': self.env.user.email or 'no-reply@example.com',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()
            if type == 'rejected':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>La solicitud de {move_text} en el proyecto {company_name} ha sido rechazada por el siguiente motivo:</p>
                                <p><em>{notes}</em></p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{invoice_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Solicitud de {move_text}',
                        'email_from': self.env.user.email or 'no-reply@example.com',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()




    def action_approve(self):
        type = self.status
        if type == 'to_revise':
            self.status = 'approved_by_boss_group'
            user_to_send = self.env['res.users'].search([('id', '=', self.equip_boss.id)])
            move_text = self.computed_name
            # Usar sudo() para acceder a partner_id.name para evitar errores de permisos
            self._send_invoice_request_mail(type, user_to_send, move_text, self.user_id.name, self.analytic_id.name, self.partner_id.sudo().name)
            return self.show_notificacion("¡Solicitud enviada!", "La solicitud ha sido enviada al jefe de equipo para su revisión.", "success")

        if self.status=='approved_by_boss_group':
            if self.equip_boss and self.equip_boss.partner_id:
                self.message_subscribe(partner_ids=[self.equip_boss.partner_id.id])
            self.status = 'approved_by_client_responsible'
            user_to_send = self.env['res.users'].search([('work_group_ids', 'in', self.env.ref('portal_requests.group_intern_partner_responsible').id)])
            move_text = "factura" if self.move_type == 'out_invoice' else "factura rectificativa"
            # Usar sudo() para acceder a partner_id.name para evitar errores de permisos
            self._send_invoice_request_mail(type, user_to_send, move_text, self.user_id.name, self.analytic_id.name, self.partner_id.sudo().name)
            return self.show_notificacion("¡Aprobación registrada!", "La solicitud ha sido aprobada y enviada al responsable de clientes para su revisión.", "success")

        if self.status=='approved_by_client_responsible':
            self.status = 'approve'
            for record in self:
                #record.add_partner_id_to_followers()
                record.approved = True
                record.is_revised = True
                record.create_invoice()
                body = 'Factura borrador creada correctamente.'

                # publicar como nota en el chatter (usar subtype_id con env.ref)
                self.sudo().message_post(
                    body=body,
                    subtype_id=self.env.ref('mail.mt_note').id
                )
                if record.send_draft:
                    record.invoice_created.action_send_draft_to_followers()
                    return self.show_notificacion("¡Solicitud aprobada!", "La factura borrador ha sido creada y enviada como borrador correctamente.",
                                                  "success")
            return self.show_notificacion("¡Solicitud aprobada!", "La factura borrador ha sido creada correctamente.", "success")

    def action_reject(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rechazar solicitud de factura',
            'res_model': 'invoice.request.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_id': self.id,
            }
        }

    def action_to_revise(self):
        for record in self:
            record.is_revised = False

    def create_invoice(self):
        print("*" * 100)
        if self.move_type == 'out_invoice':
            print("Factura")
            tax_ids =self.env['account.tax'].search([('name', '=', '21% S')], limit=1)
            journal_id = self.env['account.journal'].search([('name', '=', 'Facturas de cliente')], limit=1)
            invoice = self.env['account.move'].sudo().create({
                'partner_id': self.partner_id.id,
                'invoice_date': self.date,
                'invoice_origin': False,
                'journal_id': journal_id.id,
                'move_type': 'out_invoice',
                'analytic_distribution': {
                    self.analytic_id.id: 100,  # 100 significa 100% de distribución
                } if self.analytic_id else {},
                'invoice_line_ids': [
                    (0, 0, {
                        'name': self.notes,
                        'quantity': 1.0,
                        'price_unit': self.amount,
                        'analytic_distribution': {
                            self.analytic_id.id: 100,  # 100 significa 100% de distribución
                        } if self.analytic_id else {},
                        'tax_ids': [(6, 0, tax_ids.ids)],
                    })
                ],
            })
        else:
            print("Factura rectificativa")
            print("self.l10n_", self.l10n_es_edi_facturae_reason_code)
            options = self.env['account.move']._fields['l10n_es_edi_facturae_reason_code']._description_selection(
                self.env)
            reason = _("Reversión de %s") % self.invoice_to_refund.name
            for value, label in options:
                if value == self.l10n_es_edi_facturae_reason_code:
                    reason = reason + " " + label
                    break

            invoice = self.env['account.move'].sudo().create({
                'move_type': 'out_refund',
                'partner_id': self.partner_id.id,
                'company_id': self.company_id.id,
                'invoice_date': self.date,
                'ref': reason,
                'invoice_line_ids': [
                    (0, 0, {
                        'name': self.notes,
                        'quantity': 1.0,
                        'price_unit': self.amount,
                    })
                ],
            })

        # invoice.sudo().action_post()
        self.invoice_created = invoice.id
        self.invoice_created._onchange_analytic_distribution()
        group = self.analytic_id.work_group_id
        invoice.add_followers_from_request(self)
        #self.invoice_created.add_partner_id_to_followers(group)

    def action_view_invoice(self):
        self.ensure_one()
        invoice_ids = self.invoice_created.ids
        action = {
            "res_model": "account.move",
            "type": "ir.actions.act_window",
        }
        if len(invoice_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": invoice_ids[0],
                }
            )
        else:
            action.update(
                {
                    "name": "Factura",
                    "domain": [("id", "in", invoice_ids)],
                    "view_mode": "tree,form",
                }
            )
        return action


    def add_partner_id_to_followers(self):
        self.ensure_one()
        if not self.partner_id:
            return
        self.message_subscribe(partner_ids=[self.partner_id.id])
