from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AiciaAccountPgcRecodeMoveWizard(models.TransientModel):
    _name = 'aicia.account.pgc.recode.move.wizard'
    _description = 'Mover apuntes de una cuenta a otra'

    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )
    source_account_id = fields.Many2one(
        'account.account',
        string='Cuenta origen',
        required=True,
    )
    target_account_id = fields.Many2one(
        'account.account',
        string='Cuenta destino',
        required=True,
    )
    date_from = fields.Date(string='Fecha desde')
    date_to = fields.Date(string='Fecha hasta')
    journal_ids = fields.Many2many(
        'account.journal',
        relation='aicia_pgc_move_journal_rel',
        column1='wizard_id',
        column2='journal_id',
        string='Diarios',
    )
    posted_only = fields.Boolean(string='Solo asientos publicados', default=True)
    move_line_count = fields.Integer(
        string='Apuntes afectados',
        compute='_compute_move_line_count',
    )

    @api.depends(
        'company_id',
        'source_account_id',
        'date_from',
        'date_to',
        'journal_ids',
        'posted_only',
    )
    def _compute_move_line_count(self):
        for wizard in self:
            if not wizard.source_account_id:
                wizard.move_line_count = 0
                continue
            wizard.move_line_count = self.env['account.move.line'].search_count(
                wizard._get_move_line_domain()
            )

    def _check_configuration(self):
        self.ensure_one()
        if not self.source_account_id or not self.target_account_id:
            raise ValidationError(_('Debes indicar la cuenta origen y la cuenta destino.'))
        if self.source_account_id == self.target_account_id:
            raise ValidationError(_('La cuenta origen y la cuenta destino deben ser distintas.'))
        if self.company_id not in self.source_account_id.company_ids:
            raise ValidationError(_('La cuenta origen debe pertenecer al plan contable de la compañía.'))
        if self.company_id not in self.target_account_id.company_ids:
            raise ValidationError(_('La cuenta destino debe pertenecer al plan contable de la compañía.'))
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_('La fecha desde no puede ser posterior a la fecha hasta.'))

    def _get_move_line_domain(self):
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('account_id', '=', self.source_account_id.id),
        ]
        if self.posted_only:
            domain.append(('parent_state', '=', 'posted'))
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))
        if self.journal_ids:
            domain.append(('journal_id', 'in', self.journal_ids.ids))
        return domain

    def action_apply_move(self):
        self.ensure_one()
        self._check_configuration()

        move_lines = self.env['account.move.line'].search(self._get_move_line_domain())
        if not move_lines:
            raise UserError(_('No se ha encontrado ningún apunte que cumpla los criterios indicados.'))

        move_lines.with_context(check_move_validity=False).write({
            'account_id': self.target_account_id.id,
            'aicia_pgc_recode_original_account_id': self.source_account_id.id,
            'aicia_pgc_recode_applied': True,
            'aicia_pgc_recode_last_batch_id': False,
        })

        message = _(
            'Se han movido %(count)s apuntes de %(source)s a %(target)s.',
            count=len(move_lines),
            source=self.source_account_id.display_name,
            target=self.target_account_id.display_name,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Apuntes movidos'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
