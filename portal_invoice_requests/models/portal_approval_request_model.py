from odoo import models, fields, api

class PortalApprovalRequest(models.Model):
    _name = 'portal.approval.request'
    _description = 'Portal Approval Request'

    name = fields.Char(string='Request Name', compute='_compute_name', store=True)
    approval_type = fields.Selection([
        ('sign_nda', 'Solicitud firma NDA'),
        ('business_contract', 'Solicitud firma contrato con empresa'),
        ('collaboration_pas', 'Solicitud colaboración PAS'),
        ('exit_authorization', 'Solicitud autorización salida a empresas'),
        ('travel_request', 'Solicitud de salida de viaje'),
    ], string='Approval Type', required=True)
    description = fields.Text(string='Description')

    user_id = fields.Many2one('res.users', string='User', required=True)  # Este campo debe existir.


    # category_id = fields.Many2one('document.page', string="Document Category")  # Relación con document.page
    # @api.depends('approval_type')
    # def _compute_name(self):
    #     for record in self:
    #         record.name = dict(self._fields['approval_type'].selection).get(record.approval_type, 'Solicitud')


