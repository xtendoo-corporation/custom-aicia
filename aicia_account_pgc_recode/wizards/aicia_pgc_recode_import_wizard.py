import base64

from odoo import _, fields, models
from odoo.exceptions import UserError


class AiciaAccountPgcRecodeImportWizard(models.TransientModel):
    _name = 'aicia.account.pgc.recode.import.wizard'
    _description = 'Importar reglas de recodificación PGC'

    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    file = fields.Binary('Archivo', required=True)
    filename = fields.Char('Nombre del archivo')
    clear_existing_rules = fields.Boolean('Eliminar reglas existentes', default=False)

    def action_import(self):
        self.ensure_one()

        if not self.file:
            raise UserError(_("Debes subir un archivo."))

        if self.clear_existing_rules:
            self.env['aicia.account.pgc.recode.rule'].search([('company_id', '=', self.company_id.id)]).unlink()

        file_content = base64.b64decode(self.file)

        parser_model = self.env['aicia.account.pgc.recode.rule']
        rules_data = parser_model.parse_rules_file(file_content, filename=self.filename)
        rules_to_create = [
            {
                'company_id': self.company_id.id,
                'old_code': rule_data['old_code'],
                'old_name': rule_data['old_name'],
                'target_prefix': rule_data['target_prefix'],
                'target_label': rule_data['target_label'],
                'notes': rule_data['notes'],
                'status': rule_data['status'],
                'source_row': rule_data['source_row'],
            }
            for rule_data in rules_data
        ]

        if not rules_to_create:
            raise UserError(_("No se han encontrado reglas válidas en el archivo subido."))

        created_rules = self.env['aicia.account.pgc.recode.rule'].create(rules_to_create)

        created_rules._finalize_import_statuses()

        return {
            'name': _('Reglas importadas'),
            'type': 'ir.actions.act_window',
            'res_model': 'aicia.account.pgc.recode.rule',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_rules.ids)],
        }
