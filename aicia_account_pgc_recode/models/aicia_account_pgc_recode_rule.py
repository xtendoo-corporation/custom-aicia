import re
from io import BytesIO
from zipfile import is_zipfile

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import xlrd
except ImportError:
    xlrd = None



class AiciaAccountPgcRecodeRule(models.Model):
    _name = 'aicia.account.pgc.recode.rule'
    _description = 'Regla de recodificación PGC'
    _order = 'old_code'

    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    old_code = fields.Char(string='Código anterior', required=True)
    old_name = fields.Char(string='Nombre anterior')
    target_prefix = fields.Char(string='Prefijo destino')
    target_label = fields.Char(string='Etiqueta destino')
    proposed_code = fields.Char(
        string='Código propuesto',
        compute='_compute_proposed_code',
        inverse='_inverse_proposed_code',
        store=True,
    )
    proposed_account_id = fields.Many2one(
        'account.account',
        string='Cuenta propuesta',
        compute='_compute_proposed_account',
        inverse='_inverse_proposed_account',
    )

    status = fields.Selection([
        ('draft', 'Borrador'),
        ('automatic', 'Automática'),
        ('review', 'En revisión'),
        ('manual', 'Manual'),
        ('discarded', 'Descartada'),
        ('applied', 'Aplicada')
    ], string='Estado', default='draft', required=True)

    confidence = fields.Selection([
        ('high', 'Alta'),
        ('medium', 'Media'),
        ('low', 'Baja'),
        ('none', 'Ninguna')
    ], string='Confianza', default='none')

    collision = fields.Boolean(string='Colisión', default=False)
    collision_notes = fields.Text(string='Notas de colisión')
    create_target_account = fields.Boolean(
        string='Crear subcuenta destino al aplicar',
        default=False,
        help='Si se marca, permite mapear la cuenta origen a un código destino que '
             'todavía no existe en el plan contable. La subcuenta se creará al aplicar '
             'la recodificación.',
    )
    notes = fields.Text(string='Notas')
    active = fields.Boolean(default=True)
    is_default_data = fields.Boolean(string='Cargado desde el Excel por defecto', default=False, copy=False, index=True)
    source_row = fields.Integer(string='Fila origen', copy=False)

    @api.depends('old_code', 'target_prefix')
    def _compute_proposed_code(self):
        for rule in self:
            if not rule.target_prefix or '/' in rule.target_prefix:
                rule.proposed_code = False
                continue

            prefix = rule.target_prefix.strip()
            old_code = rule.old_code.strip() if rule.old_code else ''

            # Destination has exactly 6 digits
            if len(prefix) == 6:
                rule.proposed_code = prefix
            elif len(prefix) > 6:
                rule.proposed_code = False
            else:
                # Need to complete to 6 digits
                missing_digits = 6 - len(prefix)
                if len(old_code) >= missing_digits:
                    suffix = old_code[-missing_digits:]
                    rule.proposed_code = f"{prefix}{suffix}"
                else:
                    # Pad with zeros if old code is shorter than needed
                    suffix = old_code.zfill(missing_digits)
                    rule.proposed_code = f"{prefix}{suffix}"

    def _inverse_proposed_code(self):
        for rule in self:
            proposed_code = re.sub(r'[^0-9]', '', rule.proposed_code or '')
            if not proposed_code:
                rule.target_prefix = False
                continue
            if len(proposed_code) != 6:
                raise ValidationError(_('El código propuesto debe tener exactamente 6 dígitos.'))
            if not rule._find_account_by_code(proposed_code):
                raise ValidationError(
                    _('La cuenta propuesta debe existir previamente en el plan contable de la compañía.')
                )
            rule.target_prefix = proposed_code

    def _inverse_proposed_account(self):
        for rule in self:
            if not rule.proposed_account_id:
                rule.target_prefix = False
                continue
            if rule.company_id not in rule.proposed_account_id.company_ids:
                raise ValidationError(
                    _('La cuenta propuesta debe pertenecer al plan contable de la compañía.')
                )
            rule.target_prefix = rule.proposed_account_id.code

    @api.depends('proposed_code', 'company_id')
    def _compute_proposed_account(self):
        for rule in self:
            rule.proposed_account_id = rule._find_proposed_account().id or False

    def _find_account_by_code(self, code):
        self.ensure_one()
        if not code or not self.company_id:
            return self.env['account.account']
        return self.env['account.account'].with_company(self.company_id).search([
            ('code', '=', code),
            ('company_ids', '=', self.company_id.id)
        ], limit=1)

    def _find_proposed_account(self):
        self.ensure_one()
        return self._find_account_by_code(self.proposed_code)

    def _check_status_requires_existing_proposed_account(self, target_status=None):
        for rule in self:
            status = target_status or rule.status
            if status == 'automatic' and (not rule.proposed_code or len(rule.proposed_code) != 6):
                raise ValidationError(_('El código propuesto debe tener exactamente 6 dígitos.'))
            if status not in ('automatic', 'review', 'applied') or not rule.proposed_code:
                continue
            if rule.create_target_account:
                if len(rule.proposed_code) != 6:
                    raise ValidationError(_('El código propuesto debe tener exactamente 6 dígitos.'))
                if status == 'automatic' and rule.collision:
                    raise ValidationError(_('No se puede marcar como automática si existe una colisión.'))
                continue
            if not rule._find_proposed_account():
                raise ValidationError(
                    _('La subcuenta propuesta debe existir previamente en el plan contable de la compañía.')
                )
            if status == 'automatic' and rule.collision:
                raise ValidationError(_('No se puede marcar como automática si existe una colisión.'))

    def action_mark_automatic(self):
        self._check_status_requires_existing_proposed_account(target_status='automatic')
        self.write({'status': 'automatic'})

    def action_mark_review(self):
        self.write({'status': 'review'})

    def action_mark_manual(self):
        self.write({'status': 'manual'})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_recode_collision_check'):
            records._recompute_collision_and_status(records.mapped('company_id'))
        return records

    def write(self, vals):
        previous_companies = self.mapped('company_id')
        if 'status' in vals:
            self._check_status_requires_existing_proposed_account(target_status=vals['status'])
        res = super().write(vals)
        if not self.env.context.get('skip_recode_collision_check') and {
            'company_id',
            'old_code',
            'target_prefix',
            'proposed_code',
            'proposed_account_id',
        } & set(vals):
            self._recompute_collision_and_status(previous_companies | self.mapped('company_id'))
        return res

    @api.model
    def _normalize_cell_value(self, value):
        if value is None:
            return ''
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    @api.model
    def _get_workbook_rows(self, file_content, filename=False):
        normalized_name = (filename or '').lower()
        if normalized_name.endswith('.xlsx') or is_zipfile(BytesIO(file_content)):
            if not openpyxl:
                raise ValidationError(_('Instala openpyxl para poder leer archivos Excel.'))
            workbook = openpyxl.load_workbook(BytesIO(file_content), data_only=True, read_only=True)
            sheet = workbook.worksheets[0]
            return [tuple(row) for row in sheet.iter_rows(values_only=True)]

        if normalized_name.endswith('.xls'):
            if not xlrd:
                raise ValidationError(
                    _('Instala xlrd para leer archivos .xls antiguos o convierte el fichero a .xlsx.')
                )
            workbook = xlrd.open_workbook(file_contents=file_content)
            sheet = workbook.sheet_by_index(0)
            return [tuple(sheet.row_values(index)) for index in range(sheet.nrows)]

        raise ValidationError(_('Solo se admiten archivos .xls y .xlsx.'))

    @api.model
    def _extract_target_prefix(self, target_value):
        match = re.match(r'^(\d+(?:/\d+)*)', target_value or '')
        return match.group(1) if match else False

    @api.model
    def _extract_target_label(self, target_value):
        target_value = (target_value or '').strip()
        if not target_value:
            return False
        match = re.match(r'^(\d+(?:/\d+)*)\s*[:\-]?\s*(.*)$', target_value)
        if not match:
            return target_value
        label = match.group(2).strip()
        return label or target_value

    @api.model
    def _extract_old_account_parts(self, old_value):
        old_value = self._normalize_cell_value(old_value)
        if not old_value or old_value.upper().startswith('TOTAL '):
            return False, False

        match = re.match(r'^(\d+)\s*(.*)$', old_value)
        if match:
            old_name = match.group(2).strip()
            return match.group(1), old_name or False

        digits_only = re.sub(r'[^0-9]', '', old_value)
        if digits_only:
            return digits_only, old_value
        return False, False

    @api.model
    def _detect_aicia_balance_format(self, rows):
        if len(rows) < 4:
            return False
        first_header = self._normalize_cell_value(rows[3][0] if len(rows[3]) > 0 else False)
        second_header = self._normalize_cell_value(rows[3][1] if len(rows[3]) > 1 else False)
        return first_header == 'Cuenta PGC' and 'AICIA' in second_header

    @api.model
    def _parse_aicia_balance_rows(self, rows):
        parsed_rows = []
        last_target = False

        for row_number, row in enumerate(rows[4:], start=5):
            target_value = self._normalize_cell_value(row[0] if len(row) > 0 else False)
            old_value = row[1] if len(row) > 1 else False

            if target_value in {'', '"', "''"}:
                target_value = last_target
            elif target_value:
                last_target = target_value

            old_code, old_name = self._extract_old_account_parts(old_value)
            if not old_code:
                continue

            target_prefix = self._extract_target_prefix(target_value)
            status = 'manual' if not target_prefix or '/' in target_prefix else 'draft'
            parsed_rows.append({
                'old_code': old_code,
                'old_name': old_name,
                'target_prefix': target_prefix or False,
                'target_label': self._extract_target_label(target_value),
                'notes': target_value or False,
                'source_row': row_number,
                'status': status,
            })

        return parsed_rows

    @api.model
    def _parse_generic_rows(self, rows):
        parsed_rows = []
        last_target = False

        for row_number, row in enumerate(rows[1:], start=2):
            target_value = self._normalize_cell_value(row[0] if len(row) > 0 else False)
            old_value = self._normalize_cell_value(row[1] if len(row) > 1 else False)
            description = self._normalize_cell_value(row[2] if len(row) > 2 else False)

            if not old_value:
                continue

            if target_value in {'', '"', "''"}:
                target_value = last_target
            elif target_value:
                last_target = target_value

            old_code = re.sub(r'[^0-9]', '', old_value)
            if not old_code:
                continue

            target_prefix = target_value or False
            status = 'manual' if not target_prefix or '/' in target_prefix else 'draft'
            parsed_rows.append({
                'old_code': old_code,
                'old_name': description or False,
                'target_prefix': target_prefix,
                'target_label': description or False,
                'notes': False,
                'source_row': row_number,
                'status': status,
            })

        return parsed_rows

    @api.model
    def parse_rules_file(self, file_content, filename=False):
        rows = self._get_workbook_rows(file_content, filename=filename)
        if self._detect_aicia_balance_format(rows):
            return self._parse_aicia_balance_rows(rows)
        return self._parse_generic_rows(rows)

    def _finalize_import_statuses(self):
        self._recompute_collision_and_status(self.mapped('company_id'))

    def _get_recomputed_status(self):
        self.ensure_one()
        if self.status in ('discarded', 'applied'):
            return self.status
        if not self.proposed_code or len(self.proposed_code) != 6:
            return 'manual'
        if not self._find_proposed_account():
            if self.create_target_account:
                return 'review'
            return 'manual'
        if self.collision:
            return 'review'
        return 'automatic'

    def _recompute_collision_and_status(self, companies=None):
        companies = companies or self.mapped('company_id')
        for company in companies:
            all_company_rules = self.search([('company_id', '=', company.id)])
            rules_with_code = all_company_rules.filtered('proposed_code')
            rules_with_collision = all_company_rules.filtered('collision')
            if rules_with_collision:
                rules_with_collision.with_context(skip_recode_collision_check=True).write({
                    'collision': False,
                    'collision_notes': False,
                })

            code_counts = {}
            for rule in rules_with_code:
                code_counts.setdefault(rule.proposed_code, self.browse())
                code_counts[rule.proposed_code] |= rule

            for rule_list in code_counts.values():
                if len(rule_list) <= 1:
                    continue
                for rule in rule_list:
                    others = ', '.join((rule_list - rule).mapped('old_code'))
                    rule.with_context(skip_recode_collision_check=True).write({
                        'collision': True,
                        'collision_notes': _('Colisiona con: %s', others),
                    })

            for rule in all_company_rules:
                new_status = rule._get_recomputed_status()
                if rule.status != new_status:
                    rule.with_context(skip_recode_collision_check=True).write({'status': new_status})

    @api.model
    def load_default_rules_for_company(self, company):
        if not getattr(company, '_name', False):
            company = self.env['res.company'].browse(company)
        parsed_rows = self.env['aicia.account.pgc.recode.rule.template']._get_default_rule_rows()

        company_rules = self.search([('company_id', '=', company.id)])
        default_rules = company_rules.filtered('is_default_data')
        custom_old_codes = set((company_rules - default_rules).mapped('old_code'))
        default_by_old_code = {rule.old_code: rule for rule in default_rules}
        parsed_by_old_code = {row['old_code']: row for row in parsed_rows}

        stale_default_rules = default_rules.filtered(
            lambda rule: rule.old_code not in parsed_by_old_code or rule.old_code in custom_old_codes
        )
        has_changes = bool(stale_default_rules)
        if stale_default_rules:
            stale_default_rules.unlink()

        rules_to_create = []
        for parsed_row in parsed_rows:
            if parsed_row['old_code'] in custom_old_codes:
                continue

            default_rule = default_by_old_code.get(parsed_row['old_code'])
            values = {
                'company_id': company.id,
                'old_code': parsed_row['old_code'],
                'old_name': parsed_row['old_name'],
                'target_prefix': parsed_row['target_prefix'],
                'target_label': parsed_row['target_label'],
                'create_target_account': parsed_row.get('create_target_account', False),
                'notes': parsed_row['notes'],
                'status': parsed_row['status'],
                'is_default_data': True,
                'source_row': parsed_row['source_row'],
                'active': True,
            }
            if not default_rule:
                rules_to_create.append(values)
                has_changes = True
                continue

            changed_values = {
                'old_name': values['old_name'],
                'target_prefix': values['target_prefix'],
                'target_label': values['target_label'],
                'create_target_account': values['create_target_account'],
                'notes': values['notes'],
                'status': values['status'],
                'source_row': values['source_row'],
                'active': values['active'],
                'is_default_data': values['is_default_data'],
            }

            if any(default_rule[field_name] != field_value for field_name, field_value in changed_values.items()):
                default_rule.with_context(skip_recode_collision_check=True).write(changed_values)
                has_changes = True

        if rules_to_create:
            self.with_context(skip_recode_collision_check=True).create(rules_to_create)

        default_rules = self.search([
            ('company_id', '=', company.id),
            ('is_default_data', '=', True),
        ])
        if has_changes:
            default_rules._recompute_collision_and_status(default_rules.mapped('company_id'))
        return default_rules

    @api.model
    def load_default_rules_for_all_companies(self):
        companies = self.env['res.company'].search([])
        loaded_rules = self.browse()
        for company in companies:
            loaded_rules |= self.load_default_rules_for_company(company)
        return loaded_rules

    def _check_collision(self):
        self._recompute_collision_and_status(self.mapped('company_id'))
