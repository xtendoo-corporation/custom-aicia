from odoo import api, fields, models

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    other_field = fields.Many2many('employee.attribute', string='Información adicional')
    partner_id = fields.Many2one('res.partner', string='Contacto', compute='_compute_partner_id', store=True)

    def _compute_partner_id(self):
        for record in self:
            record.partner_id = self.env['res.partner'].search([('id', '=', record.work_contact_id.id)], limit=1)
