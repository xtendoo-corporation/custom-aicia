from odoo import models, fields, api

class AccountAnalyticAccountInherit(models.Model):
    _inherit = ['account.analytic.account', 'portal.mixin']
    _name = 'account.analytic.account'

    sujeto_convenio = fields.Boolean(string='Sujeto a Convenio', tracking=True)

    clientes_asociados = fields.Many2many('res.partner', 'account_analytic_partner_rel', 'account_id', 'partner_id',
                                        string='Clientes Asociados',
                                        domain="[('id', 'not in', clientes_asociados_domain)]")
    observaciones = fields.Text(string='Observaciones', tracking=True)


    @api.depends('partner_id', 'clientes_asociados')
    def _compute_clientes_asociados_domain(self):
        for record in self:
            excluded_partners = record.clientes_asociados.ids
            if record.partner_id:
                excluded_partners.append(record.partner_id.id)
            record.clientes_asociados_domain = excluded_partners

    clientes_asociados_domain = fields.Many2many('res.partner', compute='_compute_clientes_asociados_domain')

    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', tracking=True)
    responsible_domain = fields.Many2many('res.users', compute='_compute_responsible_domain')
    work_group_boss_id = fields.Many2one('res.users', string='Jefe de Equipo', related='work_group_id.equip_boss', store=True)

    @api.depends('work_group_id')
    def _compute_responsible_domain(self):
        for record in self:
            if record.work_group_id:
                record.responsible_domain = record.work_group_id.user_ids.ids
            else:
                record.responsible_domain = []

    responsible_id = fields.Many2one('res.users', string='Responsable', tracking=True,
                                     domain="[('id', 'in', responsible_domain)]")

    user_can_edit = fields.Boolean(string='User Can Edit', compute='_compute_user_can_edit')

    @api.depends('work_group_id', 'responsible_id')
    def _compute_user_can_edit(self):
        for record in self:
            user = self.env.user
            if user.has_group('portal_requests.group_director_manager'):
                record.user_can_edit = True
            elif record.responsible_id == user:
                record.user_can_edit = True
            else:
                record.user_can_edit = False

    def _compute_attachment_count(self):
        Attachment = self.env['ir.attachment']
        for record in self:
            attachment_count = Attachment.search_count([
                ('res_model', '=', 'account.analytic.account'),
                ('res_id', '=', record.id)
            ])
            record.attachment_count = attachment_count

    attachment_count = fields.Integer(string='Attachment Count', compute='_compute_attachment_count')

    def _compute_invoice_count(self):
        """Cuenta las facturas asociadas a esta cuenta analítica"""
        for record in self:
            # Buscar facturas que tengan líneas con distribución analítica para este proyecto
            invoice_lines = self.env['account.move.line'].search([
                ('analytic_distribution', '!=', False),
                ('move_id.move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']),
                ('move_id.state', '!=', 'cancel')
            ])

            # Filtrar las que contienen este analytic account en su distribución
            # analytic_distribution es un JSON como: {"42": 100.0} o {"42,43": 50.0}
            invoice_ids = set()
            for line in invoice_lines:
                if line.analytic_distribution:
                    for key in line.analytic_distribution.keys():
                        # Las claves pueden ser "42" o "42,43" (múltiples IDs separados por coma)
                        analytic_ids = [int(id_str) for id_str in key.split(',')]
                        if record.id in analytic_ids:
                            invoice_ids.add(line.move_id.id)
                            break

            record.invoice_count = len(invoice_ids)

    invoice_count = fields.Integer(string='Facturas Asociadas', compute='_compute_invoice_count')

    def action_view_invoices(self):
        """Abre las facturas asociadas a esta cuenta analítica"""
        # Buscar facturas que tengan líneas con distribución analítica para este proyecto
        invoice_lines = self.env['account.move.line'].search([
            ('analytic_distribution', '!=', False),
            ('move_id.move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']),
            ('move_id.state', '!=', 'cancel')
        ])

        # Filtrar las que contienen este analytic account en su distribución
        # analytic_distribution es un JSON como: {"42": 100.0} o {"42,43": 50.0}
        invoice_ids = []
        for line in invoice_lines:
            if line.analytic_distribution:
                for key in line.analytic_distribution.keys():
                    # Las claves pueden ser "42" o "42,43" (múltiples IDs separados por coma)
                    analytic_ids = [int(id_str) for id_str in key.split(',')]
                    if self.id in analytic_ids:
                        if line.move_id.id not in invoice_ids:
                            invoice_ids.append(line.move_id.id)
                        break

        return {
            'name': 'Facturas del Proyecto',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', invoice_ids)],
            'context': {'create': False},
            'target': 'current',
        }

    def action_open_attachments(self):
        return {
            'name': 'Adjuntos',
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'tree,kanban,form',
            'domain': [
                ('res_model', '=', 'account.analytic.account'),
                ('res_id', '=', self.id)
            ],
            'context': {
                'default_res_model': 'account.analytic.account',
                'default_res_id': self.id,
            },
            'target': 'current',
        }
