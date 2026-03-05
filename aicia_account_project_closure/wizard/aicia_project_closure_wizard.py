# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class AiciaProjectClosureWizard(models.TransientModel):
    """Wizard para el cierre contable AICIA por proyectos (cuentas analíticas).

    Calcula el resultado por proyecto en un rango de fechas y genera asientos
    de regularización:
    - Resultado positivo → cuenta 130 contra 294
    - Resultado negativo → cuenta 131 contra 294
    """

    _name = "aicia.project.closure.wizard"
    _description = "Wizard Cierre AICIA por Proyectos"

    # ------------------------------------------------------------------
    # Campos
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda",
        related="company_id.currency_id",
        readonly=True,
    )
    date_from = fields.Date(
        string="Fecha Desde",
        required=True,
        help="Inicio del periodo de cierre (inclusive).",
    )
    date_to = fields.Date(
        string="Fecha Hasta",
        required=True,
        help="Fin del periodo de cierre (inclusive).",
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Diario de Cierre",
        required=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        help="Diario donde se crearán los asientos de cierre.",
    )
    account_profit_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta Beneficio (130)",
        required=True,
        domain="[('company_ids', 'in', company_id)]",
        help="Cuenta contable para resultado positivo (ej: 130 - Subvenciones oficiales de capital).",
    )
    account_loss_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta Pérdida (131)",
        required=True,
        domain="[('company_ids', 'in', company_id)]",
        help="Cuenta contable para resultado negativo (ej: 131 - Donaciones y legados de capital).",
    )
    account_provision_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta Provisión (294)",
        required=True,
        domain="[('company_ids', 'in', company_id)]",
        help="Cuenta de contrapartida (ej: 294 - Provisiones material científico).",
    )
    include_accounts_prefixes = fields.Char(
        string="Prefijos de Cuentas",
        required=True,
        default="6,7",
        help="Prefijos de cuentas contables a incluir, separados por coma. "
        "Por defecto 6 (gastos) y 7 (ingresos).",
    )
    analytic_account_ids = fields.Many2many(
        comodel_name="account.analytic.account",
        string="Proyectos (Cuentas Analíticas)",
        help="Si se deja vacío, se procesan todas las cuentas analíticas con "
        "movimientos en el periodo.",
    )
    preview_line_ids = fields.One2many(
        comodel_name="aicia.project.closure.line",
        inverse_name="wizard_id",
        string="Previsualización por Proyecto",
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("preview", "Previsualización"),
            ("done", "Finalizado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        readonly=True,
    )
    created_move_ids = fields.Many2many(
        comodel_name="account.move",
        string="Asientos Creados",
        readonly=True,
    )
    created_move_count = fields.Integer(
        string="Nº Asientos",
        compute="_compute_created_move_count",
    )

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company

        # Diario por defecto: primer diario general de la compañía
        if "journal_id" in fields_list and not res.get("journal_id"):
            journal = self.env["account.journal"].search(
                [("type", "=", "general"), ("company_id", "=", company.id)],
                limit=1,
            )
            if journal:
                res["journal_id"] = journal.id

        # Cuentas por defecto buscando por código
        Account = self.env["account.account"].with_company(company)
        account_defaults = {
            "account_profit_id": "130",
            "account_loss_id": "131",
            "account_provision_id": "294",
        }
        for field_name, code_prefix in account_defaults.items():
            if field_name in fields_list and not res.get(field_name):
                account = Account.search(
                    [
                        ("code", "=like", f"{code_prefix}%"),
                        ("company_ids", "in", company.id),
                    ],
                    limit=1,
                )
                if account:
                    res[field_name] = account.id

        # Fechas: por defecto el ejercicio actual (1 de enero a 31 de diciembre)
        if "date_from" in fields_list and not res.get("date_from"):
            today = fields.Date.context_today(self)
            res["date_from"] = today.replace(month=1, day=1)
        if "date_to" in fields_list and not res.get("date_to"):
            today = fields.Date.context_today(self)
            res["date_to"] = today.replace(month=12, day=31)

        return res

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------
    @api.depends("created_move_ids")
    def _compute_created_move_count(self):
        for wizard in self:
            wizard.created_move_count = len(wizard.created_move_ids)

    # ------------------------------------------------------------------
    # Constrains
    # ------------------------------------------------------------------
    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(
                    _("La fecha de inicio no puede ser posterior a la fecha de fin.")
                )

    # ------------------------------------------------------------------
    # Acciones principales
    # ------------------------------------------------------------------
    def action_preview(self):
        """Calcula y muestra la previsualización de resultados por proyecto."""
        self.ensure_one()
        self._validate_configuration()

        # Limpiar previsualización anterior
        self.preview_line_ids.unlink()

        # Calcular resultados por proyecto
        results = self._compute_project_results()

        if not results:
            raise UserError(
                _(
                    "No se encontraron movimientos contables con distribución analítica "
                    "para los criterios seleccionados (prefijos: %(prefixes)s, periodo: "
                    "%(date_from)s - %(date_to)s).",
                    prefixes=self.include_accounts_prefixes,
                    date_from=self.date_from,
                    date_to=self.date_to,
                )
            )

        # Crear líneas de previsualización
        line_vals = []
        for analytic_id, data in sorted(results.items(), key=lambda x: x[1]["name"]):
            line_vals.append(
                {
                    "wizard_id": self.id,
                    "analytic_account_id": analytic_id,
                    "income": data["income"],
                    "expense": data["expense"],
                }
            )

        self.env["aicia.project.closure.line"].create(line_vals)
        self.state = "preview"

        return self._reopen_wizard()

    def action_generate(self):
        """Genera y postea los asientos de cierre por proyecto."""
        self.ensure_one()

        if not self.preview_line_ids:
            raise UserError(_("No hay datos de previsualización. Pulse 'Previsualizar' primero."))

        lines_to_process = self.preview_line_ids.filtered(
            lambda l: not l.has_existing_entries
            and not self.currency_id.is_zero(l.result)
        )

        if not lines_to_process:
            skipped_duplicates = self.preview_line_ids.filtered("has_existing_entries")
            skipped_zero = self.preview_line_ids.filtered(
                lambda l: self.currency_id.is_zero(l.result)
            )
            msg_parts = []
            if skipped_duplicates:
                msg_parts.append(
                    _("%(count)s proyecto(s) ya tienen asientos de cierre para este periodo.",
                      count=len(skipped_duplicates))
                )
            if skipped_zero:
                msg_parts.append(
                    _("%(count)s proyecto(s) tienen resultado cero.",
                      count=len(skipped_zero))
                )
            raise UserError(
                _("No hay asientos que generar. ") + " ".join(msg_parts)
            )

        created_moves = self.env["account.move"]

        for line in lines_to_process:
            move = self._create_closure_move(line)
            created_moves |= move

        # Postear los asientos
        try:
            created_moves.action_post()
        except (UserError, AccessError) as e:
            raise UserError(
                _(
                    "Error al postear los asientos de cierre. Verifique que tiene "
                    "permisos para publicar asientos contables.\n\nDetalle: %(error)s",
                    error=str(e),
                )
            ) from e

        self.created_move_ids = [Command.set(created_moves.ids)]
        self.state = "done"

        # Log informativo
        skipped_dup = self.preview_line_ids.filtered("has_existing_entries")
        skipped_zero = self.preview_line_ids.filtered(
            lambda l: self.currency_id.is_zero(l.result)
        )
        _logger.info(
            "Cierre AICIA completado: %d asientos creados, %d omitidos (duplicados), "
            "%d omitidos (resultado cero).",
            len(created_moves),
            len(skipped_dup),
            len(skipped_zero),
        )

        return self._reopen_wizard()

    def action_back(self):
        """Regresa al estado borrador limpiando la previsualización."""
        self.ensure_one()
        self.preview_line_ids.unlink()
        self.state = "draft"
        return self._reopen_wizard()

    def action_view_moves(self):
        """Abre los asientos de cierre creados."""
        self.ensure_one()
        if not self.created_move_ids:
            return

        action = {
            "name": _("Asientos de Cierre AICIA"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", self.created_move_ids.ids)],
            "context": {"default_move_type": "entry"},
        }

        if len(self.created_move_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": self.created_move_ids.id,
                }
            )

        return action

    # ------------------------------------------------------------------
    # Lógica de cálculo
    # ------------------------------------------------------------------
    def _validate_configuration(self):
        """Valida que la configuración del wizard sea correcta."""
        self.ensure_one()
        if not self.include_accounts_prefixes or not self.include_accounts_prefixes.strip():
            raise UserError(_("Debe indicar al menos un prefijo de cuenta contable."))
        if not self.journal_id:
            raise UserError(_("Debe seleccionar un diario de cierre."))
        if not self.account_profit_id:
            raise UserError(_("Debe seleccionar la cuenta de beneficio (130)."))
        if not self.account_loss_id:
            raise UserError(_("Debe seleccionar la cuenta de pérdida (131)."))
        if not self.account_provision_id:
            raise UserError(_("Debe seleccionar la cuenta de provisión (294)."))

    def _get_account_prefixes(self):
        """Devuelve la lista de prefijos limpia."""
        return [p.strip() for p in self.include_accounts_prefixes.split(",") if p.strip()]

    def _get_income_prefixes(self):
        """Devuelve los prefijos que se consideran ingresos (empiezan por 7)."""
        return [p for p in self._get_account_prefixes() if p.startswith("7")]

    def _get_expense_prefixes(self):
        """Devuelve los prefijos que se consideran gastos (empiezan por 6)."""
        return [p for p in self._get_account_prefixes() if p.startswith("6")]

    def _build_account_domain(self):
        """Construye el dominio para buscar cuentas contables por prefijos."""
        prefixes = self._get_account_prefixes()
        if not prefixes:
            raise UserError(_("No hay prefijos de cuentas válidos configurados."))

        # Construir dominio OR para los prefijos
        account_domain = ["|"] * (len(prefixes) - 1)
        for prefix in prefixes:
            account_domain.append(("code", "=like", f"{prefix}%"))
        account_domain.append(("company_ids", "in", self.company_id.id))
        return account_domain

    def _compute_project_results(self):
        """Calcula el resultado (income - expense) por cuenta analítica.

        Retorna un dict: {analytic_account_id: {name, income, expense}}

        Lógica:
        - Toma account.move.line posteadas en el rango de fechas
        - Filtra por cuentas con los prefijos configurados
        - Lee analytic_distribution (JSON: {"analytic_id": porcentaje, ...})
        - Reparte balance * porcentaje / 100 a cada analítica
        - Clasifica como income (cuentas 7xx) o expense (cuentas 6xx)

        Convención de signos:
        - balance = debit - credit
        - Ingresos (7xx): balance normalmente negativo (haber > debe)
          → income = -balance (positivo)
        - Gastos (6xx): balance normalmente positivo (debe > haber)
          → expense = balance (positivo)
        - result = income - expense
        """
        self.ensure_one()

        # Obtener IDs de cuentas contables que coinciden con los prefijos
        Account = self.env["account.account"].with_company(self.company_id)
        account_domain = self._build_account_domain()
        target_accounts = Account.search(account_domain)

        if not target_accounts:
            return {}

        # Clasificar cuentas como ingreso o gasto
        income_prefixes = self._get_income_prefixes()
        expense_prefixes = self._get_expense_prefixes()

        income_account_ids = set()
        expense_account_ids = set()
        for account in target_accounts:
            code = account.code or ""
            for prefix in income_prefixes:
                if code.startswith(prefix):
                    income_account_ids.add(account.id)
                    break
            for prefix in expense_prefixes:
                if code.startswith(prefix):
                    expense_account_ids.add(account.id)
                    break

        # Buscar apuntes contables posteados en el rango
        move_line_domain = [
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("account_id", "in", target_accounts.ids),
            ("analytic_distribution", "!=", False),
        ]

        move_lines = self.env["account.move.line"].search(move_line_domain)

        if not move_lines:
            return {}

        # Filtrar por analíticas seleccionadas (si se indicaron)
        filter_analytic_ids = (
            set(self.analytic_account_ids.ids) if self.analytic_account_ids else None
        )

        # Acumular resultados por analítica
        # Estructura: {analytic_id: {"name": str, "income": float, "expense": float}}
        results = defaultdict(lambda: {"name": "", "income": 0.0, "expense": 0.0})

        # Cache de nombres de analíticas
        analytic_names = {}

        for line in move_lines:
            distribution = line.analytic_distribution
            if not distribution or not isinstance(distribution, dict):
                continue

            balance = line.balance  # debit - credit
            account_id = line.account_id.id

            for key, percentage in distribution.items():
                # Las claves pueden ser IDs separados por comas (distribución combinada)
                # En el caso simple es un solo ID
                analytic_ids = [
                    int(aid) for aid in key.split(",") if aid.strip().isdigit()
                ]

                for analytic_id in analytic_ids:
                    # Filtrar si se seleccionaron analíticas específicas
                    if filter_analytic_ids and analytic_id not in filter_analytic_ids:
                        continue

                    # Importe proporcional según el porcentaje de distribución
                    amount = balance * percentage / 100.0

                    # Clasificar y acumular
                    if account_id in income_account_ids:
                        # Ingresos: balance normalmente negativo → income = -amount
                        results[analytic_id]["income"] += -amount
                    elif account_id in expense_account_ids:
                        # Gastos: balance normalmente positivo → expense = amount
                        results[analytic_id]["expense"] += amount

        # Rellenar nombres de analíticas
        if results:
            analytic_records = self.env["account.analytic.account"].browse(
                list(results.keys())
            )
            for rec in analytic_records.exists():
                analytic_names[rec.id] = rec.display_name

            # Limpiar analíticas que ya no existen
            for analytic_id in list(results.keys()):
                if analytic_id not in analytic_names:
                    del results[analytic_id]
                else:
                    results[analytic_id]["name"] = analytic_names[analytic_id]

        return dict(results)

    # ------------------------------------------------------------------
    # Generación de asientos
    # ------------------------------------------------------------------
    def _create_closure_move(self, line):
        """Crea un account.move de cierre para una línea de previsualización.

        Estructura del asiento:
        - Línea 1: Cuenta 130/131 (según resultado) - Resultado del proyecto
        - Línea 2: Cuenta 294 - Contrapartida provisión

        Ambas líneas llevan analytic_distribution = {analytic_id: 100}
        """
        self.ensure_one()
        analytic = line.analytic_account_id
        result = line.result
        abs_result = abs(result)

        if self.currency_id.is_zero(abs_result):
            return self.env["account.move"]

        # Determinar cuenta según resultado
        if result > 0:
            target_account = self.account_profit_id
        else:
            target_account = self.account_loss_id

        # Referencia para trazabilidad y detección de duplicados
        closure_ref = self.env["aicia.project.closure.line"]._build_closure_ref(
            analytic.id, self.date_from, self.date_to
        )
        year = self.date_to.year if self.date_to else self.date_from.year
        ref_text = _("AICIA Cierre proyecto %(project)s %(year)s", project=analytic.display_name, year=year)
        narration_text = _(
            "<p><strong>Cierre AICIA por proyecto</strong></p>"
            "<p>Proyecto: %(project)s</p>"
            "<p>Periodo: %(date_from)s - %(date_to)s</p>"
            "<p>Ingresos: %(income).2f | Gastos: %(expense).2f</p>"
            "<p>Resultado: %(result).2f</p>"
            "<p>Prefijos incluidos: %(prefixes)s</p>",
            project=analytic.display_name,
            date_from=self.date_from,
            date_to=self.date_to,
            income=line.income,
            expense=line.expense,
            result=line.result,
            prefixes=self.include_accounts_prefixes,
        )

        # Distribución analítica: 100% al proyecto
        analytic_dist = {str(analytic.id): 100}

        # Construir líneas del asiento
        # Resultado positivo (beneficio):
        #   Debe (debit) en 130 / Haber (credit) en 294
        # Resultado negativo (pérdida):
        #   Debe (debit) en 294 / Haber (credit) en 131
        if result > 0:
            move_lines = [
                Command.create({
                    "name": _("Resultado proyecto %(project)s - Beneficio",
                              project=analytic.display_name),
                    "account_id": target_account.id,
                    "debit": 0.0,
                    "credit": abs_result,
                    "analytic_distribution": analytic_dist,
                }),
                Command.create({
                    "name": _("Provisión proyecto %(project)s",
                              project=analytic.display_name),
                    "account_id": self.account_provision_id.id,
                    "debit": abs_result,
                    "credit": 0.0,
                    "analytic_distribution": analytic_dist,
                }),
            ]
        else:
            move_lines = [
                Command.create({
                    "name": _("Resultado proyecto %(project)s - Pérdida",
                              project=analytic.display_name),
                    "account_id": target_account.id,
                    "debit": abs_result,
                    "credit": 0.0,
                    "analytic_distribution": analytic_dist,
                }),
                Command.create({
                    "name": _("Provisión proyecto %(project)s",
                              project=analytic.display_name),
                    "account_id": self.account_provision_id.id,
                    "debit": 0.0,
                    "credit": abs_result,
                    "analytic_distribution": analytic_dist,
                }),
            ]

        move_vals = {
            "move_type": "entry",
            "journal_id": self.journal_id.id,
            "date": self.date_to,
            "ref": ref_text,
            "narration": narration_text,
            "company_id": self.company_id.id,
            "line_ids": move_lines,
            "aicia_closure": True,
            "aicia_closure_ref": closure_ref,
        }

        move = (
            self.env["account.move"]
            .with_company(self.company_id)
            .create(move_vals)
        )
        return move

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _reopen_wizard(self):
        """Reabre el wizard para mantener el modal activo."""
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

