from odoo import api, fields, models, _

class EmployeeAttribute(models.Model):
    _name = 'employee.attribute'
    _description = 'Employee Attribute'

    name = fields.Char(string='Attribute Name')
