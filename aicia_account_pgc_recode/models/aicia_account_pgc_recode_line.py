from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AiciaAccountPgcRecodeLine(models.Model):
    _name = 'aicia.account.pgc.recode.line'
    _description = 'Línea de propuesta de recodificación PGC'
    _order = 'date desc, id desc'

    batch_id = fields.Many2one('aicia.account.pgc.recode.batch', string='Lote', required=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', related='batch_id.company_id', store=True)

    move_line_id = fields.Many2one('account.move.line', string='Apunte contable', required=True, ondelete='cascade')
    move_id = fields.Many2one('account.move', related='move_line_id.move_id', store=True, string='Asiento contable')
    date = fields.Date(related='move_line_id.date', store=True)
    journal_id = fields.Many2one('account.journal', related='move_line_id.journal_id', store=True)
    partner_id = fields.Many2one('res.partner', related='move_line_id.partner_id', store=True)

    old_account_id = fields.Many2one('account.account', string='Cuenta anterior', required=True)
    old_account_code = fields.Char(related='old_account_id.code', string='Código cuenta anterior')
    old_account_name = fields.Char(related='old_account_id.name', string='Nombre cuenta anterior')

    new_account_id = fields.Many2one('account.account', string='Cuenta destino propuesta')
    new_account_code = fields.Char(string='Código propuesto')
    new_account_name = fields.Char(string='Nombre propuesto')

    rule_id = fields.Many2one('aicia.account.pgc.recode.rule', string='Regla aplicada')

    debit = fields.Monetary(related='move_line_id.debit', currency_field='company_currency_id')
    credit = fields.Monetary(related='move_line_id.credit', currency_field='company_currency_id')
    balance = fields.Monetary(related='move_line_id.balance', currency_field='company_currency_id')
    company_currency_id = fields.Many2one(related='company_id.currency_id')

    name = fields.Char(related='move_line_id.name', string='Concepto')
    ref = fields.Char(related='move_line_id.ref', string='Referencia')

    status = fields.Selection([
        ('automatic', 'Automática'),
        ('review', 'En revisión'),
        ('manual', 'Manual'),
        ('discarded', 'Descartada'),
        ('applied', 'Aplicada'),
        ('error', 'Error')
    ], string='Estado', required=True)

    confidence = fields.Selection([
        ('high', 'Alta'),
        ('medium', 'Media'),
        ('low', 'Baja'),
        ('none', 'Ninguna')
    ], string='Confianza', default='none')

    applied = fields.Boolean(string='Aplicada', default=False)
    applied_date = fields.Datetime(string='Fecha de aplicación')
    reverted = fields.Boolean(string='Revertida', default=False)
    notes = fields.Text(string='Notas')
    blocking_reason = fields.Char(string='Motivo de bloqueo', compute='_compute_blocking_reason')

    @api.depends('status', 'notes', 'reverted')
    def _compute_blocking_reason(self):
        default_reasons = {
            'manual': _('La línea requiere intervención manual.'),
            'review': _('La línea requiere revisión antes de aplicarse.'),
            'error': _('La línea contiene un error que impide su aplicación.'),
        }
        for line in self:
            if line.status not in ('manual', 'review', 'error'):
                line.blocking_reason = False
            elif line.reverted:
                line.blocking_reason = _('Línea revertida; revisa la propuesta antes de volver a aplicarla.')
            else:
                line.blocking_reason = (line.notes or '').splitlines()[0] or default_reasons.get(line.status)

    def action_apply(self, create_missing=False):
        self.ensure_one()
        if self.applied:
            raise UserError(_("La línea ya está aplicada."))

        if self.status in ('manual', 'discarded', 'error'):
            raise UserError(_("No se puede aplicar una línea con estado %s.") % self.status)

        if not self.new_account_id:
            self.write({
                'status': 'error',
                'notes': _('La subcuenta propuesta debe existir previamente en el plan contable de la compañía.'),
            })
            return False

        if len(self.new_account_id.code) != 6:
            self.write({'status': 'error', 'notes': _('La cuenta destino debe tener exactamente 6 dígitos.')})
            return False

        if self.move_line_id.company_id != self.company_id:
            self.write({'status': 'error', 'notes': _('La compañía del apunte no coincide con la del lote.')})
            return False

        if self.move_line_id.aicia_pgc_recode_applied and self.move_line_id.aicia_pgc_recode_last_batch_id != self.batch_id:
            self.write({'status': 'error', 'notes': _('Esta línea ya fue recodificada por otro lote.')})
            return False

        try:
            with self.env.cr.savepoint():
                self.move_line_id.with_context(check_move_validity=False).write({
                    'account_id': self.new_account_id.id,
                    'aicia_pgc_recode_original_account_id': self.old_account_id.id,
                    'aicia_pgc_recode_applied': True,
                    'aicia_pgc_recode_last_batch_id': self.batch_id.id,
                })
        except Exception as e:
            self.write({'status': 'error', 'notes': _('Error al aplicar el cambio: %s') % str(e)})
            return False

        self.write({
            'applied': True,
            'status': 'applied',
            'applied_date': fields.Datetime.now()
        })
        return True

    def _create_target_account(self):
        self.ensure_one()
        prefix = self.new_account_code[:3]
        account_model = self.env['account.account'].with_company(self.company_id)
        reference_acc = account_model.search([
            ('company_ids', '=', self.company_id.id),
            ('code', '=like', f"{prefix}%")
        ], limit=1)

        if not reference_acc:
            prefix = self.new_account_code[:2]
            reference_acc = account_model.search([
                ('company_ids', '=', self.company_id.id),
                ('code', '=like', f"{prefix}%")
            ], limit=1)

        if not reference_acc:
            return False

        new_name = self.new_account_name or _("Recodificada desde %s") % self.old_account_code

        new_account = account_model.create({
            'code': self.new_account_code,
            'name': new_name,
            'account_type': reference_acc.account_type,
            'reconcile': reference_acc.reconcile,
            'currency_id': reference_acc.currency_id.id,
            'company_ids': [(6, 0, self.company_id.ids)],
            'tag_ids': [(6, 0, reference_acc.tag_ids.ids)] if reference_acc.tag_ids else False,
        })
        return new_account

    def action_revert(self):
        self.ensure_one()
        if not self.applied:
            raise UserError(_("La línea no está aplicada y no se puede revertir."))

        if self.move_line_id.account_id != self.new_account_id:
            raise UserError(_("La cuenta de la línea se modificó después de la recodificación. No se puede revertir con seguridad."))

        try:
            with self.env.cr.savepoint():
                self.move_line_id.with_context(check_move_validity=False).write({
                    'account_id': self.old_account_id.id,
                    'aicia_pgc_recode_applied': False,
                    'aicia_pgc_recode_last_batch_id': False,
                })
        except Exception as e:
            raise UserError(_('Error al revertir el cambio: %s') % str(e))

        self.write({
            'applied': False,
            'status': 'review',
            'reverted': True,
            'applied_date': False
        })
