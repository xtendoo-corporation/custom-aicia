from odoo import models, fields, api


class PortalHrExpensiveRequest(models.Model):
    _name = 'portal.hr.expensive.request'
    _description = 'Portal HR Expensive Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'computed_name'

    computed_name = fields.Char('Computed Name', compute='_compute_name')
    def _compute_name(self):
        for record in self:
            record.computed_name = F"Solicitud de Gasto para {record.project.name}"

    user_id = fields.Many2one('res.users', string='User', required=True)
    type = fields.Selection([
        ('bienes_servicios', 'Compra de bienes o servicios'),
        ('material_inventariable', 'Pago de material inventariable'),
    ], string='Tipo', required=True)
    project = fields.Many2one('account.analytic.account', string='Project', required=True)
    work_group_id = fields.Many2one('portal.work.group', related='project.work_group_id', string='Grupo de Trabajo',
                                    store=True)
    equip_boss = fields.Many2one('res.users', related='work_group_id.equip_boss', string='Jefe de Equipo', store=True)
    status = fields.Selection([('to_revise', 'Volver a revisar'),
                               ('approved_by_boss_group', 'Aprobación del Jefe de Equipo'),
                               ('approved_purchase_responsible', 'Aprobación del Responsable de proveedores'),
                               ('approved_director', 'Aprobación del Director Gerente'),
                               ('approve', 'Aprobada'), ("rejected", 'Rechazada')
                               ], 'Estado',
                              default='approved_by_boss_group', tracking=True)
    is_more = fields.Boolean(string='Es más de 10000€', default=True)
    invoice_created = fields.Many2one('account.move', string='Invoice Created')
    invoice_count = fields.Integer(default=1, string='Invoice Count')
    inmovilizado_type = fields.Selection([
        ('computer_equipment', 'Equipo informático'),
        ('furniture', 'Mobiliario'),
        ('other', 'Otro'),], string='Tipo de Inmovilizado')

    @api.depends('status')
    def _compute_show_solicitar_revision(self):
        is_boss = self.env.user.has_group('portal_requests.group_equip_boss') or self.env.user.has_group(
            'portal_requests.group_partner_responsible')
        for rec in self:
            if rec.status == 'to_revise' and not is_boss:
                print("Setting show_solicitar_revision to True for record ID:", rec.id)
            else:
                print("Setting show_solicitar_revision to False for record ID:", rec.id)
            rec.show_solicitar_revision = (rec.status == 'to_revise') and (not is_boss)

    show_solicitar_revision = fields.Boolean(
        string='Mostrar Solicitar Revisión',
        compute='_compute_show_solicitar_revision',
        store=False,
    )

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

    def action_approve(self):
        if self.env.user.has_group('portal_requests.group_equip_boss') and self.status == 'approved_by_boss_group':
            self.status = 'approved_purchase_responsible'
            user_to_notify = self.env['res.users'].search(
                [('work_group_ids', 'in', [self.env.ref('portal_requests.group_purchase_responsible').id])])
            self._send_purchase_request_mail('approved_by_boss_group', user_to_notify, self.user_id.name, self.project.name)
            return self.show_notificacion("¡Aprobación registrada!", "La solicitud ha sido aprobada y enviada al responsable de compras para su revisión.", "success")
        elif self.env.user.has_group('portal_requests.group_purchase_responsible') and self.status == 'approved_purchase_responsible':
            #si no supera los 10k y el saldo del equipo es mayor a 0:
            balance_group = self._get_balance_work_group()
            if self.is_more:
                self.status = 'approved_director'
                user_to_notify = self.env['res.users'].search(
                    [('work_group_ids', 'in', self.env.ref('portal_requests.group_director_manager').id)])
                self._send_purchase_request_mail('approved_purchase_responsible', user_to_notify, self.user_id.name,
                                                 self.project.name)
                return self.show_notificacion("¡Aprobación registrada!",
                                              "La solicitud ha sido aprobada y enviada al director gerente para su revisión.",
                                              "success")
            elif balance_group <= 0:
                self.status = 'approved_director'
                user_to_notify = self.env['res.users'].search(
                    [('work_group_ids', 'in', self.env.ref('portal_requests.group_director_manager').id)])
                self._send_purchase_request_mail('approved_purchase_responsible', user_to_notify, self.user_id.name,
                                                 self.project.name)
                return self.show_notificacion("¡Aprobación registrada!",
                                              "La solicitud ha sido aprobada y enviada al director gerente para su revisión.",
                                              "success")
            else:
                self.status = 'approve'
                self._create_purchase_invoice()
                return self.show_notificacion("¡Solicitud aprobada!",
                                              "La factura borrador ha sido creada correctamente.", "success")
                # CREATE LA FACTURA EN BLANCO CON EL ADJUNTO Y LA DISTRIBUCION CONTABLE


        elif self.env.user.has_group('portal_requests.group_director_manager') and self.status == 'approved_director':
            self.status = 'approve'
            #CREATE LA FACTURA EN BLANCO CON EL ADJUNTO Y LA DISTRIBUCION CONTABLE
            self._create_purchase_invoice()
            return self.show_notificacion("¡Solicitud aprobada!", "La factura borrador ha sido creada correctamente.",
                                          "success")

        elif self.status == 'to_revise':
            if self.equip_boss == self.user_id:
                user_to_notify = self.env['res.users'].search([('groups_id', 'in', self.env.ref('portal_requests.group_purchase_responsible').id)])
                self.status = 'approved_purchase_responsible'
            else:
                user_to_notify = [self.work_group_id.equip_boss]
                self.status = 'approved_by_boss_group'
            self._send_purchase_request_mail('to_revise', user_to_notify, self.user_id.name, self.project.name)
            return self.show_notificacion("¡Nueva Revision!",
                                          "Su solicitud de nueva revision ha sido registrada correctamente.",
                                          "success")
        print("Approved HR Expensive Request")

    # def action_reject(self):
    #     print("Rejected HR Expensive Request")

    def _get_balance_work_group(self):
        self.ensure_one()
        work_group = self.work_group_id
        balance = 0.0
        if work_group:
            analytic_accounts = self.env['account.analytic.account'].search([('work_group_id', '=', work_group.id)])
            for account in analytic_accounts:
                balance += account.balance
        return balance

    def _create_purchase_invoice(self):
        self.ensure_one()
        # Lógica para crear la factura de compra en blanco con el adjunto y la distribución contable
        # El analytic_distribution debe ser un JSON con formato: {str(account_id): percentage}
        analytic_distribution = {str(self.project.id): 100.0}

        invoice_vals = {
            # 'partner_id': self.project.partner_id.id,
            'move_type': 'in_invoice',
            'analytic_distribution': analytic_distribution,
        }
        invoice = self.env['account.move'].create(invoice_vals)
        #añadimos el adjunto de la solicitud a la factura
        attachments = self.env['ir.attachment'].search([('res_model', '=', 'portal.hr.expensive.request'), ('res_id', '=', self.id)])
        for attachment in attachments:
            attachment.write({
                'res_model': 'account.move',
                'res_id': invoice.id,
            })
        self.invoice_created = invoice.id

    def action_reject(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rechazar solicitud de gasto',
            'res_model': 'purchase.request.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_id': self.id,
            }
        }

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

    def action_to_revise(self):
        for record in self:
            record.is_revised = False

    def _send_purchase_request_mail(self,type, users_to_send, user_name, company_name, notes=""):
            expensive_request_link = f"/web#id={self.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=portal.hr.expensive.request&view_type=form"
            if type == 'to_revise':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>Se ha solicitado una nueva revisión de la solicitud de gasto, por parte de {user_name}.</p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{expensive_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Nueva Revisión de Gasto',
                        'email_from': self.env.user.email or '',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].create(mail_values)
                    mail.send()
            elif type == 'approved_by_boss_group':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>La solicitud de gasto en el proyecto {company_name} ha sido aprobada por el jefe de equipo ({user_name}).</p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{expensive_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Solicitud de gasto',
                        'email_from': self.env.user.email or 'no-reply@example.com',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].create(mail_values)
                    mail.send()
            elif type == 'rejected':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>La solicitud de gasto en el proyecto {company_name} ha sido rechazada por el siguiente motivo:</p>
                                <p><em>{notes}</em></p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{expensive_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Solicitud de gasto',
                        'email_from': self.env.user.email or 'no-reply@example.com',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].create(mail_values)
                    mail.send()
            elif type == 'approved_purchase_responsible':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>La solicitud de gasto en el proyecto {company_name} ha sido aprobada por el responsable de compras ({user_name}).</p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{expensive_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Solicitud de gasto',
                        'email_from': self.env.user.email or 'no-reply@example.com',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].create(mail_values)
                    mail.send()



