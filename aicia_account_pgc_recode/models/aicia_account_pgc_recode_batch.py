from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AiciaAccountPgcRecodeBatch(models.Model):
    _name = 'aicia.account.pgc.recode.batch'
    _description = 'Lote de recodificación PGC'
    _order = 'date desc, id desc'

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True, default=lambda self: _('Nuevo'))
    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    date = fields.Datetime(string='Fecha', default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one('res.users', string='Responsable', default=lambda self: self.env.user, readonly=True)

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('simulated', 'Borrador preparado'),
        ('partially_applied', 'Parcialmente aplicado'),
        ('applied', 'Aplicado'),
        ('reverted', 'Revertido'),
        ('cancelled', 'Cancelado')
    ], string='Estado', default='draft', required=True)

    line_ids = fields.One2many('aicia.account.pgc.recode.line', 'batch_id', string='Líneas')
    rule_ids = fields.Many2many('aicia.account.pgc.recode.rule', relation='aicia_pgc_recode_batch_rule_rel', column1='batch_id', column2='rule_id', string='Reglas utilizadas')

    move_line_count = fields.Integer(string='Total de líneas', compute='_compute_counts')
    applied_line_count = fields.Integer(string='Líneas aplicadas', compute='_compute_counts')
    manual_line_count = fields.Integer(string='Líneas manuales', compute='_compute_counts')
    review_line_count = fields.Integer(string='Líneas en revisión', compute='_compute_counts')

    note = fields.Text(string='Notas internas')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('aicia.account.pgc.recode.batch') or _('Lote %s') % fields.Date.today()
        return super().create(vals_list)

    @api.depends('line_ids.status', 'line_ids.applied')
    def _compute_counts(self):
        for batch in self:
            batch.move_line_count = len(batch.line_ids)
            batch.applied_line_count = len(batch.line_ids.filtered(lambda l: l.applied))
            batch.manual_line_count = len(batch.line_ids.filtered(lambda l: l.status == 'manual'))
            batch.review_line_count = len(batch.line_ids.filtered(lambda l: l.status == 'review'))

    def action_apply_automatic(self):
        return {
            'name': _('Aplicar propuestas automáticas'),
            'type': 'ir.actions.act_window',
            'res_model': 'aicia.account.pgc.recode.apply.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id,
                'default_apply_automatic': True,
                'default_apply_review_validated': False,
            }
        }

    def action_apply_selected(self):
        return {
            'name': _('Aplicar propuestas seleccionadas'),
            'type': 'ir.actions.act_window',
            'res_model': 'aicia.account.pgc.recode.apply.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id,
                'default_apply_automatic': True,
                'default_apply_review_validated': True,
            }
        }

    def action_revert(self):
        for batch in self:
            if batch.state not in ('applied', 'partially_applied'):
                raise UserError(_('Solo se pueden revertir lotes aplicados.'))

            applied_lines = batch.line_ids.filtered(lambda l: l.applied)
            if not applied_lines:
                raise UserError(_('No se han encontrado líneas aplicadas en este lote.'))

            for line in applied_lines:
                line.action_revert()

            batch.state = 'reverted'
