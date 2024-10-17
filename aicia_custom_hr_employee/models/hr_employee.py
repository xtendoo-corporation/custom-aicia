from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    other_field = fields.Many2many('employee.attribute', string='Información adicional')

    partner_id = fields.Many2one('res.partner', string="Contacto", compute="_compute_partner_id", store=True)
    partner_id_2 = fields.Many2one('res.partner', string="Contacto 2", compute="_compute_partner_id_2", store=True)

    def _compute_partner_id(self):
        for record in self:
            record.partner_id = self.env['res.partner'].search([('work_contact_id', '=', record.id)], limit=1)

    def _compute_partner_id_2(self):
        for record in self:
            record.partner_id = self.env['res.partner'].search([('id', '=', record.work_contact_id.id)], limit=1)
