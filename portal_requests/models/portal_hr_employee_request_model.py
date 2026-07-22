from odoo import models, fields, api, _
#configurar como correo entrante compras.aicia@xtendoo.es


class PortalHrEmployeeRequest(models.Model):
    _name = 'portal.hr.employee.request'
    _description = 'Portal HR Employee Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.request.notify.mixin']

    user_id = fields.Many2one('res.users', string='User', required=True)
    name = fields.Char(string='Employee Name', required=True)
    identification_id = fields.Char(string='Identification')
    mobile_phone = fields.Char(string='Mobile')
    ssnid = fields.Char(string='SSN ID')
    confidential_compromise = fields.Boolean(string='Confidential Compromise')
    working_life_report = fields.Binary(string="Working Life Report", attachment=True)
    working_life_report_filename = fields.Char(string="Working Life Report Filename")
    cv = fields.Binary(string="CV", attachment=True)
    cv_filename = fields.Char(string="CV Filename")
    work_email = fields.Char(string='Work Email')
    prl_annex = fields.Binary(string="PRL Annex", attachment=True)
    prl_annex_filename = fields.Char(string="PRL Annex Filename")
    # study_field = fields.Char(string='Study Field', required=True)
    # job_id = fields.Many2one('hr.job', string='Job', required=True)
    salary = fields.Float(string='Salary')
    number_of_pays = fields.Integer(string='Number of Pays')
    resource_calendar_id = fields.Many2one('resource.calendar', string='Resource Calendar',)
    # Context {'default_partner_id': work_contact_id} Domain [('partner_id', '=', work_contact_id), | ('company_id', '=', False), | ('company_id', '=', company_id)]
    bank_account = fields.Char(string='Bank Account')
    company_id = fields.Many2one('res.company', string='Project', required=True)#Esto tendrá un domain de team_work_id
    is_revised = fields.Boolean(string='Is revised', default=False, store=True)
    approved = fields.Boolean(string='Approved', default=False)
    type=fields.Selection([
        ('new', 'Nuevo'),
        ('alta', 'Alta'),
        ('baja', 'Baja'),
    ], string='Type', required=True)
    employee_created = fields.Many2one('hr.employee', string='Employee Created')
    employee_id = fields.Many2one('hr.employee', string='Empleado')
    employee_count = fields.Integer(default=1, string='Employee Count')
    alta_date = fields.Date(string='Fecha de alta')
    baja_date = fields.Date(string='Fecha de baja')
    baja_reason_id = fields.Many2one("hr.departure.reason",
                                          default=lambda self: self.env['hr.departure.reason'].search([], limit=1),
                                          )
    baja_description = fields.Html(string="Información adicional")


    def show_notificacion(self, title_char, text, type_char):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': type_char,
                'message': text,
                'title': title_char,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_approve(self):
        for record in self:
            notification_text = ""
            if record.type == 'new':
                record.employee_created = record.action_create_employee()
                notification_text = _("El empleado %s ha sido creado correctamente.") % record.employee_id.name
            elif record.type == 'alta':
                print("alta")
                record.employee_id.active = True
                record.employee_created = record.employee_id
                notification_text = _("El empleado %s ha sido dado de alta correctamente.") % record.employee_id.name
            elif record.type == 'baja':
                print("baja")
                record.action_baja_employee()
                record.employee_created = record.employee_id
                notification_text = _("El empleado %s ha sido dado de baja correctamente.") % record.employee_id.name
            record.approved = True
            record.is_revised = True
        self._notify_requester_state(_("Aprobada"))
        return self.show_notificacion("¡Solicitud aprobada!", notification_text, "success")


    def action_create_employee(self):
        print("*" * 100)
        print("action_create_employee")
        employee = self.env['hr.employee'].create({
            'name': self.name,
            'identification_id': self.identification_id,
            'mobile_phone': self.mobile_phone,
            'ssnid': self.ssnid,
            # 'confidential_compromise': self.confidential_compromise,
            'work_email': self.work_email,
            'company_id': self.company_id.id,
            'resource_calendar_id': self.resource_calendar_id.id,
            # 'active': False,
            'employee_type': 'employee',
            # 'bank_account': self.bank_account,
            # 'salary': self.salary,
            # 'number_of_pays': self.number_of_pays,
        })
        request_attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'portal.hr.employee.request'),
            ('res_id', '=', self.id),
        ])
        print("request_attachment", request_attachment)
        for attachment in request_attachment:
            self.env['ir.attachment'].create({
                'name': attachment.name,
                'res_model': 'hr.employee',
                'res_id': employee.id,
                'datas': attachment.datas,
                'type': attachment.type,
            })

        return employee

    def action_baja_employee(self):
        request_wizard = self.env['hr.departure.wizard'].create({
            'employee_id': self.employee_id.id,
            'departure_reason_id': self.baja_reason_id.id,
            'departure_description': self.baja_description,
            'departure_date': self.baja_date,
        })
        self.employee_id.active=False

    # def action_alta_employee(self):

    def action_reject(self):
        for record in self:
            record.approved = False
            record.is_revised = True
        self._notify_requester_state(_("Rechazada"))

    def action_to_revise(self):
        for record in self:
            record.is_revised = False
        self._notify_requester_state(_("En revisión"))

    def action_view_employee(self):
        self.ensure_one()
        employee = self.employee_created.ids
        action = {
            "res_model": "hr.employee",
            "type": "ir.actions.act_window",
        }
        if len(employee) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": employee[0],
                }
            )
        else:
            action.update(
                {
                    "name": "Empleados",
                    "domain": [("id", "in", employee)],
                    "view_mode": "tree,form",
                }
            )
        return action












