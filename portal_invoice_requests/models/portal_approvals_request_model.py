from odoo import models, fields, api

class PortalApprovalRequest(models.Model):
    _name = 'portal.approval.request'
    _description = 'Portal Approval Request'

    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True)
    approval_type = fields.Selection([
        ('sign_nda', 'Solicitud firma NDA'),
        ('business_contract', 'Solicitud firma contrato con empresa'),
        ('collaboration_pas', 'Solicitud colaboración PAS'),
        ('exit_authorization', 'Solicitud autorización salida a empresas'),
        ('travel_request', 'Solicitud de salida de viaje'),
    ], string='Approval Type', required=True)

    approver_id = fields.Many2one('approval.approver', string='Approver', required=True)



    # category_id = fields.Many2one('approval.category', string='Category', required=True)

    # response = fields.Text(string='Response')
    # response_date = fields.Datetime(string='Response Date')
    # response_user_id = fields.Many2one('res.users', string='Response User')
    # response_message = fields.Text(string='Response Message')
    # response_attachment = fields.Binary(string='Response Attachment', attachment=True)

