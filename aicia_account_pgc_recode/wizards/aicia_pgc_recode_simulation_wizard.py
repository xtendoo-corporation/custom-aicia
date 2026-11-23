from odoo import _, api, fields, models

BANK_CASH_TYPES = ('asset_cash', 'liability_credit_card')


class AiciaAccountPgcRecodeSimulationWizard(models.TransientModel):
    _name = 'aicia.account.pgc.recode.simulation.wizard'
    _description = 'Recodificación PGC por mapeo'

    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    date_from = fields.Date(string='Fecha desde')
    date_to = fields.Date(string='Fecha hasta')
    journal_ids = fields.Many2many(
        'account.journal',
        relation='aicia_pgc_simulation_journal_rel',
        column1='wizard_id',
        column2='journal_id',
        string='Diarios',
    )
    posted_only = fields.Boolean(string='Solo asientos publicados', default=True)
    include_already_recoded = fields.Boolean(string='Incluir ya recodificados', default=False)
    account_ids = fields.Many2many('account.account', relation='aicia_pgc_simulation_account_rel', column1='wizard_id', column2='account_id', string='Cuentas específicas')

    preview_generated = fields.Boolean(string='Previsualización generada', default=False)
    preview_line_ids = fields.One2many(
        'aicia.account.pgc.recode.preview.line',
        'wizard_id',
        string='Mapeo de subcuentas',
    )

    def _get_move_line_domain(self):
        self.ensure_one()
        domain = [('company_id', '=', self.company_id.id)]
        if self.posted_only:
            domain.append(('parent_state', '=', 'posted'))
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))
        if self.journal_ids:
            domain.append(('journal_id', 'in', self.journal_ids.ids))
        if not self.include_already_recoded:
            domain.append(('aicia_pgc_recode_applied', '=', False))
        if self.account_ids:
            domain.append(('account_id', 'in', self.account_ids.ids))
        return domain

    def _get_company_rules(self):
        self.ensure_one()
        rules = self.env['aicia.account.pgc.recode.rule'].search([('company_id', '=', self.company_id.id)])
        rules._recompute_collision_and_status(rules.mapped('company_id'))
        return rules

    @api.model
    def _build_rule_maps(self, rules):
        rule_map = {rule.old_code: rule for rule in rules}
        prefix_map = {}
        for rule in rules:
            prefix = rule.old_code[:4] if len(rule.old_code) > 4 else rule.old_code
            prefix_map.setdefault(prefix, []).append(rule)
        return rule_map, prefix_map

    @api.model
    def _match_rules_for_code(self, old_code, rule_map, prefix_map):
        if old_code in rule_map:
            return [rule_map[old_code]]
        if len(old_code) == 6:
            for length in range(5, 2, -1):
                prefix = old_code[:length]
                if prefix in prefix_map:
                    matched = [rule for rule in prefix_map[prefix] if old_code.startswith(rule.old_code)]
                    if matched:
                        return matched
        return []

    @api.model
    def _evaluate_account(self, account, rule_map, prefix_map):
        old_code = account.code
        matched_rules = self._match_rules_for_code(old_code, rule_map, prefix_map)
        result = {
            'rule_id': False,
            'new_account_id': False,
            'new_account_code': False,
            'new_account_name': False,
            'status': 'discarded',
            'confidence': 'none',
            'notes': '',
        }
        notes = []
        is_bank_cash = account.account_type in BANK_CASH_TYPES

        if len(matched_rules) == 1:
            rule = matched_rules[0]
            result['rule_id'] = rule.id
            result['new_account_code'] = rule.proposed_code
            result['new_account_name'] = rule.target_label
            result['new_account_id'] = rule.proposed_account_id.id if rule.proposed_account_id else False

            if rule.status == 'manual':
                result['status'] = 'manual'
                if rule.proposed_code and not rule.proposed_account_id:
                    notes.append(_('La subcuenta propuesta no existe en el plan contable de la compañía.'))
                else:
                    notes.append(_('La regla está marcada como manual.'))
            elif rule.collision:
                result['status'] = 'review'
                result['confidence'] = 'medium'
                notes.append(rule.collision_notes or _('La regla tiene una colisión.'))
            elif not rule.proposed_code or len(rule.proposed_code) != 6:
                result['status'] = 'manual'
                notes.append(_('El código propuesto no es válido.'))
            elif not rule.proposed_account_id:
                if rule.create_target_account:
                    result['status'] = 'review'
                    result['confidence'] = 'medium'
                    notes.append(_('La subcuenta destino no existe todavía; se creará al aplicar.'))
                else:
                    result['status'] = 'manual'
                    notes.append(_('La subcuenta propuesta no existe en el plan contable de la compañía.'))
            elif is_bank_cash:
                result['status'] = 'manual'
                notes.append(_('Las cuentas de banco o caja requieren validación manual.'))
            else:
                result['status'] = 'automatic'
                result['confidence'] = 'high' if rule.old_code == old_code else 'medium'
                if result['confidence'] == 'medium':
                    result['status'] = 'review'
                    notes.append(_('La regla coincide por prefijo, no de forma exacta.'))
        elif len(matched_rules) > 1:
            result['status'] = 'review'
            result['confidence'] = 'low'
            notes.append(_('Coinciden varias reglas.'))
        else:
            result['status'] = 'discarded'
            notes.append(_('No se ha encontrado ninguna regla coincidente.'))

        result['notes'] = '\n'.join(notes)
        return result

    def _resolve_evaluation(self, account, base_eval, preview):
        if not preview:
            return base_eval

        result = dict(base_eval)
        result['rule_id'] = preview.rule_id.id
        new_account = preview.new_account_id

        if not new_account:
            result['new_account_id'] = False
            result['new_account_code'] = preview.new_account_code
            result['new_account_name'] = preview.new_account_name
            has_creatable_code = bool(preview.new_account_code) and len(preview.new_account_code) == 6
            if base_eval['status'] in ('manual', 'discarded'):
                result['status'] = base_eval['status']
            elif has_creatable_code and base_eval['status'] == 'review':
                result['status'] = 'review'
            else:
                result['status'] = 'manual'
            result['notes'] = preview.notes or base_eval['notes']
            return result

        result['new_account_id'] = new_account.id
        result['new_account_code'] = new_account.code
        result['new_account_name'] = new_account.name

        if len(new_account.code) != 6:
            result['status'] = 'manual'
            result['notes'] = _('El código propuesto no es válido.')
        elif account.account_type in BANK_CASH_TYPES:
            result['status'] = 'manual'
            result['notes'] = _('Las cuentas de banco o caja requieren validación manual.')
        elif base_eval['status'] == 'review' and new_account.id == base_eval['new_account_id']:
            result['status'] = 'review'
            result['confidence'] = base_eval['confidence']
            result['notes'] = base_eval['notes']
        else:
            result['status'] = 'automatic'
            result['confidence'] = base_eval['confidence'] or 'high'
            result['notes'] = ''
        return result

    def action_preview(self):
        self.ensure_one()
        self.preview_line_ids.unlink()

        move_lines = self.env['account.move.line'].search(self._get_move_line_domain())
        rule_map, prefix_map = self._build_rule_maps(self._get_company_rules())

        grouped = {}
        for line in move_lines:
            account = line.account_id
            data = grouped.setdefault(account.id, {'account': account, 'count': 0, 'balance': 0.0})
            data['count'] += 1
            data['balance'] += line.balance

        preview_vals = []
        for data in grouped.values():
            evaluation = self._evaluate_account(data['account'], rule_map, prefix_map)
            preview_vals.append({
                'wizard_id': self.id,
                'old_account_id': data['account'].id,
                'move_line_count': data['count'],
                'total_balance': data['balance'],
                'new_account_id': evaluation['new_account_id'],
                'new_account_code': evaluation['new_account_code'],
                'new_account_name': evaluation['new_account_name'],
                'rule_id': evaluation['rule_id'],
                'status': evaluation['status'],
                'confidence': evaluation['confidence'],
                'notes': evaluation['notes'],
            })

        if preview_vals:
            self.env['aicia.account.pgc.recode.preview.line'].create(preview_vals)
        self.preview_generated = True

        return {
            'name': _('Recodificación por mapeo'),
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_simulate(self):
        self.ensure_one()

        move_lines = self.env['account.move.line'].search(self._get_move_line_domain())

        batch = self.env['aicia.account.pgc.recode.batch'].create({
            'company_id': self.company_id.id,
            'state': 'simulated',
            'note': _('Borrador generado sobre %s líneas usando el mapeo configurado.') % len(move_lines),
        })

        rule_map, prefix_map = self._build_rule_maps(self._get_company_rules())
        preview_map = {line.old_account_id.id: line for line in self.preview_line_ids}

        evaluation_cache = {}
        lines_data = []
        rules_used = set()

        for line in move_lines:
            account = line.account_id
            if account.id not in evaluation_cache:
                base_eval = self._evaluate_account(account, rule_map, prefix_map)
                evaluation_cache[account.id] = self._resolve_evaluation(
                    account, base_eval, preview_map.get(account.id)
                )
            evaluation = evaluation_cache[account.id]

            if evaluation['rule_id']:
                rules_used.add(evaluation['rule_id'])

            lines_data.append({
                'batch_id': batch.id,
                'move_line_id': line.id,
                'old_account_id': account.id,
                'new_account_id': evaluation['new_account_id'],
                'new_account_code': evaluation['new_account_code'],
                'new_account_name': evaluation['new_account_name'],
                'rule_id': evaluation['rule_id'],
                'status': evaluation['status'],
                'confidence': evaluation['confidence'],
                'notes': evaluation['notes'],
            })

        if lines_data:
            self.env['aicia.account.pgc.recode.line'].create(lines_data)
            batch.rule_ids = [(6, 0, list(rules_used))]

        return {
            'name': _('Borrador de recodificación'),
            'type': 'ir.actions.act_window',
            'res_model': 'aicia.account.pgc.recode.batch',
            'view_mode': 'form',
            'res_id': batch.id,
        }


class AiciaAccountPgcRecodePreviewLine(models.TransientModel):
    _name = 'aicia.account.pgc.recode.preview.line'
    _description = 'Previsualización del mapeo de subcuentas'
    _order = 'old_account_code'

    wizard_id = fields.Many2one(
        'aicia.account.pgc.recode.simulation.wizard',
        string='Asistente',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(related='wizard_id.company_id', store=True)
    company_currency_id = fields.Many2one(related='company_id.currency_id')

    old_account_id = fields.Many2one('account.account', string='Subcuenta origen', required=True, readonly=True)
    old_account_code = fields.Char(related='old_account_id.code', string='Código origen', store=True)
    old_account_name = fields.Char(related='old_account_id.name', string='Nombre origen')

    move_line_count = fields.Integer(string='Apuntes afectados', readonly=True)
    total_balance = fields.Monetary(string='Saldo', currency_field='company_currency_id', readonly=True)

    new_account_id = fields.Many2one('account.account', string='Subcuenta destino')
    new_account_code = fields.Char(string='Código destino propuesto', readonly=True)
    new_account_name = fields.Char(string='Nombre destino propuesto', readonly=True)

    rule_id = fields.Many2one('aicia.account.pgc.recode.rule', string='Regla', readonly=True)

    status = fields.Selection([
        ('automatic', 'Automática'),
        ('review', 'En revisión'),
        ('manual', 'Manual'),
        ('discarded', 'Descartada'),
    ], string='Estado', readonly=True)

    confidence = fields.Selection([
        ('high', 'Alta'),
        ('medium', 'Media'),
        ('low', 'Baja'),
        ('none', 'Ninguna'),
    ], string='Confianza', readonly=True)

    notes = fields.Text(string='Observaciones', readonly=True)
