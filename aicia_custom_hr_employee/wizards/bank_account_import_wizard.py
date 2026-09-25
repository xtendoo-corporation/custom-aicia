from odoo import api, fields, models
import base64
import xlrd
from odoo.exceptions import UserError


class ImportEmployeeBankAccountWizard(models.TransientModel):
    _name = 'import.employee.bank.account.wizard'
    _description = 'Wizard para importar cuentas bancarias de empleados desde un archivo XLS'

    file = fields.Binary('Subir archivo XLS', required=True)
    file_name = fields.Char('Nombre del archivo')

    def action_open_import_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Importar Cuentas Bancarias',
            'res_model': 'import.employee.bank.account.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_import_employee_bank_accounts(self):
        if not self.file:
            raise UserError("Por favor, sube un archivo XLS.")

        # Decodificar el archivo XLS
        data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)

        for row in range(1, sheet.nrows):
            row_values = sheet.row_values(row)
            print(f"Fila {row}: {row_values}")
            employee_id = sheet.cell(row, 2).value  # ID del empleado o referencia
            print("*" * 80)
            print(f"Procesando empleado con ID: {employee_id}")
            iban = sheet.cell(row, 26).value.strip() if sheet.cell(row, 26).value else None  # IBAN
            print(f"IBAN: {iban}")

            if not employee_id or not iban:
                print("Empleado ID o IBAN está vacío. Saltando esta fila.")
                continue

            # Buscar el empleado por ID o referencia
            employee = self.env['hr.employee'].search([('identification_id', '=', employee_id)], limit=1)

            if employee:

                print("*" * 80)
                print(f"Empleado encontrado: {employee.name}")
                print(f"IBAN: {iban}")
                print(f"PARTNER ID: {employee.partner_id}")
                existing_bank_record = self.env['res.partner.bank'].search(
                    [('acc_number', '=', iban), ('partner_id', '=', employee.partner_id.id)], limit=1)
                # resto de datos
                employee.partner_id.phone = employee.work_phone
                employee.partner_id.mobile = employee.mobile_phone
                employee.partner_id.vat = employee.identification_id
                employee.partner_id.email = employee.work_email
                employee.partner_id.street = employee.private_street
                employee.partner_id.city = employee.private_city
                employee.partner_id.zip = employee.private_zip
                if not existing_bank_record:
                    print("*" * 80)
                    print(f"Creando cuenta bancaria para {employee.name}")
                    print(f"PARTNER ID: {employee.partner_id}")
                    # Crear nueva cuenta bancaria si no existe
                    self.env['res.partner.bank'].create({
                        'acc_number': iban,
                        'partner_id': employee.partner_id.id,
                    })
                    print(f"Cuenta bancaria creada: {iban} para {employee.name}")
                else:
                    print(f"La cuenta bancaria con IBAN: {iban} ya existe para {employee.name}. No se crea una nueva.")

            else:
                print(f"No se encontró el empleado con ID: {employee_id}")

        # Limpiar la sesión de base de datos
        self.env.cr.flush()
