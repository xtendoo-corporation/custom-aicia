from odoo import _, models, fields, api
from odoo.exceptions import AccessError, UserError


class PortalHrExpensiveRequest(models.Model):
    _name = 'portal.hr.expensive.request'
    _description = 'Portal HR Expensive Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin', 'portal.request.notify.mixin']
    _rec_name = 'computed_name'

    _notify_state_field = 'status'
    _notify_portal_route = '/my/expenses'


    computed_name = fields.Char('Computed Name', compute='_compute_name')
    def _compute_name(self):
        for record in self:
            record.computed_name = F"Solicitud de Gasto para {record.project.name}"

    user_id = fields.Many2one('res.users', string='User', required=True)
    type = fields.Selection([
        ('bienes_servicios', 'Compra de bienes o servicios'),
        ('material_inventariable', 'Pago de material inventariable'),
        ('liquidacion_gastos', 'Liquidación de gastos'),
        ('gratificacion', 'Solicitud de gratificación'),
    ], string='Tipo', required=True)
    project = fields.Many2one('account.analytic.account', string='Project', required=True)
    work_group_id = fields.Many2one('portal.work.group', related='project.work_group_id', string='Grupo de Trabajo',
                                    store=True)
    equip_boss = fields.Many2one('res.users', related='work_group_id.equip_boss', string='Jefe de Equipo', store=True)
    status = fields.Selection([('to_revise', 'Volver a revisar'),
                               ('approved_by_boss_group', 'Aprobación del Jefe de Equipo'),
                               ('approved_purchase_responsible', 'Aprobación del Responsable de proveedores'),
                               ('approved_director', 'Aprobación del Director Gerente'),
                               ('approve', 'Aprobada'), ("rejected", 'Rechazada')
                               ], 'Estado',
                              default='approved_by_boss_group', tracking=True)
    is_more = fields.Boolean(string='Es más de 10000€', default=False)
    invoice_created = fields.Many2one('account.move', string='Invoice Created')
    invoice_count = fields.Integer(default=1, string='Invoice Count')
    expense_id = fields.Many2one('hr.expense', string='Gasto', copy=False, readonly=True)
    is_paid = fields.Boolean(string='Pagada', default=False, copy=False, tracking=True)
    paid_date = fields.Date(string='Fecha de pago', copy=False)
    paid_by_id = fields.Many2one('res.users', string='Pagada por', copy=False)
    # Liquidación de gastos: el empleado declara el total adelantado y sube por
    # separado los tickets (se reembolsan como gasto de hr_expense) y las
    # facturas a nombre de AICIA (se registran como facturas de proveedor
    # cuya deuda se traslada al empleado). Ver _create_liquidation_documents.
    currency_id = fields.Many2one('res.currency', compute='_compute_currency_id')
    liquidation_amount = fields.Monetary(
        string='Importe total adelantado', currency_field='currency_id', tracking=True,
        help='Importe que el empleado ha adelantado: facturas a nombre de AICIA más tickets.')
    employee_invoice_attachment_ids = fields.Many2many(
        'ir.attachment', 'portal_expense_employee_invoice_attachment_rel',
        'request_id', 'attachment_id', string='Facturas a nombre de AICIA', copy=False)
    payment_order_attachment_ids = fields.Many2many(
        'ir.attachment', 'portal_expense_payment_order_attachment_rel',
        'request_id', 'attachment_id', string='Orden de pago', copy=False,
        help='Archivo con la orden de pago de la liquidación (cualquier formato).')
    ticket_attachment_ids = fields.Many2many(
        'ir.attachment', string='Gastos (tickets)', compute='_compute_ticket_attachment_ids',
        help='Tickets adjuntos a la liquidación (todo menos facturas a nombre de AICIA y orden de pago).')
    employee_invoice_ids = fields.One2many(
        'account.move', 'employee_liquidation_id', string='Facturas pagadas por el empleado')
    employee_invoice_count = fields.Integer(compute='_compute_liquidation_amounts')
    liquidation_invoices_amount = fields.Monetary(
        string='Importe de las facturas', currency_field='currency_id',
        compute='_compute_liquidation_amounts')
    liquidation_tickets_amount = fields.Monetary(
        string='Importe de los tickets', currency_field='currency_id',
        compute='_compute_liquidation_amounts')
    liquidation_difference = fields.Monetary(
        string='Diferencia sin justificar', currency_field='currency_id',
        compute='_compute_liquidation_amounts',
        help='Total declarado menos facturas y tickets registrados en contabilidad.')
    is_reimbursed = fields.Boolean(
        string='Reembolsada al empleado', compute='_compute_is_reimbursed')
    inmovilizado_account_id = fields.Many2one('account.account', string='Cuenta de Inmovilizado')
    # inmovilizado_type = fields.Selection([
    #     ('computer_equipment', 'Equipo informático'),
    #     ('furniture', 'Mobiliario'),
    #     ('other', 'Otro'),], string='Tipo de Inmovilizado')
    bank_account = fields.Char(string='Cuenta Bancaria')

    @api.depends('project.company_id')
    def _compute_currency_id(self):
        for record in self:
            record.currency_id = (record.project.company_id or self.env.company).currency_id

    @api.depends(
        'liquidation_amount', 'employee_invoice_ids.amount_total', 'employee_invoice_ids.state',
        'expense_id.total_amount_currency')
    def _compute_liquidation_amounts(self):
        for record in self:
            invoices = record.sudo().employee_invoice_ids.filtered(
                lambda move: move.state != 'cancel')
            invoices_amount = sum(invoices.mapped('amount_total'))
            tickets_amount = record.sudo().expense_id.total_amount_currency
            record.employee_invoice_count = len(invoices)
            record.liquidation_invoices_amount = invoices_amount
            record.liquidation_tickets_amount = tickets_amount
            record.liquidation_difference = record.liquidation_amount - invoices_amount - tickets_amount

    def _employee_payable_lines(self):
        """Apuntes a pagar al empleado: el traslado de cada factura y el
        asiento del gasto de los tickets, en la cuenta a pagar de su contacto."""
        self.ensure_one()
        record = self.sudo()
        moves = record.employee_invoice_ids.employee_transfer_move_id | record.expense_id.account_move_id
        employees = record.expense_id.employee_id | record.employee_invoice_ids.paid_by_employee_id
        partner = employees.work_contact_id
        return moves.filtered(lambda move: move.state == 'posted').line_ids.filtered(
            lambda line: line.account_id.account_type == 'liability_payable' and line.partner_id in partner)

    liquidation_paid_amount = fields.Monetary(
        string='Reembolsado', currency_field='currency_id',
        compute='_compute_reimbursement_amounts',
        help='Importe ya pagado al empleado.')
    liquidation_pending_amount = fields.Monetary(
        string='Pendiente de reembolsar', currency_field='currency_id',
        compute='_compute_reimbursement_amounts',
        help='Importe contabilizado que todavía no se ha pagado al empleado.')

    @api.depends(
        'employee_invoice_ids.employee_transfer_move_id.line_ids.amount_residual',
        'expense_id.account_move_id.line_ids.amount_residual')
    def _compute_reimbursement_amounts(self):
        for record in self:
            owed = paid = pending = 0.0
            if record.type == 'liquidacion_gastos' and record.id:
                lines = record._employee_payable_lines()
                owed = -sum(lines.mapped('balance'))
                pending = -sum(lines.mapped('amount_residual'))
                paid = owed - pending
            record.liquidation_paid_amount = paid
            record.liquidation_pending_amount = pending

    def _has_documents_pending_accounting(self):
        self.ensure_one()
        record = self.sudo()
        draft_invoices = record.employee_invoice_ids.filtered(lambda move: move.state == 'draft')
        expense_pending = record.expense_id and not record.expense_id.account_move_id
        return bool(draft_invoices or expense_pending)

    @api.depends(
        'employee_invoice_ids.employee_transfer_move_id.line_ids.reconciled',
        'expense_id.account_move_id.line_ids.reconciled')
    def _compute_is_reimbursed(self):
        for record in self:
            if record.type != 'liquidacion_gastos' or not record.id:
                record.is_reimbursed = False
                continue
            lines = record._employee_payable_lines()
            record.is_reimbursed = (
                bool(lines)
                and all(lines.mapped('reconciled'))
                and not record._has_documents_pending_accounting()
            )

    project_credit = fields.Float(string='Saldo del Proyecto', compute='_compute_project_credit')
    @api.depends('project')
    def _compute_project_credit(self):
        for record in self:
            if record.project:
                record.project_credit = record.project.balance
            else:
                record.project_credit = 0.0
    group_credit = fields.Float(string='Saldo del Grupo de Trabajo', compute='_compute_group_credit')
    @api.depends('work_group_id')
    def _compute_group_credit(self):
        for record in self:
            if record.work_group_id:
                analytic_accounts = self.env['account.analytic.account'].search([('work_group_id', '=', record.work_group_id.id)])
                balance = 0.0
                for account in analytic_accounts:
                    balance += account.balance
                record.group_credit = balance
            else:
                record.group_credit = 0.0

    @api.depends('status')
    def _compute_show_solicitar_revision(self):
        # group_administrative implica group_equip_boss (ver res_group_data.xml),
        # así que has_group('group_equip_boss') también es True para el
        # Administrativo. Hay que excluirlo explícitamente para que sí vea
        # el botón cuando su propia solicitud necesita ser reenviada.
        user = self.env.user
        is_boss = (
            user.has_group('portal_requests.group_equip_boss')
            and not user.has_group('portal_requests.group_administrative')
        ) or user.has_group('portal_requests.group_intern_partner_responsible')
        for rec in self:
            rec.show_solicitar_revision = (rec.status == 'to_revise') and (not is_boss)

    show_solicitar_revision = fields.Boolean(
        string='Mostrar Solicitar Revisión',
        compute='_compute_show_solicitar_revision',
        store=False,
    )

    show_approve_button = fields.Boolean(
        string='Mostrar Botón Aprobar',
        compute='_compute_show_approve_button',
        store=False,
    )

    @api.depends('status')
    @api.depends_context('uid')
    def _compute_show_approve_button(self):
        """En cada etapa puede aprobar quien tenga el grupo correspondiente,
        salvo el primer paso: "Aprobación del Jefe de Equipo" solo la hace el
        Jefe de Equipo del grupo, nunca el Administrativo (aunque este
        implique group_equip_boss)."""
        user = self.env.user
        for rec in self:
            if rec.status == 'approved_by_boss_group':
                rec.show_approve_button = rec.work_group_id._is_equip_boss_step_approver(user)
            elif rec.status == 'approved_purchase_responsible':
                rec.show_approve_button = user.has_group(rec._second_approver_group_xmlid())
            elif rec.status == 'approved_director':
                rec.show_approve_button = user.has_group('portal_requests.group_director_manager')
            else:
                rec.show_approve_button = False

    show_mark_paid_button = fields.Boolean(
        string='Mostrar Botón Marcar como Pagada',
        compute='_compute_show_mark_paid_button',
        store=False,
    )

    @api.depends('type', 'status', 'is_paid')
    @api.depends_context('uid')
    def _compute_show_mark_paid_button(self):
        is_intern_partner = self.env.user.has_group('portal_requests.group_intern_partner_responsible')
        for rec in self:
            rec.show_mark_paid_button = is_intern_partner and rec._is_gratification_pending_payment()

    def _is_gratification_pending_payment(self):
        self.ensure_one()
        return self.type == 'gratificacion' and self.status == 'approve' and not self.is_paid

    show_project_credit = fields.Boolean(string='Mostrar Saldo del Proyecto', compute='_compute_show_project_credit')
    @api.depends('user_id', 'project')
    def _compute_show_project_credit(self):
        for record in self:
            if self.env.user.has_group('portal_requests.group_director_manager') or self.env.user.has_group('portal_requests.group_personnel_purchase_responsible') or self.env.user == record.equip_boss  or self.env.user == record.project.responsible_id:
                record.show_project_credit = True
            else:
                record.show_project_credit = False

    show_group_credit = fields.Boolean(string='Mostrar Saldo del Grupo', compute='_compute_show_group_credit')

    @api.depends('user_id', 'project')
    def _compute_show_group_credit(self):
        for record in self:
            if self.env.user.has_group('portal_requests.group_director_manager') or self.env.user.has_group('portal_requests.group_personnel_purchase_responsible') or self.env.user == record.equip_boss:
                record.show_group_credit = True
            else:
                record.show_group_credit = False

    def _second_approver_group_xmlid(self):
        """Grupo que actúa como segundo aprobador según el tipo de solicitud.

        La gratificación la revisa el Responsable de Clientes y Becarios
        (clientes@aicia.es); el resto de tipos, el Responsable de Personal y
        compras (personal@aicia.es).
        """
        self.ensure_one()
        if self.type == 'gratificacion':
            return 'portal_requests.group_intern_partner_responsible'
        return 'portal_requests.group_personnel_purchase_responsible'

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
        if self.status == 'approved_by_boss_group' and self.work_group_id._is_equip_boss_step_approver(self.env.user):
            self.status = 'approved_purchase_responsible'
            user_to_notify = self.env['res.users'].sudo().search(
                [('group_ids', 'in', self.env.ref(self._second_approver_group_xmlid()).id)])
            self._send_purchase_request_mail('approved_by_boss_group', user_to_notify, self.user_id.name, self.project.name)
            if self.type == 'gratificacion':
                return self.show_notificacion(
                    "¡Aprobación registrada!",
                    "La solicitud se ha enviado al responsable de clientes y becarios para su revisión.",
                    "success",
                )
            return self.show_notificacion("¡Aprobación registrada!", "La solicitud ha sido aprobada y enviada al responsable de personal y compras para su revisión.", "success")
        elif self.env.user.has_group(self._second_approver_group_xmlid()) and self.status == 'approved_purchase_responsible':
            # El Director Gerente solo interviene cuando el importe supera los 10.000€.
            if self.is_more:
                self.status = 'approved_director'
                user_to_notify = self.env['res.users'].search(
                    [('group_ids', 'in', self.env.ref('portal_requests.group_director_manager').id)])
                self._send_purchase_request_mail('approved_purchase_responsible', user_to_notify, self.user_id.name,
                                                 self.project.name)
                return self.show_notificacion("¡Aprobación registrada!",
                                              "La solicitud ha sido aprobada y enviada al director gerente para su revisión.",
                                              "success")
            return self._complete_approval()
        elif self.env.user.has_group('portal_requests.group_director_manager') and self.status == 'approved_director':
            return self._complete_approval()

        elif self.status == 'to_revise':
            # A petición del cliente, el Administrativo vuelve a pasar por
            # la aprobación del Jefe de Equipo al reenviar, igual que al
            # solicitar por primera vez.
            if self.equip_boss == self.user_id:
                user_to_notify = self.env['res.users'].sudo().search([('group_ids', 'in', self.env.ref(self._second_approver_group_xmlid()).id)])
                self.status = 'approved_purchase_responsible'
            else:
                user_to_notify = [self.work_group_id.equip_boss]
                self.status = 'approved_by_boss_group'
            self._send_purchase_request_mail('to_revise', user_to_notify, self.user_id.name, self.project.name)
            return self.show_notificacion("¡Nueva Revision!",
                                          "Su solicitud de nueva revision ha sido registrada correctamente.",
                                          "success")
        print("Approved HR Expensive Request")

    # def action_reject(self):
    #     print("Rejected HR Expensive Request")

    def _get_balance_work_group(self):
        self.ensure_one()
        work_group = self.work_group_id
        balance = 0.0
        if work_group:
            analytic_accounts = self.env['account.analytic.account'].search([('work_group_id', '=', work_group.id)])
            for account in analytic_accounts:
                balance += account.balance
        return balance

    def _complete_approval(self):
        """Cierre de la aprobación final. Las gratificaciones no generan factura:
        quedan aprobadas y pendientes de marcar como pagadas. Las liquidaciones
        de gastos se reembolsan al empleado mediante un gasto de hr_expense."""
        self.status = 'approve'
        if self.type == 'liquidacion_gastos':
            self._create_liquidation_documents()
            return self.show_notificacion(
                "¡Solicitud aprobada!",
                "Se han creado las facturas y el gasto del empleado, pendientes de revisar "
                "en contabilidad y reembolsar.",
                "success",
            )
        if self.type == 'gratificacion':
            return self.show_notificacion(
                "¡Solicitud aprobada!",
                "La gratificación ha sido aprobada. Pendiente de marcar como pagada.",
                "success",
            )
        self._create_purchase_invoice()
        return self.show_notificacion("¡Solicitud aprobada!",
                                      "La factura borrador ha sido creada correctamente.", "success")

    def action_mark_paid(self):
        self.ensure_one()
        if not self.env.user.has_group('portal_requests.group_intern_partner_responsible'):
            raise AccessError(_('Solo el Responsable de Clientes y Becarios puede marcar una gratificación como pagada.'))
        if self.type != 'gratificacion':
            raise UserError(_('Solo las solicitudes de gratificación se pueden marcar como pagadas.'))
        if self.is_paid:
            raise UserError(_('La gratificación ya está marcada como pagada.'))
        if self.status != 'approve':
            raise UserError(_('La gratificación debe estar aprobada para marcarla como pagada.'))
        self.write({
            'is_paid': True,
            'paid_date': fields.Date.context_today(self),
            'paid_by_id': self.env.user.id,
        })
        self.message_post(body=_('Gratificación marcada como pagada por %s.', self.env.user.name))

    def _get_ticket_attachments(self):
        """Adjuntos de la liquidación que son tickets: todos menos las facturas
        a nombre de AICIA y la orden de pago."""
        self.ensure_one()
        domain = ['&', ('res_model', '=', self._name), ('res_id', '=', self.id)]
        if self.expense_id:
            # Al aprobar, los tickets pasan al gasto de hr_expense.
            domain = ['|', *domain, '&', ('res_model', '=', 'hr.expense'), ('res_id', '=', self.expense_id.id)]
        attachments = self.env['ir.attachment'].sudo().search(domain, order='id')
        return attachments - self.sudo().employee_invoice_attachment_ids - self.sudo().payment_order_attachment_ids

    @api.depends('type', 'expense_id', 'employee_invoice_attachment_ids', 'payment_order_attachment_ids')
    def _compute_ticket_attachment_ids(self):
        for record in self:
            record.ticket_attachment_ids = (
                record._get_ticket_attachments()
                if record.id and record.type == 'liquidacion_gastos' else False)

    def _create_purchase_invoice(self):
        self.ensure_one()
        # Lógica para crear la factura de compra en blanco con el adjunto y la distribución contable
        # El analytic_distribution debe ser un JSON con formato: {str(account_id): percentage}
        analytic_distribution = {str(self.project.id): 100.0}
        attachments = self.env['ir.attachment'].search(
            [('res_model', '=', 'portal.hr.expensive.request'), ('res_id', '=', self.id)])

        invoice_vals = {'move_type': 'in_invoice'}
        # Header analytic field is added by aicia_account_move_analytic_account
        if 'analytic_distribution' in self.env['account.move']._fields:
            invoice_vals['analytic_distribution'] = analytic_distribution
        invoice = self.env['account.move'].create(invoice_vals)
        # The invoice document is the first attachment that is not an inventory list
        attachments = attachments.filtered(
            lambda att: not (att.name or '').startswith('inventario_')
        )[:1]
        for attachment in attachments:
            attachment.write({
                'res_model': 'account.move',
                'res_id': invoice.id,
            })
        self.invoice_created = invoice.id
        if attachments:
            invoice.message_main_attachment_id = attachments[:1]
        if self.type in ('material_inventariable', 'liquidacion_gastos'):
            attachments = self.env['ir.attachment'].search(
                [('res_model', '=', 'portal.hr.expensive.request'), ('res_id', '=', self.id)])
            for attachment in attachments:
                attachment.write({
                    'res_model': 'account.move',
                    'res_id': invoice.id,
                })
        if self.type == 'material_inventariable':
            for line in invoice.invoice_line_ids:
                line.account_id = self.inmovilizado_account_id.id

    def _get_requester_employee(self):
        """Ficha de empleado del solicitante, a quien se reembolsa el gasto.
        Si tiene varias, se prefiere la de la compañía activa."""
        self.ensure_one()
        employees = self.env['hr.employee'].sudo().search(
            [('user_id', '=', self.user_id.id)])
        employee = (
            employees.filtered(lambda emp: emp.company_id == self.env.company)[:1]
            or employees[:1]
        )
        if not employee:
            raise UserError(_(
                'El solicitante %s no tiene ficha de empleado. Créela antes de '
                'aprobar la liquidación de gastos para poder reembolsarle el importe.',
                self.user_id.name,
            ))
        if not employee.primary_bank_account_id:
            raise UserError(_(
                'El empleado %s no tiene cuenta bancaria en su ficha. Indíquela antes de '
                'aprobar la liquidación de gastos para poder transferirle el reembolso.',
                employee.name,
            ))
        return employee

    def _create_liquidation_documents(self):
        """Documentos contables de una liquidación de gastos aprobada.

        - Cada factura a nombre de AICIA: factura de proveedor en borrador,
          marcada como pagada por el empleado. Al contabilizarla, su deuda se
          traslada del proveedor al empleado (account.move._post).
        - Los tickets: un gasto de hr_expense pagado por el empleado.
        Así todo lo que se debe al empleado queda en su cuenta a pagar y se
        le reembolsa en un único pago."""
        self.ensure_one()
        employee = self._get_requester_employee()
        attachments = self.env['ir.attachment'].sudo().search(
            [('res_model', '=', self._name), ('res_id', '=', self.id)])
        invoice_attachments = attachments & self.sudo().employee_invoice_attachment_ids
        # La orden de pago no es un ticket ni una factura.
        ticket_attachments = attachments - invoice_attachments - self.sudo().payment_order_attachment_ids
        for attachment in invoice_attachments:
            self._create_employee_invoice(employee, attachment)
        # Sin documentos clasificados (liquidaciones anteriores) también se
        # crea el gasto: Contabilidad lo completa a partir de la solicitud.
        if ticket_attachments or not invoice_attachments:
            self._create_employee_expense(employee, ticket_attachments)

    def _create_employee_invoice(self, employee, attachment):
        """Factura de proveedor en borrador para una factura a nombre de
        AICIA que ha pagado el empleado. Contabilidad indica el proveedor y
        el desglose de base e IVA. Se crea con sudo porque los aprobadores del
        portal no tienen permisos de Contabilidad."""
        self.ensure_one()
        invoice_vals = {
            'move_type': 'in_invoice',
            'company_id': employee.company_id.id,
            'employee_liquidation_id': self.id,
            'paid_by_employee_id': employee.id,
        }
        # Campo de analítica en cabecera de aicia_account_move_analytic_account
        if 'analytic_distribution' in self.env['account.move']._fields:
            invoice_vals['analytic_distribution'] = {str(self.project.id): 100.0}
        invoice = self.env['account.move'].sudo().with_company(employee.company_id).create(invoice_vals)
        attachment.write({'res_model': 'account.move', 'res_id': invoice.id})
        invoice.message_main_attachment_id = attachment
        invoice.message_post(body=_(
            'Factura a nombre de AICIA pagada por el empleado %(employee)s. No se paga al '
            'proveedor: al contabilizarla, la deuda pasa al empleado (liquidación de gastos '
            '%(request)s, aprobada por %(user)s).',
            employee=employee.name, request=self.computed_name, user=self.env.user.name,
        ))
        return invoice

    def _create_employee_expense(self, employee, attachments):
        """Gasto de hr_expense con los tickets, pagado por el empleado.

        Queda en borrador para que Contabilidad lo revise, lo apruebe y lo
        contabilice. El importe se propone a partir del total declarado: todo
        si no hay facturas o, si las hay, el resto cuando estén contabilizadas
        (_update_liquidation_tickets_amount). Se crea con sudo porque los
        aprobadores del portal no tienen permisos de Gastos."""
        self.ensure_one()
        expense_vals = {
            'name': _('Liquidación de gastos - %s', self.project.name),
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
            'product_id': self.env.ref('hr_expense.product_product_no_cost').id,
            'payment_mode': 'own_account',
            'analytic_distribution': {str(self.project.id): 100.0},
            'description': _('Solicitud de gasto del portal: %s', self.computed_name),
        }
        expense = self.env['hr.expense'].sudo().create(expense_vals)
        if self.liquidation_amount and not self.sudo().employee_invoice_attachment_ids:
            self._set_expense_amount(expense, self.liquidation_amount)
        attachments.write({'res_model': 'hr.expense', 'res_id': expense.id})
        if attachments:
            expense.message_main_attachment_id = attachments[:1]
        expense.message_post(body=_(
            'Liquidación de gastos aprobada en el portal por %s.', self.env.user.name))
        self.expense_id = expense

    def _update_liquidation_tickets_amount(self):
        """Cuando todas las facturas de la liquidación están contabilizadas,
        propone como importe de los tickets el total declarado menos las
        facturas, mientras el gasto siga en borrador."""
        for record in self.sudo():
            expense = record.expense_id
            invoices = record.employee_invoice_ids.filtered(lambda move: move.state != 'cancel')
            if (not record.liquidation_amount or not expense or expense.state != 'draft'
                    or invoices.filtered(lambda move: move.state == 'draft')):
                continue
            remaining = record.liquidation_amount - sum(invoices.mapped('amount_total'))
            record._set_expense_amount(expense, max(remaining, 0.0))

    @api.model
    def _set_expense_amount(self, expense, amount):
        """Importe de un gasto sin coste de producto. Además del total hay
        que fijar el precio unitario, que es lo que se contabiliza: en el
        formulario lo hace el onchange _inverse_total_amount_currency."""
        expense.total_amount_currency = amount
        expense._inverse_total_amount_currency()

    def action_register_employee_payment(self):
        """Abre el registro de pago con todo lo pendiente de reembolsar al
        empleado (facturas trasladadas y tickets) para pagarlo de una vez."""
        self.ensure_one()
        lines = self._employee_payable_lines().filtered(lambda line: not line.reconciled)
        if not lines:
            raise UserError(_(
                'No hay importes pendientes de reembolsar. Contabilice las facturas y el '
                'gasto de la liquidación antes de pagar al empleado.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reembolsar al empleado'),
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': lines.ids,
                'default_group_payment': True,
            },
        }

    def action_view_employee_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas pagadas por el empleado'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('employee_liquidation_id', '=', self.id)],
            'context': {'default_move_type': 'in_invoice'},
        }

    def action_view_expense(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gasto'),
            'res_model': 'hr.expense',
            'view_mode': 'form',
            'res_id': self.expense_id.id,
        }

    def _get_accounting_amount(self):
        """Importe y moneda del documento contable generado al aprobar
        (factura de proveedor o gasto del empleado). En la liquidación de
        gastos, el total declarado por el empleado."""
        self.ensure_one()
        if self.type == 'liquidacion_gastos' and self.liquidation_amount:
            return self.liquidation_amount, self.currency_id
        if self.invoice_created:
            invoice = self.invoice_created.sudo()
            return invoice.amount_total, invoice.currency_id
        if self.expense_id:
            expense = self.expense_id.sudo()
            return expense.total_amount_currency, expense.currency_id
        return None, self.env['res.currency']

    def _reject_with_reason(self, reason):
        """Rechazo con motivo, común al asistente del backend y al botón
        Rechazar del portal. Si el solicitante es el propio Jefe de Equipo,
        vuelve a su paso; si no, queda en "Volver a revisar"."""
        self.ensure_one()
        status = 'to_revise'
        if self.equip_boss == self.user_id:
            status = 'approved_by_boss_group'
        self.write({'status': status})
        reason = reason or ''
        self.sudo().message_post(
            body='Solicitud Rechazada: {}'.format(reason),
            subtype_id=self.env.ref('mail.mt_note').id,
        )
        self._send_purchase_request_mail(
            'rejected', self.user_id, self.user_id.name, self.project.name, notes=reason,
        )

    def action_reject(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rechazar solicitud de gasto',
            'res_model': 'purchase.request.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_id': self.id,
            }
        }

    def action_view_invoice(self):
        self.ensure_one()
        invoice_ids = self.invoice_created.ids
        action = {
            "res_model": "account.move",
            "type": "ir.actions.act_window",
        }
        if len(invoice_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": invoice_ids[0],
                }
            )
        else:
            action.update(
                {
                    "name": "Factura",
                    "domain": [("id", "in", invoice_ids)],
                    "view_mode": "tree,form",
                }
            )
        return action

    def action_to_revise(self):
        for record in self:
            record.is_revised = False

    def _send_purchase_request_mail(self,type, users_to_send, user_name, company_name, notes=""):
            backend_link = f"/web#id={self.id}&cids=1-24-28-29-32-25-30-31&menu_id=899&active_id=1&model=portal.hr.expensive.request&view_type=form"
            if type == 'to_revise':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    # El Jefe de Equipo es usuario de portal: enlace al portal.
                    expensive_request_link = self._notify_link_for(admin_user, backend_link)
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>Se ha solicitado una nueva revisión de la solicitud de gasto, por parte de {user_name}.</p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{expensive_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Nueva Revisión de Gasto',
                        'email_from': self.env.user.email or '',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()
            elif type == 'approved_by_boss_group':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    expensive_request_link = self._notify_link_for(admin_user, backend_link)
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>La solicitud de gasto en el proyecto {company_name} ha sido aprobada por el jefe de equipo ({user_name}).</p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{expensive_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Solicitud de gasto',
                        'email_from': self.env.user.email or 'no-reply@example.com',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()
            elif type == 'rejected':
                portal_link = f"{self.get_base_url()}/my/expenses/{self.id}"
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>La solicitud de gasto en el proyecto {company_name} ha sido rechazada por el siguiente motivo:</p>
                                <p><em>{notes}</em></p>
                                <p>Puede revisar la solicitud y aportar una nueva versión desde su portal:</p>
                                <p><strong>Enlace:</strong> <a href="{portal_link}">Ver solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Solicitud de gasto',
                        'email_from': self.env.user.email or 'no-reply@example.com',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()
            elif type == 'approved_purchase_responsible':
                for admin_user in users_to_send:
                    admin_name = admin_user.name
                    expensive_request_link = self._notify_link_for(admin_user, backend_link)
                    body_html = f"""
                                <p>Estimado/a {admin_name},</p>
                                <p>La solicitud de gasto en el proyecto {company_name} ha sido aprobada por el responsable de compras ({user_name}).</p>
                                <p>Puede acceder a ella a traves del siguiente enlace:</p>
                                <p><strong>Enlace:</strong> <a href="{expensive_request_link}">Solicitud</a></p>
                                <p>Saludos cordiales, Odoo</p>
                            """
                    email = admin_user.email
                    mail_values = {
                        'subject': f'Solicitud de gasto',
                        'email_from': self.env.user.email or 'no-reply@example.com',
                        'email_to': email,
                        'body_html': body_html,
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send()



