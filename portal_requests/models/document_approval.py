from odoo import models, fields

class DocumentApproval(models.Model):
    _name = 'document.approval'
    _description = 'Document Approval'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    type_id = fields.Many2one('type.approval', string='Type', required=True)
    description = fields.Text(string='Description')
    approved = fields.Boolean(string='Approved', default=False)
    group_approval_id = fields.Many2one('res.groups', string='Group Approval')
    is_revised = fields.Boolean(string='Is revised', default=False, store=True)

    def action_approve(self):
        for record in self:
            record.approved = True
            record.is_revised = True

    def action_reject(self):
        for record in self:
            record.approved = False
            record.is_revised = True

    def action_to_revise(self):
        for record in self:
            record.is_revised = False
