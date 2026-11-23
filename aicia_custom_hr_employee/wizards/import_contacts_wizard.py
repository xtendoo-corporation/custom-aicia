from odoo import api, fields, models, _
import base64
import xlrd
from odoo.exceptions import UserError


class ImportContactsWizard(models.TransientModel):
    _name = 'import.contacts.wizard'
    _description = 'Wizard para importar contactos desde un archivo XLS'

    file = fields.Binary('Subir archivo XLS', required=True)
    file_name = fields.Char('Nombre del archivo')

    def action_import_contacts(self):
        if not self.file:
            raise UserError("Por favor, sube un archivo XLS.")

        # Decodificar el archivo XLS
        data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)

        for row in range(1, sheet.nrows):
            row_values = sheet.row_values(row)
            country_name = str(row_values[9]) if row_values[9] else False
            # Buscar el ID del país
            country_id = self.env['res.country'].search([('name', '=', country_name)], limit=1).id
            if row_values[0] != '':
                contact_data = {
                    'name': row_values[0],
                    'comercial': row_values[1],
                    'vat': row_values[2],
                    'phone': row_values[3],
                    'mobile': row_values[4],
                    'street': row_values[5],
                    'street2': row_values[6],
                    'city': row_values[7],
                    'zip': row_values[8],
                    'country_id': country_id,
                    'comment': row_values[10],
                    'email': row_values[12],
                    'is_company': True
                }
                self.create_contact(contact_data)

        # Limpiar la sesión de base de datos
        self.env.cr.flush()

    def create_contact(self, contact_data):
        try:
            self.env['res.partner'].create(contact_data)
            return True
        except Exception as e:
            print(f"Error al crear el cliente %s. {e}", contact_data['name'])
            return False
