from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AccountAnalyticAccountInherit(models.Model):
    _inherit = 'account.analytic.account'

    clientes_asociados = fields.Many2many('res.partner', 'account_analytic_partner_rel', 'account_id', 'partner_id',
                                        string='Clientes Asociados',
                                        domain="[('id', 'not in', clientes_asociados_domain)]")

    @api.depends('partner_id', 'clientes_asociados')
    def _compute_clientes_asociados_domain(self):
        for record in self:
            excluded_partners = record.clientes_asociados.ids
            if record.partner_id:
                excluded_partners.append(record.partner_id.id)
            record.clientes_asociados_domain = excluded_partners

    clientes_asociados_domain = fields.Many2many('res.partner', compute='_compute_clientes_asociados_domain')

    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', tracking=True)

    # Campo para contar documentos DMS asociados al proyecto
    dms_document_count = fields.Integer(
        compute='_compute_dms_document_count',
        string='Documentos DMS'
    )

    def _compute_dms_document_count(self):
        """Cuenta los archivos DMS asociados al proyecto"""
        for record in self:
            if record.name:
                # Buscar el directorio del proyecto en DMS por el nombre de la cuenta analítica
                project_directory = self.env['dms.directory'].sudo().search([
                    ('name', '=', record.name)
                ], limit=1)

                if project_directory:
                    # Contar archivos en el directorio del proyecto
                    record.dms_document_count = self.env['dms.file'].sudo().search_count([
                        ('directory_id', '=', project_directory.id)
                    ])
                else:
                    record.dms_document_count = 0
            else:
                record.dms_document_count = 0

    def action_view_dms_documents(self):
        """Abre la vista de documentos DMS filtrada por el directorio del proyecto"""
        self.ensure_one()

        # Buscar el directorio del proyecto por el nombre de la cuenta analítica
        project_directory = self.env['dms.directory'].sudo().search([
            ('name', '=', self.name)
        ], limit=1)

        if not project_directory:
            raise UserError(_("No se encontró el directorio DMS para el proyecto '%s'") % self.name)

        # Acción para abrir la vista de ficheros DMS filtrada por el directorio del proyecto
        action = self.env.ref('portal_requests.action_custom_dms_documents').read()[0]
        action.update({
            'type': 'ir.actions.act_window',
            'name': _('Documentos DMS - %s') % self.name,
            'res_model': 'dms.file',  # Mostrar ficheros
            'view_mode': 'kanban,tree',  # Solo vista kanban y form, sin tree
            'domain': [('directory_id', '=', project_directory.id)],  # Solo ficheros del proyecto
            'context': {
                'default_directory_id': project_directory.id,
                'search_default_directory_id': project_directory.id,
                'create': False,  # Deshabilitar creación
                'edit': False,    # Solo lectura
                'delete': False,  # Sin eliminar
            },
            'target': 'current',
        })
        return action
