import base64
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


REQUIRED_COLUMNS = [
    "FECHA PAGO",
    "LIQUIDO",
    "CONT",
    "NIF",
    "Nombre",
    "IRPF",
    "SS_TRABAJ",
    "SS_EMPRES",
    "DIETA",
    "KM",
    "GRATIFICAC",
    "DEDUCCION",
    "COST GEST",
    "COST CT",
    "COST DESP",
    "ANTICIPOS",
]

SPANISH_MONTHS = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


class AiciaPayrollImport(models.Model):
    _name = "aicia.payroll.import"
    _description = "Importación de nóminas AICIA"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "payment_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: _("Nueva importación de nóminas"), tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    config_id = fields.Many2one(
        "aicia.payroll.config",
        required=True,
        ondelete="restrict",
        domain="[('company_id', 'parent_of', company_id)]",
        tracking=True,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario",
        readonly=True,
        store=True,
        copy=False,
        check_company=True,
        domain="[('type', '=', 'general'), ('company_id', 'parent_of', company_id)]",
    )
    csv_file = fields.Binary(required=True, attachment=True)
    filename = fields.Char()
    file_checksum = fields.Char(compute="_compute_file_checksum", store=True)
    csv_encoding = fields.Char(default="cp1252")
    date = fields.Date(string="Fecha del asiento")
    payment_date = fields.Date(readonly=True, tracking=True)
    period_label = fields.Char(tracking=True)
    source_company_name = fields.Char(readonly=True)
    source_vat = fields.Char(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("parsed", "Parseado"),
            ("move_created", "Asiento creado"),
            ("cancelled", "Cancelado"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many("aicia.payroll.import.line", "import_id")
    move_id = fields.Many2one("account.move", readonly=True, copy=False)
    employee_count = fields.Integer(compute="_compute_totals", store=True)
    total_liquid = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_irpf = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_ss_employee = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_ss_company = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_diet = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_km = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_bonus = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_deduction = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_management_cost = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_ct_cost = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_travel_cost = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_advances = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    total_salary_gross = fields.Monetary(compute="_compute_totals", currency_field="currency_id", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    notes = fields.Text()
    move_ids = fields.Many2many("account.move", string="Asientos", readonly=True, copy=False)
    move_count = fields.Integer(compute="_compute_move_count")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        config = self._get_or_create_default_config(self.env.company)
        if config:
            values.setdefault("config_id", config.id)
            values.setdefault("journal_id", config.journal_id.id)
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company = self.env["res.company"].browse(vals.get("company_id") or self.env.company.id)
            config = self.env["aicia.payroll.config"].browse(vals.get("config_id"))
            if not config:
                config = self._get_or_create_default_config(company)
                if config:
                    vals["config_id"] = config.id
            if config and not vals.get("journal_id"):
                vals["journal_id"] = config.journal_id.id
        records = super().create(vals_list)
        records._check_duplicate_checksum()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._check_duplicate_checksum()
        return result

    @api.depends("csv_file")
    def _compute_file_checksum(self):
        for record in self:
            record.file_checksum = False
            if record.csv_file:
                record.file_checksum = hashlib.sha256(base64.b64decode(record.csv_file)).hexdigest()

    @api.depends(
        "line_ids",
        "line_ids.liquid",
        "line_ids.irpf",
        "line_ids.ss_employee",
        "line_ids.ss_company",
        "line_ids.diet",
        "line_ids.km",
        "line_ids.bonus",
        "line_ids.deduction",
        "line_ids.management_cost",
        "line_ids.ct_cost",
        "line_ids.travel_cost",
        "line_ids.advances",
        "line_ids.gross_salary",
    )
    def _compute_totals(self):
        for record in self:
            totals = {
                "liquid": Decimal("0.00"),
                "irpf": Decimal("0.00"),
                "ss_employee": Decimal("0.00"),
                "ss_company": Decimal("0.00"),
                "diet": Decimal("0.00"),
                "km": Decimal("0.00"),
                "bonus": Decimal("0.00"),
                "deduction": Decimal("0.00"),
                "management_cost": Decimal("0.00"),
                "ct_cost": Decimal("0.00"),
                "travel_cost": Decimal("0.00"),
                "advances": Decimal("0.00"),
                "salary_gross": Decimal("0.00"),
            }
            for line in record.line_ids:
                totals["liquid"] += record._to_decimal(line.liquid)
                totals["irpf"] += record._to_decimal(line.irpf)
                totals["ss_employee"] += record._to_decimal(line.ss_employee)
                totals["ss_company"] += record._to_decimal(line.ss_company)
                totals["diet"] += record._to_decimal(line.diet)
                totals["km"] += record._to_decimal(line.km)
                totals["bonus"] += record._to_decimal(line.bonus)
                totals["deduction"] += record._to_decimal(line.deduction)
                totals["management_cost"] += record._to_decimal(line.management_cost)
                totals["ct_cost"] += record._to_decimal(line.ct_cost)
                totals["travel_cost"] += record._to_decimal(line.travel_cost)
                totals["advances"] += record._to_decimal(line.advances)
                totals["salary_gross"] += record._to_decimal(line.gross_salary)
            record.employee_count = len(record.line_ids)
            record.total_liquid = float(record._round_money(totals["liquid"]))
            record.total_irpf = float(record._round_money(totals["irpf"]))
            record.total_ss_employee = float(record._round_money(totals["ss_employee"]))
            record.total_ss_company = float(record._round_money(totals["ss_company"]))
            record.total_diet = float(record._round_money(totals["diet"]))
            record.total_km = float(record._round_money(totals["km"]))
            record.total_bonus = float(record._round_money(totals["bonus"]))
            record.total_deduction = float(record._round_money(totals["deduction"]))
            record.total_management_cost = float(record._round_money(totals["management_cost"]))
            record.total_ct_cost = float(record._round_money(totals["ct_cost"]))
            record.total_travel_cost = float(record._round_money(totals["travel_cost"]))
            record.total_advances = float(record._round_money(totals["advances"]))
            record.total_salary_gross = float(record._round_money(totals["salary_gross"]))

    @api.depends("move_id", "move_ids")
    def _compute_move_count(self):
        for record in self:
            record.move_count = len(record.move_ids) or (1 if record.move_id else 0)

    @api.constrains("file_checksum", "company_id")
    def _check_duplicate_checksum(self):
        for record in self:
            if not record.file_checksum or not record.company_id:
                continue
            duplicate = self.search(
                [
                    ("file_checksum", "=", record.file_checksum),
                    ("company_id", "=", record.company_id.id),
                    ("id", "!=", record.id),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _(
                        "Ya existe otra importación para esta compañía con el mismo fichero (SHA256 duplicado)."
                    )
                )

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if not self.company_id:
            return
        config = self._get_or_create_default_config(self.company_id)
        self.config_id = config
        self.journal_id = config.journal_id if config else False

    @api.onchange("config_id")
    def _onchange_config_id(self):
        self.journal_id = self.config_id.journal_id

    @api.model
    def _get_or_create_default_config(self, company):
        config = self.env["aicia.payroll.config"].search([("company_id", "=", company.id)], limit=1)
        if config:
            return config
        journal = self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "parent_of", company.id)],
            limit=1,
        )
        if not journal:
            return self.env["aicia.payroll.config"]
        return self.env["aicia.payroll.config"].create(
            {
                "name": _("Configuración nóminas AICIA - %s") % company.display_name,
                "company_id": company.id,
                "journal_id": journal.id,
            }
        )

    def _decode_csv_file(self):
        self.ensure_one()
        if not self.csv_file:
            raise UserError(_("Debe subir un fichero CSV antes de parsear."))
        binary_data = base64.b64decode(self.csv_file)
        tried = []
        for encoding in [self.csv_encoding or "cp1252", "cp1252", "latin1"]:
            if encoding in tried:
                continue
            tried.append(encoding)
            try:
                return binary_data.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise UserError(_("No se pudo decodificar el CSV. Pruebe con cp1252 o latin1."))

    @api.model
    def _find_header_row(self, rows):
        for index, row in enumerate(rows):
            if row and row[0].strip().lstrip("\ufeff") == "FECHA PAGO":
                return index
        raise ValidationError(_("No se ha encontrado la cabecera real del CSV con FECHA PAGO."))

    @api.model
    def _parse_spanish_decimal(self, value):
        if value in (False, None, ""):
            return Decimal("0.00")
        text = str(value).strip().replace("\xa0", "")
        if not text:
            return Decimal("0.00")
        normalized = text.replace(".", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation as error:
            raise ValidationError(_("Importe no válido en el CSV: %s") % value) from error

    @api.model
    def _parse_spanish_date(self, value):
        if not value:
            return False
        try:
            return fields.Date.to_date(datetime.strptime(value.strip(), "%d/%m/%Y").date())
        except ValueError as error:
            raise ValidationError(_("Fecha no válida en el CSV: %s") % value) from error

    @api.model
    def _round_money(self, amount):
        return self._to_decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @api.model
    def _to_decimal(self, value):
        return Decimal(str(value or 0.0))

    @api.model
    def _normalize_vat(self, value):
        normalized_value = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
        if normalized_value.startswith("ES") and len(normalized_value) > 2:
            normalized_value = normalized_value[2:]
        return normalized_value

    @api.model
    def _extract_source_metadata(self, raw_lines):
        company_name = False
        source_vat = False
        vat_regex = re.compile(r"\b[A-Z0-9][A-Z0-9]{8}\b", re.IGNORECASE)
        for raw_line in raw_lines:
            clean_line = raw_line.strip().strip(";")
            if not clean_line:
                continue
            if ":" in clean_line:
                label, value = clean_line.split(":", 1)
                label = label.upper().strip()
                value = value.strip()
                if not company_name and any(token in label for token in ("EMPRESA", "RAZON", "SOCIEDAD")):
                    company_name = value
                if not source_vat and any(token in label for token in ("CIF", "NIF", "VAT")):
                    source_vat = value.split()[0]
                continue
            if not company_name and re.search(r"[A-Za-z]", clean_line):
                company_name = clean_line
            if not source_vat:
                match = vat_regex.search(clean_line.upper())
                if match:
                    source_vat = match.group(0)
        return company_name, source_vat

    @api.model
    def _compute_period_label_from_date(self, payment_date):
        if not payment_date:
            return False
        date_value = fields.Date.to_date(payment_date)
        return "%s %s" % (SPANISH_MONTHS[date_value.month], date_value.year)

    def action_parse_csv(self):
        for record in self:
            if record.move_ids or record.move_id:
                raise UserError(_("No puede volver a parsear una importación que ya tiene asiento creado."))
            decoded_text, detected_encoding = record._decode_csv_file()
            rows = list(csv.reader(io.StringIO(decoded_text), delimiter=";"))
            header_index = record._find_header_row(rows)
            header = [cell.strip().lstrip("\ufeff") for cell in rows[header_index]]
            missing_columns = [column for column in REQUIRED_COLUMNS if column not in header]
            if missing_columns:
                raise ValidationError(_("Faltan columnas obligatorias en el CSV: %s") % ", ".join(missing_columns))

            commands = [Command.clear()]
            warnings = []
            payment_dates = []
            source_company_name, source_vat = record._extract_source_metadata(decoded_text.splitlines()[:header_index])
            for sequence, row in enumerate(rows[header_index + 1 :], start=1):
                if not any((cell or "").strip() for cell in row):
                    continue
                values = {
                    column: (row[index].strip() if index < len(row) else "")
                    for index, column in enumerate(header)
                }
                payment_value = values.get("FECHA PAGO")
                if not payment_value:
                    continue
                payment_date = record._parse_spanish_date(payment_value)
                payment_dates.append(payment_date)
                commands.append(
                    Command.create(
                        {
                            "sequence": sequence,
                            "payment_date": payment_date,
                            "liquid": float(record._parse_spanish_decimal(values.get("LIQUIDO"))),
                            "cont": int(record._parse_spanish_decimal(values.get("CONT") or 0)),
                            "nif": values.get("NIF"),
                            "employee_name": values.get("Nombre") or _("Empleado sin nombre"),
                            "irpf": float(record._parse_spanish_decimal(values.get("IRPF"))),
                            "ss_employee": float(record._parse_spanish_decimal(values.get("SS_TRABAJ"))),
                            "ss_company": float(record._parse_spanish_decimal(values.get("SS_EMPRES"))),
                            "diet": float(record._parse_spanish_decimal(values.get("DIETA"))),
                            "km": float(record._parse_spanish_decimal(values.get("KM"))),
                            "bonus": float(record._parse_spanish_decimal(values.get("GRATIFICAC"))),
                            "deduction": float(record._parse_spanish_decimal(values.get("DEDUCCION"))),
                            "management_cost": float(record._parse_spanish_decimal(values.get("COST GEST"))),
                            "ct_cost": float(record._parse_spanish_decimal(values.get("COST CT"))),
                            "travel_cost": float(record._parse_spanish_decimal(values.get("COST DESP"))),
                            "advances": float(record._parse_spanish_decimal(values.get("ANTICIPOS"))),
                            "raw_data": json.dumps(values, ensure_ascii=False),
                        }
                    )
                )
            if len(commands) == 1:
                raise UserError(_("El CSV no contiene líneas de nómina válidas para importar."))

            selected_payment_date = False
            if payment_dates:
                unique_dates = sorted(set(payment_dates))
                selected_payment_date = unique_dates[-1]
                if len(unique_dates) > 1:
                    warnings.append(
                        _(
                            "Se han detectado varias fechas de pago en el CSV. Se usará la mayor para el asiento."
                        )
                    )

            if source_vat and record.company_id.vat:
                if record._normalize_vat(source_vat) != record._normalize_vat(record.company_id.vat):
                    warnings.append(
                        _("El CIF del CSV (%s) no coincide con el CIF de la compañía (%s).")
                        % (source_vat, record.company_id.vat)
                    )

            period_label = record.period_label or record._compute_period_label_from_date(selected_payment_date)
            note_lines = []
            if detected_encoding:
                note_lines.append(_("Codificación detectada: %s") % detected_encoding)
            note_lines.extend(warnings)

            record.write(
                {
                    "csv_encoding": detected_encoding,
                    "line_ids": commands,
                    "payment_date": selected_payment_date,
                    "period_label": period_label,
                    "source_company_name": source_company_name,
                    "source_vat": source_vat,
                    "notes": "\n".join(note_lines) if note_lines else False,
                    "state": "parsed",
                    "name": _("Nóminas AICIA - %s") % (period_label or record.filename or record.id),
                }
            )
        return True

    def _check_required_accounts(self):
        self.ensure_one()
        config = self.config_id
        if not config:
            raise ValidationError(_("Debe existir una configuración para crear el asiento."))
        if not (self.journal_id or config.journal_id):
            raise ValidationError(_("La configuración debe tener un diario general."))

        missing = []
        required_fields = [
            ("salary_expense_account_id", _("cuenta de gasto de sueldos y salarios")),
            (
                "company_social_security_expense_account_id",
                _("cuenta de gasto de Seguridad Social empresa"),
            ),
            ("employee_payable_account_id", _("cuenta acreedora de líquido nóminas")),
            ("irpf_payable_account_id", _("cuenta acreedora de IRPF")),
            (
                "social_security_payable_account_id",
                _("cuenta acreedora de Seguridad Social"),
            ),
        ]
        if self.total_diet > 0:
            required_fields.append(("diet_expense_account_id", _("cuenta de dietas")))
        if self.total_km > 0:
            required_fields.append(("km_expense_account_id", _("cuenta de kilometraje")))
        if self.total_bonus > 0:
            required_fields.append(("bonus_expense_account_id", _("cuenta de gratificaciones")))
        if self.total_advances > 0:
            required_fields.append(("advance_account_id", _("cuenta de anticipos")))
        if self.total_deduction > 0:
            required_fields.append(("deduction_payable_account_id", _("cuenta de otras deducciones")))
        if config.include_management_costs and self.total_management_cost > 0:
            required_fields.extend(
                [
                    ("management_cost_expense_account_id", _("cuenta de gasto de gestoría")),
                    ("management_cost_payable_account_id", _("cuenta acreedora de gestoría")),
                ]
            )
        if config.include_ct_costs and self.total_ct_cost > 0:
            required_fields.extend(
                [
                    ("ct_cost_expense_account_id", _("cuenta de gasto de coste CT")),
                    ("ct_cost_payable_account_id", _("cuenta acreedora de coste CT")),
                ]
            )
        if config.include_travel_costs and self.total_travel_cost > 0:
            required_fields.extend(
                [
                    ("travel_cost_expense_account_id", _("cuenta de gasto de desplazamiento")),
                    ("travel_cost_payable_account_id", _("cuenta acreedora de desplazamiento")),
                ]
            )

        for field_name, label in required_fields:
            if not config[field_name]:
                missing.append(label)
        if missing:
            raise ValidationError(_("Faltan cuentas por configurar: %s") % ", ".join(missing))

    @api.model
    def _normalize_partner_name(self, name):
        return re.sub(r"\s+", " ", (name or "").strip())

    @api.model
    def _normalize_partner_vat(self, vat):
        return re.sub(r"[^0-9A-Z]", "", (vat or "").upper())

    @api.model
    def _extract_partner_data_from_label(self, label):
        parts = [part.strip() for part in (label or "").rsplit(" - ", 2)]
        if len(parts) != 3:
            return False, False
        employee_name, nif, _concept = parts
        return employee_name or False, nif or False

    def _find_partner_from_employee(self, employee_name=None, nif=None, line_name=None):
        self.ensure_one()
        normalized_name = self._normalize_partner_name(employee_name)
        normalized_nif = self._normalize_partner_vat(nif)
        if line_name and (not normalized_name or not normalized_nif):
            parsed_name, parsed_nif = self._extract_partner_data_from_label(line_name)
            if not normalized_name:
                normalized_name = self._normalize_partner_name(parsed_name)
            if not normalized_nif:
                normalized_nif = self._normalize_partner_vat(parsed_nif)

        partner_model = self.env["res.partner"].with_context(active_test=False)
        if normalized_nif:
            nif_candidates = partner_model.search([("vat", "ilike", normalized_nif)])
            nif_matches = nif_candidates.filtered(
                lambda partner: self._normalize_partner_vat(partner.vat) == normalized_nif
            )
            if normalized_name:
                exact_name_matches = nif_matches.filtered(
                    lambda partner: self._normalize_partner_name(partner.name) == normalized_name
                )
                if exact_name_matches:
                    return exact_name_matches[:1]
            if nif_matches:
                return nif_matches[:1]

        if normalized_name:
            name_candidates = partner_model.search([("name", "=ilike", normalized_name)], limit=10)
            exact_name_matches = name_candidates.filtered(
                lambda partner: self._normalize_partner_name(partner.name) == normalized_name
            )
            if exact_name_matches:
                return exact_name_matches[:1]
        return partner_model.browse()

    def _find_employee_from_payroll_line(self, payroll_line, partner=None):
        self.ensure_one()
        employee_model = self.env["hr.employee"].with_context(active_test=False)
        normalized_nif = self._normalize_partner_vat(payroll_line.nif)
        normalized_name = self._normalize_partner_name(payroll_line.employee_name)

        if normalized_nif:
            nif_employees = employee_model.search([("identification_id", "ilike", normalized_nif)])
            nif_matches = nif_employees.filtered(
                lambda employee: self._normalize_partner_vat(employee.identification_id) == normalized_nif
            )
            if normalized_name:
                exact_name_matches = nif_matches.filtered(
                    lambda employee: self._normalize_partner_name(employee.name) == normalized_name
                )
                if exact_name_matches:
                    return exact_name_matches[:1]
            if nif_matches:
                return nif_matches[:1]

        if partner:
            partner_matches = employee_model.search(
                [
                    "|",
                    ("work_contact_id", "=", partner.id),
                    ("partner_id", "=", partner.id),
                ],
                limit=1,
            )
            if partner_matches:
                return partner_matches

        if normalized_name:
            name_employees = employee_model.search([("name", "=ilike", normalized_name)], limit=10)
            exact_name_matches = name_employees.filtered(
                lambda employee: self._normalize_partner_name(employee.name) == normalized_name
            )
            if exact_name_matches:
                return exact_name_matches[:1]
        return employee_model.browse()

    def _get_employee_analytic_distribution(self, employee):
        self.ensure_one()
        distribution = {}
        for analytic_line in employee.analytic_line_ids.sorted(key=lambda line: (line.sequence, line.id)):
            if not analytic_line.analytic_account_id or not analytic_line.percentage:
                continue
            account_id = analytic_line.analytic_account_id.id
            distribution[account_id] = distribution.get(account_id, 0.0) + analytic_line.percentage
        return distribution or False

    def _prepare_line_vals(
        self,
        name,
        account,
        debit=Decimal("0.00"),
        credit=Decimal("0.00"),
        partner=None,
        analytic_distribution=False,
    ):
        vals = {
            "name": name,
            "account_id": account.id,
            "debit": float(self._round_money(debit)),
            "credit": float(self._round_money(credit)),
        }
        if partner:
            vals["partner_id"] = partner.id
        if analytic_distribution:
            vals["analytic_distribution"] = analytic_distribution
        return vals

    def _get_move_reference(self):
        self.ensure_one()
        if self.period_label:
            return _("Nóminas AICIA - %s") % self.period_label
        payment_date = fields.Date.to_date(self.payment_date)
        return _("Nóminas AICIA - %s") % payment_date.strftime("%m/%Y")

    def _prepare_optional_cost_lines(self):
        self.ensure_one()
        config = self.config_id
        lines = []
        if config.include_management_costs and self.total_management_cost > 0:
            total = self._to_decimal(self.total_management_cost)
            lines.append(
                self._prepare_line_vals(
                    _("Coste gestoría - %s") % (self.period_label or self.payment_date),
                    config.management_cost_expense_account_id,
                    debit=total,
                )
            )
            lines.append(
                self._prepare_line_vals(
                    _("Acreedor gestoría - %s") % (self.period_label or self.payment_date),
                    config.management_cost_payable_account_id,
                    credit=total,
                )
            )
        if config.include_ct_costs and self.total_ct_cost > 0:
            total = self._to_decimal(self.total_ct_cost)
            lines.append(
                self._prepare_line_vals(
                    _("Coste CT - %s") % (self.period_label or self.payment_date),
                    config.ct_cost_expense_account_id,
                    debit=total,
                )
            )
            lines.append(
                self._prepare_line_vals(
                    _("Acreedor CT - %s") % (self.period_label or self.payment_date),
                    config.ct_cost_payable_account_id,
                    credit=total,
                )
            )
        if config.include_travel_costs and self.total_travel_cost > 0:
            total = self._to_decimal(self.total_travel_cost)
            lines.append(
                self._prepare_line_vals(
                    _("Coste desplazamiento - %s") % (self.period_label or self.payment_date),
                    config.travel_cost_expense_account_id,
                    debit=total,
                )
            )
            lines.append(
                self._prepare_line_vals(
                    _("Acreedor desplazamiento - %s") % (self.period_label or self.payment_date),
                    config.travel_cost_payable_account_id,
                    credit=total,
                )
            )
        return lines

    def _prepare_employee_optional_cost_lines(self, payroll_line, partner, label_prefix):
        self.ensure_one()
        config = self.config_id
        lines = []
        employee = self._find_employee_from_payroll_line(payroll_line, partner=partner)
        analytic_distribution = self._get_employee_analytic_distribution(employee)
        if config.include_management_costs and self._to_decimal(payroll_line.management_cost) > 0:
            total = self._to_decimal(payroll_line.management_cost)
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Coste gestoría"),
                    config.management_cost_expense_account_id,
                    debit=total,
                    partner=partner,
                    analytic_distribution=analytic_distribution,
                )
            )
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Acreedor gestoría"),
                    config.management_cost_payable_account_id,
                    credit=total,
                    partner=partner,
                )
            )
        if config.include_ct_costs and self._to_decimal(payroll_line.ct_cost) > 0:
            total = self._to_decimal(payroll_line.ct_cost)
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Coste CT"),
                    config.ct_cost_expense_account_id,
                    debit=total,
                    partner=partner,
                    analytic_distribution=analytic_distribution,
                )
            )
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Acreedor CT"),
                    config.ct_cost_payable_account_id,
                    credit=total,
                    partner=partner,
                )
            )
        if config.include_travel_costs and self._to_decimal(payroll_line.travel_cost) > 0:
            total = self._to_decimal(payroll_line.travel_cost)
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Coste desplazamiento"),
                    config.travel_cost_expense_account_id,
                    debit=total,
                    partner=partner,
                    analytic_distribution=analytic_distribution,
                )
            )
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Acreedor desplazamiento"),
                    config.travel_cost_payable_account_id,
                    credit=total,
                    partner=partner,
                )
            )
        return lines

    def _prepare_aggregated_move_lines(self):
        self.ensure_one()
        config = self.config_id
        period = self.period_label or self.payment_date
        salary_amount = (
            self._to_decimal(self.total_salary_gross)
            - self._to_decimal(self.total_diet)
            - self._to_decimal(self.total_km)
            - self._to_decimal(self.total_bonus)
        )
        lines = [
            self._prepare_line_vals(
                _("Sueldos y salarios - %s") % period,
                config.salary_expense_account_id,
                debit=salary_amount,
            )
        ]
        if self.total_diet > 0:
            lines.append(
                self._prepare_line_vals(
                    _("Dietas - %s") % period,
                    config.diet_expense_account_id,
                    debit=self._to_decimal(self.total_diet),
                )
            )
        if self.total_km > 0:
            lines.append(
                self._prepare_line_vals(
                    _("Kilometraje - %s") % period,
                    config.km_expense_account_id,
                    debit=self._to_decimal(self.total_km),
                )
            )
        if self.total_bonus > 0:
            lines.append(
                self._prepare_line_vals(
                    _("Gratificaciones - %s") % period,
                    config.bonus_expense_account_id,
                    debit=self._to_decimal(self.total_bonus),
                )
            )
        lines.append(
            self._prepare_line_vals(
                _("Seguridad Social empresa - %s") % period,
                config.company_social_security_expense_account_id,
                debit=self._to_decimal(self.total_ss_company),
            )
        )
        lines.extend(self._prepare_optional_cost_lines())
        lines.append(
            self._prepare_line_vals(
                _("Líquido nóminas - %s") % period,
                config.employee_payable_account_id,
                credit=self._to_decimal(self.total_liquid),
            )
        )
        lines.append(
            self._prepare_line_vals(
                _("IRPF - %s") % period,
                config.irpf_payable_account_id,
                credit=self._to_decimal(self.total_irpf),
            )
        )
        lines.append(
            self._prepare_line_vals(
                _("Seguridad Social acreedora - %s") % period,
                config.social_security_payable_account_id,
                credit=self._to_decimal(self.total_ss_employee) + self._to_decimal(self.total_ss_company),
            )
        )
        if self.total_advances > 0:
            lines.append(
                self._prepare_line_vals(
                    _("Anticipos - %s") % period,
                    config.advance_account_id,
                    credit=self._to_decimal(self.total_advances),
                )
            )
        if self.total_deduction > 0:
            lines.append(
                self._prepare_line_vals(
                    _("Otras deducciones - %s") % period,
                    config.deduction_payable_account_id,
                    credit=self._to_decimal(self.total_deduction),
                )
            )
        return lines

    def _prepare_employee_move_lines(self, line):
        self.ensure_one()
        config = self.config_id
        lines = []
        label_prefix = "%s - %s - " % (
            line.employee_name or _("Empleado"),
            line.nif or _("Sin NIF"),
        )
        partner = self._find_partner_from_employee(
            employee_name=line.employee_name,
            nif=line.nif,
            line_name=label_prefix + _("Salario bruto"),
        )
        employee = self._find_employee_from_payroll_line(line, partner=partner)
        analytic_distribution = self._get_employee_analytic_distribution(employee)
        gross_amount = (
            self._to_decimal(line.gross_salary)
            - self._to_decimal(line.diet)
            - self._to_decimal(line.km)
            - self._to_decimal(line.bonus)
        )
        if gross_amount > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Salario bruto"),
                    config.salary_expense_account_id,
                    debit=gross_amount,
                    partner=partner,
                    analytic_distribution=analytic_distribution,
                )
            )
        if self._to_decimal(line.diet) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Dietas"),
                    config.diet_expense_account_id,
                    debit=self._to_decimal(line.diet),
                    partner=partner,
                    analytic_distribution=analytic_distribution,
                )
            )
        if self._to_decimal(line.km) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Kilometraje"),
                    config.km_expense_account_id,
                    debit=self._to_decimal(line.km),
                    partner=partner,
                    analytic_distribution=analytic_distribution,
                )
            )
        if self._to_decimal(line.bonus) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Gratificaciones"),
                    config.bonus_expense_account_id,
                    debit=self._to_decimal(line.bonus),
                    partner=partner,
                    analytic_distribution=analytic_distribution,
                )
            )
        if self._to_decimal(line.ss_company) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("SS empresa"),
                    config.company_social_security_expense_account_id,
                    debit=self._to_decimal(line.ss_company),
                    partner=partner,
                    analytic_distribution=analytic_distribution,
                )
            )
        lines.extend(self._prepare_employee_optional_cost_lines(line, partner, label_prefix))
        if self._to_decimal(line.liquid) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Líquido"),
                    config.employee_payable_account_id,
                    credit=self._to_decimal(line.liquid),
                    partner=partner,
                )
            )
        if self._to_decimal(line.irpf) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("IRPF"),
                    config.irpf_payable_account_id,
                    credit=self._to_decimal(line.irpf),
                    partner=partner,
                )
            )
        if self._to_decimal(line.ss_employee) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("SS trabajador"),
                    config.social_security_payable_account_id,
                    credit=self._to_decimal(line.ss_employee),
                    partner=partner,
                )
            )
        if self._to_decimal(line.ss_company) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("SS empresa"),
                    config.social_security_payable_account_id,
                    credit=self._to_decimal(line.ss_company),
                    partner=partner,
                )
            )
        if self._to_decimal(line.advances) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Anticipos"),
                    config.advance_account_id,
                    credit=self._to_decimal(line.advances),
                    partner=partner,
                )
            )
        if self._to_decimal(line.deduction) > 0:
            lines.append(
                self._prepare_line_vals(
                    label_prefix + _("Deducciones"),
                    config.deduction_payable_account_id,
                    credit=self._to_decimal(line.deduction),
                    partner=partner,
                )
            )
        return lines

    def _get_employee_move_reference(self, payroll_line):
        self.ensure_one()
        return _("%(reference)s - %(employee)s") % {
            "reference": self._get_move_reference(),
            "employee": payroll_line.employee_name or _("Empleado"),
        }

    def _balance_move_lines(self, line_vals):
        self.ensure_one()
        total_debit = sum(self._to_decimal(line["debit"]) for line in line_vals)
        total_credit = sum(self._to_decimal(line["credit"]) for line in line_vals)
        difference = self._round_money(total_debit - total_credit)
        if abs(difference) > Decimal("0.05"):
            raise ValidationError(
                _("El asiento no queda cuadrado. La diferencia supera 0,05 y es de %s.")
                % difference
            )
        if not difference:
            return line_vals

        salary_line = next(
            (
                line
                for line in line_vals
                if line["account_id"] == self.config_id.salary_expense_account_id.id
                and self._to_decimal(line["debit"]) > 0
            ),
            False,
        )
        if not salary_line:
            raise ValidationError(
                _("No se ha encontrado una línea de gasto salarial para ajustar el redondeo.")
            )
        updated_debit = self._to_decimal(salary_line["debit"]) - difference
        if updated_debit < 0:
            raise ValidationError(
                _("No se puede ajustar el redondeo porque el gasto salarial quedaría negativo.")
            )
        salary_line["debit"] = float(self._round_money(updated_debit))
        return line_vals

    def action_create_account_move(self):
        for record in self:
            if record.move_ids or record.move_id:
                raise UserError(_("Esta importación ya tiene un asiento contable creado."))
            if not record.line_ids:
                raise UserError(_("Debe parsear el CSV antes de crear el asiento."))
            if record.state not in ("parsed", "draft"):
                raise UserError(_("Solo se puede crear el asiento desde un CSV parseado."))
            record._check_required_accounts()
            move_date = record.date or record.payment_date
            if not move_date:
                raise UserError(_("No hay fecha para el asiento. Indique una fecha o parsee un CSV válido."))
            moves = self.env["account.move"]
            if record.config_id.group_by_employee:
                for payroll_line in record.line_ids.sorted(key=lambda item: (item.sequence, item.id)):
                    line_vals = record._prepare_employee_move_lines(payroll_line)
                    line_vals = record._balance_move_lines(line_vals)
                    moves |= self.env["account.move"].create(
                        {
                            "move_type": "entry",
                            "company_id": record.company_id.id,
                            "journal_id": (record.journal_id or record.config_id.journal_id).id,
                            "date": move_date,
                            "ref": record._get_employee_move_reference(payroll_line),
                            "line_ids": [Command.create(line) for line in line_vals],
                        }
                    )
            else:
                line_vals = record._prepare_aggregated_move_lines()
                line_vals = record._balance_move_lines(line_vals)
                moves = self.env["account.move"].create(
                    {
                        "move_type": "entry",
                        "company_id": record.company_id.id,
                        "journal_id": (record.journal_id or record.config_id.journal_id).id,
                        "date": move_date,
                        "ref": record._get_move_reference(),
                        "line_ids": [Command.create(line) for line in line_vals],
                    }
                )
            record.write(
                {
                    "move_id": moves[:1].id,
                    "move_ids": [Command.set(moves.ids)],
                    "journal_id": moves[:1].journal_id.id,
                    "state": "move_created",
                }
            )
        return True

    def action_open_move(self):
        self.ensure_one()
        moves = self.move_ids or self.move_id
        if not moves:
            raise UserError(_("No hay ningún asiento creado para esta importación."))
        if len(moves) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Asiento contable"),
                "res_model": "account.move",
                "res_id": moves.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Asientos contables"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", moves.ids)],
            "target": "current",
        }

    def action_cancel(self):
        self.write({"state": "cancelled"})
        return True

    def action_reset_to_draft(self):
        for record in self:
            if record.move_ids or record.move_id:
                raise UserError(_("No puede volver a borrador una importación que ya tiene asiento creado."))
        self.write({"state": "draft"})
        return True
