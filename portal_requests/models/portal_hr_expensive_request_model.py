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



