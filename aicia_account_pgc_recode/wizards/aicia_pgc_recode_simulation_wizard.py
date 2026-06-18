from odoo import _, fields, models
from odoo.exceptions import ValidationError

class AiciaAccountPgcRecodeSimulationWizard(models.TransientModel):
    _name = 'aicia.account.pgc.recode.simulation.wizard'
    _description = 'Simular recodificación PGC'

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
    operation_mode = fields.Selection([
        ('rules', 'Usar mapeo'),
        ('manual', 'Cambio puntual'),
    ], string='Modo', default='rules', required=True)
    manual_old_account_id = fields.Many2one(
        'account.account',
        string='Cuenta origen',
    )
    manual_new_account_id = fields.Many2one(
        'account.account',
        string='Cuenta destino',
    )
    posted_only = fields.Boolean(string='Solo asientos publicados', default=True)
    include_already_recoded = fields.Boolean(string='Incluir ya recodificados', default=False)
    account_ids = fields.Many2many('account.account', relation='aicia_pgc_simulation_account_rel', column1='wizard_id', column2='account_id', string='Cuentas específicas')

    def _check_manual_mode_configuration(self):
        self.ensure_one()
        if self.operation_mode != 'manual':
            return
        if not self.manual_old_account_id or not self.manual_new_account_id:
            raise ValidationError(_('Debes indicar la cuenta origen y la cuenta destino para el cambio puntual.'))
        if self.manual_old_account_id == self.manual_new_account_id:
            raise ValidationError(_('La cuenta origen y la cuenta destino deben ser distintas.'))
        if self.company_id not in self.manual_old_account_id.company_ids:
            raise ValidationError(_('La cuenta origen debe pertenecer al plan contable de la compañía.'))
        if self.company_id not in self.manual_new_account_id.company_ids:
            raise ValidationError(_('La cuenta destino debe pertenecer al plan contable de la compañía.'))

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
        if self.operation_mode == 'manual' and self.manual_old_account_id:
            domain.append(('account_id', '=', self.manual_old_account_id.id))
        return domain

    def _build_manual_line_values(self, batch, move_lines):
        self.ensure_one()
        return [{
            'batch_id': batch.id,
            'move_line_id': line.id,
            'old_account_id': line.account_id.id,
            'new_account_id': self.manual_new_account_id.id,
            'new_account_code': self.manual_new_account_id.code,
            'new_account_name': self.manual_new_account_id.name,
            'status': 'automatic',
            'confidence': 'high',
            'notes': _('Cambio puntual preparado desde %s hacia %s.') % (
                self.manual_old_account_id.code,
                self.manual_new_account_id.code,
            ),
        } for line in move_lines]

    def action_simulate(self):
        self.ensure_one()
        self._check_manual_mode_configuration()

        move_lines = self.env['account.move.line'].search(self._get_move_line_domain())

        if self.operation_mode == 'manual':
            batch_note = _('Borrador generado sobre %s líneas para trasladar %s a %s.') % (
                len(move_lines),
                self.manual_old_account_id.display_name,
                self.manual_new_account_id.display_name,
            )
        else:
            batch_note = _('Borrador generado sobre %s líneas usando el mapeo configurado.') % len(move_lines)

        batch = self.env['aicia.account.pgc.recode.batch'].create({
            'company_id': self.company_id.id,
            'state': 'simulated',
            'note': batch_note,
        })

        if self.operation_mode == 'manual':
            lines_data = self._build_manual_line_values(batch, move_lines)
            if lines_data:
                self.env['aicia.account.pgc.recode.line'].create(lines_data)
            return {
                'name': _('Borrador de recodificación'),
                'type': 'ir.actions.act_window',
                'res_model': 'aicia.account.pgc.recode.batch',
                'view_mode': 'form',
                'res_id': batch.id,
            }

        rules = self.env['aicia.account.pgc.recode.rule'].search([('company_id', '=', self.company_id.id)])
        rules._recompute_collision_and_status(rules.mapped('company_id'))
        rule_map = {r.old_code: r for r in rules}

        prefix_map = {}
        for r in rules:
            prefix = r.old_code[:4] if len(r.old_code) > 4 else r.old_code
            prefix_map.setdefault(prefix, []).append(r)

        lines_data = []
        rules_used = set()

        for line in move_lines:
            old_code = line.account_id.code
            matched_rules = []

            if old_code in rule_map:
                matched_rules = [rule_map[old_code]]
            elif len(old_code) == 6:
                for i in range(5, 2, -1):
                    prefix = old_code[:i]
                    if prefix in prefix_map:
                        matched_rules = [r for r in prefix_map[prefix] if old_code.startswith(r.old_code)]
                        if matched_rules:
                            break

            status = 'discarded'
            rule_id = False
            new_acc_code = False
            new_acc_name = False
            new_acc_id = False
            confidence = 'none'
            notes = []

            is_bank_cash = line.account_id.account_type in ('asset_cash', 'liability_credit_card')

            if len(matched_rules) == 1:
                rule = matched_rules[0]
                rule_id = rule.id
                rules_used.add(rule.id)
                new_acc_code = rule.proposed_code
                new_acc_name = rule.target_label
                new_acc_id = rule.proposed_account_id.id if rule.proposed_account_id else False

                if rule.status == 'manual':
                    status = 'manual'
                    if rule.proposed_code and not rule.proposed_account_id:
                        notes.append(_('La subcuenta propuesta no existe en el plan contable de la compañía.'))
                    else:
                        notes.append(_('La regla está marcada como manual.'))
                elif rule.collision:
                    status = 'review'
                    confidence = 'medium'
                    notes.append(rule.collision_notes or _('La regla tiene una colisión.'))
                elif not rule.proposed_code or len(rule.proposed_code) != 6:
                    status = 'manual'
                    notes.append(_('El código propuesto no es válido.'))
                elif not rule.proposed_account_id:
                    status = 'manual'
                    notes.append(_('La subcuenta propuesta no existe en el plan contable de la compañía.'))
                elif is_bank_cash:
                    status = 'manual'
                    notes.append(_('Las cuentas de banco o caja requieren validación manual.'))
                else:
                    status = 'automatic'
                    confidence = 'high' if rule.old_code == old_code else 'medium'
                    if confidence == 'medium':
                        status = 'review'
                        notes.append(_('La regla coincide por prefijo, no de forma exacta.'))
            elif len(matched_rules) > 1:
                status = 'review'
                confidence = 'low'
                notes.append(_('Coinciden varias reglas.'))
            else:
                status = 'discarded'
                notes.append(_('No se ha encontrado ninguna regla coincidente.'))

            lines_data.append({
                'batch_id': batch.id,
                'move_line_id': line.id,
                'old_account_id': line.account_id.id,
                'new_account_id': new_acc_id,
                'new_account_code': new_acc_code,
                'new_account_name': new_acc_name,
                'rule_id': rule_id,
                'status': status,
                'confidence': confidence,
                'notes': '\n'.join(notes)
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
