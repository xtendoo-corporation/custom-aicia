from odoo import models, fields, tools, _
import base64


class PortalRequestDashboard(models.Model):
    _name = 'portal.request.dashboard'
    _description = 'Portal Request Dashboard'

    name = fields.Char(string='Name', required=True)
    type = fields.Char(string='Type')
    model = fields.Char(string='Model')
    count_unapproved = fields.Integer(string='Count Rejected', compute='_compute_count_unapproved')
    unaproved_text = fields.Char(string='Unapproved Text', compute='_compute_unapproved_text')

    count_approved = fields.Integer(string='Count Approved', compute='_compute_count_approved')
    approved_text = fields.Char(string='Approved Text', compute='_compute_approved_text')

    count_to_revise = fields.Integer(string='Count To revise', compute='_compute_count_to_revise')
    # to_revise_action = fields.Many2one('ir.actions.act_window', string="Action to Revise" ,compute='_compute_to_revise_action_id')
    to_revise_text = fields.Char(string='To revise Text', compute='_compute_to_revise_text')

    # document_approval_ids = fields.One2many('document.approval', 'type_id', string='Document Approvals')
    image = fields.Binary(string='Image')
    # To revise
    def open_new_action_to_revise(self):
        self.ensure_one()
        if self.model == 'document.approval':
            return self.open_to_revise_document()
        elif self.model == 'portal.project.request':
            return self.open_to_revise_project()
        elif self.model == 'portal.invoice.request':
            if self.type == 'out_invoice':
                return self.open_to_revise_invoice()
            else:
                return self.open_to_revise_invoice_refund()
        # elif self.model == 'portal.hr.employee.request':
        #     return self.open_to_revise_employee()

    def open_to_revise_document(self):
        return {
            'name': _('Documentos para revisar'),
            'type': 'ir.actions.act_window',
            'res_model': 'document.approval',
            'view_mode': 'tree,form',
            'domain': [('is_revised', '=', False)],
            'context': {'group_by': 'type_id'},
        }
    def open_to_revise_project(self):
        return {
            'name': _('Proyectos para revisar'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.project.request',
            'view_mode': 'tree,form',
            'domain': [('is_revised', '=', False)],
            'context': {'group_by': 'company_id'},
        }
    def open_to_revise_invoice(self):
        return {
            'name': _('Facturas para revisar'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.invoice.request',
            'view_mode': 'tree,form',
            'domain': [('is_revised', '=', False), ('move_type', '=', 'out_invoice')],
            'context': {'group_by': 'company_id'},
        }
    def open_to_revise_invoice_refund(self):
        return {
            'name': _('Facturas rectificativas para revisar'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.invoice.request',
            'view_mode': 'tree,form',
            'domain': [('is_revised', '=', False), ('move_type', '=', 'out_refund')],
            'context': {'group_by': 'company_id'},
        }

    # def open_to_revise_employee(self):
    #     return {
    #         'name': _('Contratos para revisar'),
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'portal.hr.employee.request',
    #         'view_mode': 'tree,form',
    #         'domain': [('is_revised', '=', False)],
    #         'context': {'group_by': 'company_id'},
    #     }

    #Approved
    def open_new_action_approve(self):
        self.ensure_one()
        if self.model == 'document.approval':
            return self.open_approved_document()
        elif self.model == 'portal.project.request':
            return self.open_approved_project()
        elif self.model == 'portal.invoice.request':
            if self.type == 'out_invoice':
                return self.open_approved_invoice()
            else:
                return self.open_approved_invoice_refund()
        # elif self.model == 'portal.hr.employee.request':
        #     return self.open_approved_employee()

    def open_approved_document(self):
        return {
            'name': _('Documentos Aprobados'),
            'type': 'ir.actions.act_window',
            'res_model': 'document.approval',
            'view_mode': 'tree,form',
            'domain': [('approved', '=', True)],
            'context': {'group_by': 'type_id'},
        }
    def open_approved_project(self):
        return {
            'name': _('Proyectos Aprobados'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.project.request',
            'view_mode': 'tree,form',
            'domain': [('approved', '=', True), ('is_revised', '=', True)],
            'context': {'group_by': 'company_id'},
        }
    def open_approved_invoice(self):
        return {
            'name': _('Facturas Aprobadas'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.invoice.request',
            'view_mode': 'tree,form',
            'domain': [('approved', '=', True), ('move_type', '=', 'out_invoice')],
            'context': {'group_by': 'company_id'},
        }
    def open_approved_invoice_refund(self):
        return {
            'name': _('Facturas rectificativas Aprobadas'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.invoice.request',
            'view_mode': 'tree,form',
            'domain': [('approved', '=', True), ('move_type', '=', 'out_refund')],
            'context': {'group_by': 'company_id'},
        }

    # def open_approved_employee(self):
    #     return {
    #         'name': _('Contratos Aprobados'),
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'portal.hr.employee.request',
    #         'view_mode': 'tree,form',
    #         'domain': [('approved', '=', True), ('is_revised', '=', True)],
    #         'context': {'group_by': 'company_id'},
    #     }

    #Rejected
    def open_new_action_rejected(self):
        self.ensure_one()
        if self.model == 'document.approval':
            return self.open_rejected_document()
        elif self.model == 'portal.project.request':
            return self.open_rejected_project()
        elif self.model == 'portal.invoice.request':
            if self.type == 'out_invoice':
                return self.open_rejected_invoice()
            else:
                return self.open_rejected_invoice_refund()
        # elif self.model == 'portal.hr.employee.request':
        #     return self.open_rejected_employee()

    def open_rejected_document(self):
        return {
            'name': _('Documentos Rechazados'),
            'type': 'ir.actions.act_window',
            'res_model': 'document.approval',
            'view_mode': 'tree,form',
            'domain': [('approved', '=', False), ('is_revised', '=', True)],
            'context': {'group_by': 'type_id'},
        }
    def open_rejected_project(self):
        return {
            'name': _('Proyectos Rechazados'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.project.request',
            'view_mode': 'tree,form',
            'domain': [('approved', '=', False), ('is_revised', '=', True)],
            'context': {'group_by': 'company_id'},
        }
    def open_rejected_invoice(self):
        return {
            'name': _('Facturas Rechazadas'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.invoice.request',
            'view_mode': 'tree,form',
            'domain': [('approved', '=', False), ('is_revised', '=', True), ('move_type', '=', 'out_invoice')],
            'context': {'group_by': 'company_id'},
        }
    def open_rejected_invoice_refund(self):
        return {
            'name': _('Facturas rectificativas Rechazadas'),
            'type': 'ir.actions.act_window',
            'res_model': 'portal.invoice.request',
            'view_mode': 'tree,form',
            'domain': [('approved', '=', False), ('is_revised', '=', True), ('move_type', '=', 'out_refund')],
            'context': {'group_by': 'company_id'},
        }

    # def open_rejected_employee(self):
    #     return {
    #         'name': _('Contratos Rechazados'),
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'portal.hr.employee.request',
    #         'view_mode': 'tree,form',
    #         'domain': [('approved', '=', False), ('is_revised', '=', True)],
    #         'context': {'group_by': 'company_id'},
    #     }

    def _compute_to_revise_text(self):
        for record in self:
            number= record.count_to_revise
            number= str(number)
            record.to_revise_text = _('Para revisar: %s', number)

    def _compute_count_to_revise(self):
        for record in self:
            if record.model == 'portal.project.request':
                record.count_to_revise = self.env['portal.project.request'].search_count(
                    [('is_revised', '=', False)])
            elif record.model == 'portal.invoice.request':
                if record.type == 'out_invoice':
                    record.count_to_revise = self.env['portal.invoice.request'].search_count(
                        [('is_revised', '=', False),('move_type', '=', 'out_invoice')])
                else:
                    record.count_to_revise = self.env['portal.invoice.request'].search_count(
                        [('is_revised', '=', False), ('move_type', '=', 'out_refund')])
            elif record.model == 'document.approval':
                record.count_to_revise = self.env['document.approval'].search_count(
                    [('is_revised', '=', False)])
            # elif record.model == 'portal.hr.employee.request':
            #     record.count_to_revise = self.env['portal.hr.employee.request'].search_count(
            #         [('is_revised', '=', False)])

    def _compute_approved_text(self):
        for record in self:
            number= record.count_approved
            number= str(number)
            if record.model == 'portal.project.request':
                record.approved_text = _('Aprobados: %s', number)
            elif record.model == 'portal.invoice.request':
                record.approved_text = _('Aprobadas: %s', number)
            elif record.model == 'document.approval':
                record.approved_text = _('Aprobados: %s', number)
            # elif record.model == 'portal.hr.employee.request':
            #     record.approved_text = _('Aprobados: %s', number)

    def _compute_count_approved(self):
        for record in self:
            if record.model == 'portal.project.request':
                record.count_approved = self.env['portal.project.request'].search_count(
                    [('approved', '=', True), ('is_revised', '=', True)])
            elif record.model == 'portal.invoice.request':
                if record.type == 'out_invoice':
                    record.count_approved = self.env['portal.invoice.request'].search_count(
                        [('approved', '=', True), ('is_revised', '=', True),('move_type', '=', 'out_invoice')])
                else:
                    record.count_approved = self.env['portal.invoice.request'].search_count(
                        [('approved', '=', True), ('is_revised', '=', True), ('move_type', '=', 'out_refund')])
            elif record.model == 'document.approval':
                record.count_approved = self.env['document.approval'].search_count(
                    [('approved', '=', True), ('is_revised', '=', True)])
            # elif record.model == 'portal.hr.employee.request':
            #     record.count_approved = self.env['portal.hr.employee.request'].search_count(
            #         [('approved', '=', True), ('is_revised', '=', True)])


    def _compute_unapproved_text(self):
        for record in self:
            number= record.count_unapproved
            number= str(number)
            if record.model == 'portal.project.request':
                record.unaproved_text = _('Rechazados: %s', number)
            elif record.model == 'portal.invoice.request':
                record.unaproved_text = _('Rechazadas: %s', number)
            elif record.model == 'document.approval':
                record.unaproved_text = _('Rechazados: %s', number)
            # elif record.model == 'portal.hr.employee.request':
            #     record.unaproved_text = _('Rechazados: %s', number)


    def _compute_count_unapproved(self):
        for record in self:
            if record.model == 'portal.project.request':
                record.count_unapproved = self.env['portal.project.request'].search_count(
                    [('approved', '=', False), ('is_revised', '=', True)])
            elif record.model == 'portal.invoice.request':
                if record.type == 'out_invoice':
                    record.count_unapproved = self.env['portal.invoice.request'].search_count(
                        [('approved', '=', False), ('is_revised', '=', True),('move_type', '=', 'out_invoice')])
                else:
                    record.count_unapproved = self.env['portal.invoice.request'].search_count(
                        [('approved', '=', False), ('is_revised', '=', True), ('move_type', '=', 'out_refund')])
            elif record.model == 'document.approval':
                record.count_unapproved = self.env['document.approval'].search_count(
                    [('approved', '=', False), ('is_revised', '=', True)])
            # elif record.model == 'portal.hr.employee.request':
            #     record.count_unapproved = self.env['portal.hr.employee.request'].search_count(
            #         [('approved', '=', False), ('is_revised', '=', True)])


