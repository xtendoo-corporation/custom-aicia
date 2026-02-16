from odoo import models, api, _, fields

class HrEmployee(models.Model):
    _inherit = "hr.employee"

    codigo_empleado = fields.Char(string='Código de Empleado')

    apply_retention = fields.Boolean(
        string='Aplica Retención',
        default=False,
    )
    permission_to_desplace = fields.Boolean(
        string='Permiso de desplazamiento',
        default=False,
    )
    confidentiality_agreement = fields.Boolean(
        string='Confidencialidad',
        default=False,
    )
    other_field = fields.Many2many('employee.attribute', string='Información adicional')

    # partner_id = fields.Char(string="Contacto")

    partner_id = fields.Many2one('res.partner', string="Contacto", compute="_compute_partner_id", store=True)

    def _compute_partner_id(self):
        for record in self: (
            record.partner_id) = self.env['res.partner'].search([('id', '=', record.work_contact_id.id)], limit=1)
