from odoo import _, api, fields, models


class AiciaPayrollConfig(models.Model):
    _name = "aicia.payroll.config"
    _description = "Configuración de importación de nóminas AICIA"
    _check_company_auto = True
    _order = "company_id, name"

    _unique_company = models.Constraint(
        "unique(company_id)",
        "Solo puede existir una configuración de nóminas AICIA por compañía.",
    )

    name = fields.Char(required=True, default=lambda self: _("Nóminas AICIA"))
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario",
        required=True,
        check_company=True,
        ondelete="restrict",
        domain="[('company_id', 'parent_of', company_id), ('type', '=', 'general')]",
        default=lambda self: self._default_journal_id(),
    )
    salary_expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta gasto sueldos y salarios",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    company_social_security_expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta gasto Seguridad Social empresa",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    employee_payable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta acreedora líquido nóminas",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    irpf_payable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta acreedora IRPF",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    social_security_payable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta acreedora Seguridad Social",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    advance_account_id = fields.Many2one(
        "account.account",
        string="Cuenta anticipos",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    deduction_payable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta otras deducciones",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    diet_expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta gasto dietas",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    km_expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta gasto kilometraje",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    bonus_expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta gasto gratificaciones",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    management_cost_expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta gasto gestoría",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    management_cost_payable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta acreedora gestoría",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    ct_cost_expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta gasto coste CT",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    ct_cost_payable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta acreedora coste CT",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    travel_cost_expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta gasto desplazamiento",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    travel_cost_payable_account_id = fields.Many2one(
        "account.account",
        string="Cuenta acreedora desplazamiento",
        ondelete="restrict",
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    include_management_costs = fields.Boolean(default=False)
    include_ct_costs = fields.Boolean(default=False)
    include_travel_costs = fields.Boolean(default=False)
    group_by_employee = fields.Boolean(default=False)

    @api.model
    def _default_journal_id(self):
        return self._find_default_journal(self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            prepared_vals_list.append(self._apply_default_values(dict(vals)))
        return super().create(prepared_vals_list)

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if not self.company_id:
            return
        values = self._apply_default_values({"company_id": self.company_id.id})
        for field_name, value in values.items():
            if field_name != "company_id" and value and not self[field_name]:
                self[field_name] = value

    def _apply_default_values(self, vals):
        company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
        if not vals.get("journal_id"):
            journal = self._find_default_journal(company)
            if journal:
                vals["journal_id"] = journal.id
        for field_name, code in self._get_recommended_account_codes().items():
            if vals.get(field_name):
                continue
            account = self._find_account_by_code(company, code)
            if account:
                vals[field_name] = account.id
        return vals

    @api.model
    def _find_default_journal(self, company):
        return self.env["account.journal"].search(
            [
                ("type", "=", "general"),
                ("company_id", "parent_of", company.id),
            ],
            limit=1,
        )

    @api.model
    def _find_account_by_code(self, company, code):
        return self.env["account.account"].with_company(company).search(
            [
                ("company_ids", "parent_of", [company.id]),
                ("code", "=", code),
            ],
            limit=1,
        )

    @api.model
    def _get_recommended_account_codes(self):
        return {
            "salary_expense_account_id": "640000",
            "company_social_security_expense_account_id": "642000",
            "employee_payable_account_id": "465000",
            "irpf_payable_account_id": "475100",
            "social_security_payable_account_id": "476000",
            "advance_account_id": "460000",
        }
