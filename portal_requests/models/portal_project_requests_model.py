from odoo import models, fields, api , _
from odoo.exceptions import UserError

class PortalProjectRequest(models.Model):
    _name = 'portal.project.request'
    _description = 'Portal Project Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Campo computado para usar name_get como display_name
    display_name = fields.Char(compute='_compute_display_name', store=True, index=True)

    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, tracking=True)
    work_group_id = fields.Many2one('portal.work.group', string='Grupo de Trabajo', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', tracking=True)
    partner_id_char = fields.Char(string='Cliente', store=True)
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    project_name = fields.Char(string='Project Name')
    signed_contract = fields.Binary(string="Signed Contract", attachment=True)
    budget_file = fields.Binary(string="Budget", attachment=True)
    signed_contract_filename = fields.Char(string="Signed Contract Filename")
    budget_file_filename = fields.Char(string="Budget Filename")
    approved = fields.Boolean(string='Approved', default=False)
    is_revised = fields.Boolean(string='Is revised', default=False, store=True)
    type= fields.Selection([
        ('new', 'Nuevo Proyecto'),
        ('end', 'Finalizar Proyecto'),
    ], string='Tipo', required=True)
    concept = fields.Char(string='Concept')
    created_analytic_id = fields.Many2one('account.analytic.account', string='Created Analytic Account')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Cuenta Analítica', tracking=True)
    project_count = fields.Integer(compute='_compute_analytic_count', string='Analytic Count')

    # Campo para contar documentos DMS asociados al proyecto
    dms_document_count = fields.Integer(
        compute='_compute_dms_document_count',
        string='Documentos DMS'
    )

    def _compute_analytic_count(self):
        for record in self:
            record.project_count = 1 if record.created_analytic_id else 0

    def _compute_dms_document_count(self):
        """Cuenta los archivos DMS asociados al proyecto"""
        for record in self:
            if record.created_analytic_id and record.project_name:
                # Buscar el directorio del proyecto en DMS
                project_directory = self.env['dms.directory'].sudo().search([
                    ('name', '=', record.project_name)
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

    def show_notificacion(self, title_char, text, type_char):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': type_char,
                'message': text,
                'title': title_char,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_approve(self):
        for record in self:
            if record.type == 'new':
                if not record.partner_id:
                    raise UserError(_("Por favor, seleccione un cliente para el proyecto."))
                analytic_account = record.create_new_project()
                record.created_analytic_id = analytic_account
                # Añadir mensaje al chatter cuando se crea
                mensaje = _("La cuenta %s ha sido creada por petición de %s") % (record.project_name, record.user_id.name)
                record.message_post(
                    body=mensaje,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note'
                )
                notification_text = _("La cuenta analítica %s ha sido creada correctamente.") % record.project_name
            else:
                if not record.analytic_account_id:
                    raise UserError(_("No se encontró la cuenta analítica asociada a esta solicitud."))
                notification_text = _("La cuenta analítica %s ha sido archivada correctamente.") % record.project_name
                record.created_analytic_id = record.analytic_account_id
                # Añadir mensaje al chatter antes de archivar
                mensaje = _("Ha sido archivada por petición de %s") % record.user_id.name
                if record.concept:
                    mensaje += _(" con el concepto: %s") % record.concept
                record.analytic_account_id.message_post(
                    body=mensaje,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note'
                )
                record.analytic_account_id.active = False
            record.approved = True
            record.is_revised = True

        return self.show_notificacion("¡Solicitud aprobada!", notification_text, "success")

    def action_reject(self):
        for record in self:
            record.approved = False
            record.is_revised = True

    def action_to_revise(self):
        for record in self:
            record.is_revised = False

    def create_new_project(self):
        # Buscar el plan analítico AICIA
        plan = self.env['account.analytic.plan'].sudo().search([('name', '=', 'AICIA')], limit=1)
        if not plan:
            raise UserError(_("No se encontró el plan analítico 'AICIA'. Por favor, créelo primero."))

        # Crear la cuenta analítica
        analytic_account = self.env['account.analytic.account'].sudo().create({
            'name': self.project_name,
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'plan_id': plan.id,
            'work_group_id': self.work_group_id.id if self.work_group_id else False,
        })

        # Buscar el directorio raíz de DMS para proyectos o crearlo si no existe
        root_directory = self.env['dms.directory'].sudo().search([
            ('name', '=', 'Proyectos'),
            ('is_root_directory', '=', True)
        ], limit=1)

        if not root_directory:
            # Buscar o crear almacenamiento para usar el filestore de la base de datos
            storage = self.env['dms.storage'].sudo().search([
                ('save_type', '=', 'filesystem')  # Usamos filesystem en lugar de database
            ], limit=1)

            if not storage:
                # Si no existe, creamos uno nuevo
                storage = self.env['dms.storage'].sudo().create({
                    'name': 'Almacenamiento AICIA',
                    'save_type': 'filesystem',  # Tipo filesystem para usar una ruta específica
                    'company_id': self.company_id.id,
                    'root_directory_path': '/var/lib/docker/volumes/aicia_4_filestore/_data/filestore/aicia/dms',  # Ruta correcta del volumen Docker
                })

            root_directory = self.env['dms.directory'].sudo().create({
                'name': 'Proyectos',
                'storage_id': storage.id,
                'is_root_directory': True,
            })

        # Crear directorio del proyecto
        project_directory = self.env['dms.directory'].sudo().create({
            'name': self.project_name,
            'parent_id': root_directory.id,
            'storage_id': root_directory.storage_id.id,
        })

        # Crear archivos en DMS y sus enlaces
        if self.signed_contract:
            # Crear archivo en DMS con prefijo del proyecto
            contract_filename = f"{self.project_name}-{self.signed_contract_filename or 'contrato_firmado.pdf'}"
            dms_contract = self.env['dms.file'].sudo().create({
                'name': contract_filename,
                'directory_id': project_directory.id,
                'content': self.signed_contract,
            })
            # Crear enlace en la cuenta analítica
            self.env['ir.attachment'].sudo().create({
                'name': contract_filename,
                'res_model': 'account.analytic.account',
                'res_id': analytic_account.id,
                'type': 'binary',
                'dms_file_id': dms_contract.id,
            })

        if self.budget_file:
            # Crear archivo en DMS con prefijo del proyecto
            budget_filename = f"{self.project_name}-{self.budget_file_filename or 'presupuesto.pdf'}"
            dms_budget = self.env['dms.file'].sudo().create({
                'name': budget_filename,
                'directory_id': project_directory.id,
                'content': self.budget_file,
            })
            # Crear enlace en la cuenta analítica
            self.env['ir.attachment'].sudo().create({
                'name': budget_filename,
                'res_model': 'account.analytic.account',
                'res_id': analytic_account.id,
                'type': 'binary',
                'dms_file_id': dms_budget.id,
            })

        return analytic_account

    def action_view_analytic(self):
        self.ensure_one()
        if not self.created_analytic_id:
            return

        action = {
            "type": "ir.actions.act_window",
            "res_model": "account.analytic.account",
            "view_mode": "form",
            "res_id": self.created_analytic_id.id,
            "target": "current",
        }
        return action

    def action_view_dms_documents(self):
        """Abre la vista personalizada de documentos DMS filtrada por el directorio del proyecto"""
        self.ensure_one()

        # Buscar el directorio del proyecto
        project_directory = self.env['dms.directory'].sudo().search([
            ('name', '=', self.project_name)
        ], limit=1)

        if not project_directory:
            raise UserError(_("No se encontró el directorio DMS para el proyecto '%s'") % self.project_name)

        # Obtener la acción personalizada y modificar el dominio y contexto
        action = self.env.ref('portal_requests.action_custom_dms_documents').read()[0]
        action.update({
            'name': _('Documentos DMS - %s') % self.project_name,
            'domain': [('directory_id', '=', project_directory.id)],
            'context': {
                'default_directory_id': project_directory.id,
                'search_default_directory_id': project_directory.id,
                'create': False,  # Deshabilitar creación
                'edit': False,    # Solo lectura
                'delete': False,  # Sin eliminar
            },
        })
        return action

    @api.depends('project_name', 'type')
    def _compute_display_name(self):
        for record in self:
            name = dict(record.name_get())[record.id]
            record.display_name = name

    def name_get(self):
        result = []
        for record in self:
            if record.type == 'new':
                prefix = _("Nuevo proyecto: ")
            else:
                prefix = _("Finalizar proyecto: ")
            name = prefix + (record.project_name or _("#%s") % record.id)
            result.append((record.id, name))
        return result
