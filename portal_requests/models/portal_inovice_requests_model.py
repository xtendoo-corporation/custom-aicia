from odoo import models, fields, api, _


class PortalInvoiceRequest(models.Model):
    _name = 'portal.invoice.request'
    _description = 'Portal Invoice Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
    send_draft = fields.Boolean(string='Send Draft Invoice', default=False)
    status = fields.Selection([('to_revise', 'Volver a revisar'),
                               ('approved_by_boss_group', 'Aprobación del Jefe de Equipo'),
                               ('approved_by_client_responsible', 'Aprobación del Responsable de clientes'),
                               ('approve', 'Aprobada'), ("rejected", 'Rechazada')
                               ], 'Estado',
                              default='approved_by_boss_group', tracking=True)

    def _compute_name(self):
        for record in self:
            record.computed_name = F"Solicitud de Factura para {record.analytic_id.name}"

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
        if self.status=='approved_by_boss_group':
            self.status = 'approved_by_client_responsible'
            return self.show_notificacion("¡Aprobación registrada!", "La solicitud ha sido aprobada y enviada al responsable de clientes para su revisión.", "success")
        if self.status=='approved_by_client_responsible':
            self.status = 'approve'
        for record in self:
            record.add_group_boss_to_followers()
            record.approved = True
            record.is_revised = True
            record.create_invoice()
        return self.show_notificacion("¡Solicitud aprobada!", "La factura ha sido creada correctamente.", "success")

    def action_reject(self):
        for record in self:
            record.approved = False
            record.is_revised = True

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
        self.invoice_created.add_group_boss_to_followers(group)

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


    def add_group_boss_to_followers(self):
        group = self.analytic_id.work_group_id
        if not group:
            return
        boss = group.user_ids.filtered(lambda u: u.has_group('portal_requests.group_equip_boss'))
        if boss:
            print("*"*100)
            print("Adding boss to followers:", boss.name)
            print("*"*100)
            self.message_subscribe(partner_ids=[boss.partner_id.id])

