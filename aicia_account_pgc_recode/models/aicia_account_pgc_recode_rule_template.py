from odoo import fields, models


class AiciaAccountPgcRecodeRuleTemplate(models.Model):
    _name = 'aicia.account.pgc.recode.rule.template'
    _description = 'Plantilla de equivalencia PGC (origen → destino)'
    _order = 'old_code'

    old_code = fields.Char(string='Cuenta origen (código)', required=True, index=True)
    old_name = fields.Char(string='Cuenta origen (nombre)')
    target_prefix = fields.Char(string='Cuenta destino (prefijo/código)')
    target_label = fields.Char(string='Cuenta destino (etiqueta)')
    create_target_account = fields.Boolean(
        string='Crear subcuenta destino al aplicar',
        default=False,
        help='Si se marca, permite mapear la cuenta origen a un código destino que '
             'todavía no existe en el plan contable. La subcuenta se creará al aplicar '
             'la recodificación.',
    )
    notes = fields.Text(string='Notas')
    source_row = fields.Integer(string='Fila origen')

    status = fields.Selection([
        ('draft', 'Borrador'),
        ('automatic', 'Automática'),
        ('review', 'En revisión'),
        ('manual', 'Manual'),
        ('discarded', 'Descartada'),
        ('applied', 'Aplicada'),
    ], string='Estado inicial', default='draft', required=True)

    _unique_old_code = models.Constraint(
        'UNIQUE(old_code)',
        'Ya existe una plantilla de equivalencia con esa cuenta origen.',
    )

    def _get_default_rule_rows(self):
        rows = []
        for template in self.search([]):
            rows.append({
                'old_code': template.old_code,
                'old_name': template.old_name or False,
                'target_prefix': template.target_prefix or False,
                'target_label': template.target_label or False,
                'create_target_account': template.create_target_account,
                'notes': template.notes or False,
                'source_row': template.source_row or 0,
                'status': template.status or 'draft',
            })
        return rows
