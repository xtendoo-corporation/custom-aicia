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
