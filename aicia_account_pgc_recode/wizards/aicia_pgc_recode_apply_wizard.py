from odoo import models, fields, api, _

class AiciaAccountPgcRecodeApplyWizard(models.TransientModel):
    _name = 'aicia.account.pgc.recode.apply.wizard'
    _description = 'Aplicar lote de recodificación PGC'

    batch_id = fields.Many2one('aicia.account.pgc.recode.batch', string='Lote', required=True)
    apply_automatic = fields.Boolean(string='Aplicar propuestas automáticas', default=True)
    apply_review_validated = fields.Boolean(string='Aplicar propuestas revisadas y validadas', default=False)
    create_missing_accounts = fields.Boolean(string='Crear cuentas destino inexistentes', default=True)

    def action_apply(self):
        self.ensure_one()

        domain = [
            ('batch_id', '=', self.batch_id.id),
            ('applied', '=', False)
        ]
        statuses = []
        if self.apply_automatic:
            statuses.append('automatic')
        if self.apply_review_validated:
            statuses.append('review')

        if not statuses:
            return {'type': 'ir.actions.act_window_close'}

        domain.append(('status', 'in', statuses))

        lines = self.env['aicia.account.pgc.recode.line'].search(domain)

        for line in lines:
            if line.status == 'review' and not line.new_account_id and not (self.create_missing_accounts and line.new_account_code):
                continue
            line.action_apply(create_missing=self.create_missing_accounts)

        unapplied = self.env['aicia.account.pgc.recode.line'].search_count([
            ('batch_id', '=', self.batch_id.id),
            ('applied', '=', False),
            ('status', 'in', ('automatic', 'review'))
        ])

        if unapplied == 0:
            self.batch_id.state = 'applied'
        else:
            self.batch_id.state = 'partially_applied'

        return {'type': 'ir.actions.act_window_close'}
