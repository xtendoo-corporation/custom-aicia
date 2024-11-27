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
    approver_id = fields.Many2one(
        'res.users',
        string='Approver',
        required=True,
    )

    file = fields.Binary(string='File', attachment=True, required=True)
    file_name = fields.Char(string='File name')
    description = fields.Text(string='Description')


    @api.depends('approval_type')
    def _compute_name(self):
        """Genera un nombre basado en el tipo de solicitud."""
        for record in self:
            record.name = dict(self._fields['approval_type'].selection).get(record.approval_type, 'Solicitud')



    # category_id = fields.Many2one('approval.category', string='Category', required=True)

    # response = fields.Text(string='Response')
    # response_date = fields.Datetime(string='Response Date')
    # response_user_id = fields.Many2one('res.users', string='Response User')
    # response_message = fields.Text(string='Response Message')
    # response_attachment = fields.Binary(string='Response Attachment', attachment=True)

