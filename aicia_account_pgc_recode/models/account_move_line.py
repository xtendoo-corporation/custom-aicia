from odoo import models, fields, api, _

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    aicia_pgc_recode_line_ids = fields.One2many('aicia.account.pgc.recode.line', 'move_line_id', string='Líneas de recodificación PGC')
    aicia_pgc_recode_last_batch_id = fields.Many2one('aicia.account.pgc.recode.batch', string='Último lote de recodificación PGC')
    aicia_pgc_recode_original_account_id = fields.Many2one('account.account', string='Cuenta original')
    aicia_pgc_recode_applied = fields.Boolean(string='Recodificado a PGC 2008', default=False)
