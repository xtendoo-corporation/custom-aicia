from odoo import models, fields, api
#configurar como correo entrante compras.aicia@xtendoo.es


class PortalHrEmployeeRequest(models.Model):
    _name = 'portal.hr.employee.request'
    _description = 'Portal HR Employee Request'

    name = fields.Char(string='Employee Name', required=True)
    identification_id = fields.Char(string='Identification', required=True)
    mobile_phone = fields.Char(string='Mobile', required=True)
    ssnid = fields.Char(string='SSN ID', required=True)
    confidential_compromise = fields.Boolean(string='Confidential Compromise', required=True)
    working_life_report = fields.Binary(string="Working Life Report", attachment=True)#revisar
    cv = fields.Binary(string="CV", attachment=True)#revisar
    work_email = fields.Char(string='Work Email', required=True)
    prl_annex = fields.Binary(string="PRL Annex", attachment=True)#revisar
    employee_type = fields.Many2one('hr.contract.type', string='Employee Type', required=True)
    study_field = fields.Char(string='Study Field', required=True)
    job_id = fields.Many2one('hr.job', string='Job', required=True)
    salary = fields.Float(string='Salary', required=True)
    number_of_pays = fields.Integer(string='Number of Pays', required=True)
    resource_calendar_id = fields.Many2one('resource.calendar', string='Resource Calendar', required=True)
    # Context {'default_partner_id': work_contact_id} Domain [('partner_id', '=', work_contact_id), | ('company_id', '=', False), | ('company_id', '=', company_id)]
    bank_account_id = fields.Many2one('res.partner.bank', string='Bank Account', required=True)
    team_work_id = fields.Many2one('res.company', string='Team Work', required=True)#Esto tendrá un domain
    project_id = fields.Many2one('res.company', string='Project', required=True)#Esto tendrá un domain de team_work_id












