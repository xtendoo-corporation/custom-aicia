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
        elif self.env.user.has_group('portal_requests.group_purchase_responsible') and self.status == 'approved_purchase_responsible':
            self.status = 'approved_director'
        elif self.env.user.has_group('portal_requests.group_director_manager') and self.status == 'approved_director':
            self.status = 'approve'
        print("Approved HR Expensive Request")

    # def action_reject(self):
    #     print("Rejected HR Expensive Request")

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

    def action_to_revise(self):
        for record in self:
            record.is_revised = False



