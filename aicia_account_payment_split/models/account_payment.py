# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    """Extensión de account.payment para soportar reparto de cobros.

    Decisiones de diseño:
    ─────────────────────
    1. ESTRATEGIA DE REPARTO: se genera UN SOLO asiento de reparto por pago,
       calculado sobre el importe total del pago (payment.amount).  Si el pago
       reconcilia varias facturas, el reparto aplica al total reconciliado.
       Esto simplifica la contabilidad y la auditoría.

    2. TRIGGER: el reparto se ejecuta al postear el pago (action_post).
       En Odoo 19 Enterprise, la reconciliación ocurre dentro del flujo
       de posteo.  Si el pago se crea desde el wizard de registro de pagos,
       la reconciliación ya está hecha al terminar action_post.

    3. SUGERENCIA AUTOMÁTICA: al cambiar facturas o partner, se intenta
       detectar la analítica "principal" y buscar una plantilla con
       default_for_analytic_account_id coincidente.
       - Si todas las facturas comparten la misma analítica → se sugiere.
       - Si hay analíticas distintas entre facturas → NO se sugiere (queda vacío).
       - Esto se documenta para que el usuario entienda por qué no hay sugerencia.

    4. CANCELACIÓN: al cancelar un pago que tiene asiento de reparto,
       se genera un asiento inverso (reversal) automáticamente.
    """

    _inherit = "account.payment"

    # ------------------------------------------------------------------
    # Campos nuevos
    # ------------------------------------------------------------------
    split_template_id = fields.Many2one(
        comodel_name="account.payment.split.template",
        string="Plantilla de Reparto",
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        check_company=True,
        copy=False,
        tracking=True,
        help="Seleccione la plantilla de reparto a aplicar cuando se postee "
        "este pago.  Si no se selecciona, no se generará reparto.",
    )
    split_move_id = fields.Many2one(
        comodel_name="account.move",
        string="Asiento de Reparto",
        readonly=True,
        copy=False,
        help="Asiento contable de reparto generado automáticamente.",
    )
    split_move_count = fields.Integer(
        string="Repartos",
        compute="_compute_split_move_count",
    )

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------
    @api.depends("split_move_id")
    def _compute_split_move_count(self):
        for pay in self:
            pay.split_move_count = 1 if pay.split_move_id else 0

    # ------------------------------------------------------------------
    # Sugerencia automática de plantilla
    # ------------------------------------------------------------------
    @api.onchange("invoice_ids", "partner_id", "company_id")
    def _onchange_suggest_split_template(self):
        """Sugiere automáticamente una plantilla de reparto basándose en la
        analítica 'principal' de las facturas asociadas.

        Regla para detectar analítica principal:
        1. Si la factura tiene analytic_distribution a nivel de cabecera,
           se toma la analítica con mayor peso.
        2. Si no, se analizan las líneas de factura (invoice_line_ids):
           se agrega el peso de analytic_distribution por analytic_account_id
           y se selecciona la de mayor peso total.
        3. Si todas las facturas comparten la misma analítica principal,
           se usa para buscar plantilla.
        4. Si hay analíticas distintas entre facturas, NO se sugiere
           automáticamente (se deja vacío para que el usuario elija).
        5. Si no se puede determinar analítica, no se sugiere.
        """
        if self.split_template_id:
            # El usuario ya eligió una, no sobrescribir
            return

        invoices = self.invoice_ids.filtered(
            lambda m: m.move_type in ("out_invoice", "out_refund")
        )
        if not invoices:
            return

        # Detectar analítica principal por factura
        analytic_ids = set()
        for inv in invoices:
            main_analytic = self._get_main_analytic_from_invoice(inv)
            if main_analytic:
                analytic_ids.add(main_analytic)
            else:
                # No se pudo determinar → no sugerir
                return

        if len(analytic_ids) != 1:
            # Analíticas distintas entre facturas → no sugerir
            _logger.info(
                "Pago %s: facturas con analíticas distintas (%s), "
                "no se sugiere plantilla automáticamente.",
                self.display_name,
                analytic_ids,
            )
            return

        analytic_id = analytic_ids.pop()
        template = self.env["account.payment.split.template"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("active", "=", True),
                ("default_for_analytic_account_id", "=", analytic_id),
            ],
            order="priority desc, id",
            limit=1,
        )
        if template:
            self.split_template_id = template

    def _get_main_analytic_from_invoice(self, invoice):
        """Devuelve el ID de la cuenta analítica 'principal' de una factura.

        Estrategia:
        1. Si la factura tiene analytic_distribution en cabecera, se toma
           la clave con mayor porcentaje.
        2. Si no, se analizan las líneas:
           - Se agregan los pesos de analytic_distribution de cada línea.
           - Se selecciona la cuenta analítica con mayor peso total.

        Returns:
            int or False: ID de la cuenta analítica principal, o False.
        """
        # 1. Analítica a nivel de cabecera (si el campo existe y está informado)
        if hasattr(invoice, "analytic_distribution") and invoice.analytic_distribution:
            return self._get_dominant_analytic_from_distribution(
                invoice.analytic_distribution
            )

        # 2. Analítica en las líneas de factura
        weight_map = {}  # {analytic_account_id: total_weight}
        for line in invoice.invoice_line_ids.filtered(
            lambda l: l.display_type not in ("line_section", "line_note")
        ):
            dist = line.analytic_distribution
            if not dist:
                continue
            for key, pct in dist.items():
                try:
                    acc_id = int(key)
                except (ValueError, TypeError):
                    continue
                weight_map[acc_id] = weight_map.get(acc_id, 0.0) + (pct or 0.0)

        if not weight_map:
            return False

        # La de mayor peso total
        return max(weight_map, key=weight_map.get)

    @staticmethod
    def _get_dominant_analytic_from_distribution(distribution):
        """Dado un dict JSON {analytic_id: percentage, ...}, devuelve la
        clave (int) con mayor porcentaje."""
        if not distribution:
            return False
        best_key = max(distribution, key=lambda k: distribution[k])
        try:
            return int(best_key)
        except (ValueError, TypeError):
            return False

    # ------------------------------------------------------------------
    # Acción de posteo - TRIGGER principal
    # ------------------------------------------------------------------
    def action_post(self):
        """Override: tras postear, genera el asiento de reparto si aplica."""
        res = super().action_post()
        for payment in self:
            if (
                payment.split_template_id
                and not payment.split_move_id
                and payment.amount > 0
            ):
                payment._create_split_move()
        return res

    # ------------------------------------------------------------------
    # Cancelación → asiento inverso
    # ------------------------------------------------------------------
    def action_cancel(self):
        """Override: al cancelar, revierte el asiento de reparto si existe."""
        for payment in self:
            if payment.split_move_id and payment.split_move_id.state == "posted":
                payment._reverse_split_move()
        return super().action_cancel()

    def action_draft(self):
        """Override: al pasar a borrador, si el asiento de reparto está
        en borrador, lo eliminamos."""
        for payment in self:
            if payment.split_move_id and payment.split_move_id.state == "draft":
                payment.split_move_id.unlink()
                payment.split_move_id = False
        return super().action_draft()

    # ------------------------------------------------------------------
    # Generación del asiento de reparto
    # ------------------------------------------------------------------
    def _create_split_move(self):
        """Genera el asiento contable de reparto para este pago.

        Cálculo de importes:
        ────────────────────
        La base de reparto es el importe del pago (self.amount).
        - En modo 'lines_sum_to_100':
            total_a_repartir = amount * (split_base_percentage / 100)
            Cada línea recibe:  total_a_repartir * (line.percentage / 100)
        - En modo 'lines_sum_to_base':
            Cada línea recibe:  amount * (line.percentage / 100)
            (la suma de porcentajes ya iguala a split_base_percentage)

        Multi-currency:
        ───────────────
        Si la moneda del pago difiere de la de la compañía, las líneas
        del asiento llevan amount_currency en la moneda del pago y
        balance en moneda compañía (conversión a fecha del pago).

        Redondeos:
        ──────────
        Se ajusta la última línea de crédito para que cuadre exactamente.
        """
        self.ensure_one()
        template = self.split_template_id
        if not template or not template.split_line_ids:
            return

        company = self.company_id
        payment_currency = self.currency_id
        company_currency = company.currency_id
        is_same_currency = payment_currency == company_currency
        date = self.date or fields.Date.context_today(self)

        # ── Cálculo de importes por línea ──
        base_amount = self.amount  # en moneda del pago

        line_amounts = []  # [(template_line, amount_currency)]
        if template.split_base_mode == "lines_sum_to_100":
            total_to_split = base_amount * (template.split_base_percentage / 100.0)
            for tline in template.split_line_ids:
                amt = total_to_split * (tline.percentage / 100.0)
                line_amounts.append((tline, amt))
        else:  # lines_sum_to_base
            for tline in template.split_line_ids:
                amt = base_amount * (tline.percentage / 100.0)
                line_amounts.append((tline, amt))

        # Redondeo: calcular total real y ajustar última línea
        total_to_split_currency = sum(a for _, a in line_amounts)
        # Recalcular por si acaso (modo lines_sum_to_100)
        if template.split_base_mode == "lines_sum_to_100":
            expected_total = base_amount * (template.split_base_percentage / 100.0)
        else:
            expected_total = sum(
                base_amount * (tl.percentage / 100.0) for tl in template.split_line_ids
            )
        expected_total = payment_currency.round(expected_total)

        # Redondear cada línea
        rounded_amounts = []
        for tline, amt in line_amounts:
            rounded_amounts.append((tline, payment_currency.round(amt)))

        # Ajustar última línea para cuadrar
        rounded_total = sum(a for _, a in rounded_amounts)
        diff = payment_currency.round(expected_total - rounded_total)
        if diff and rounded_amounts:
            last_tline, last_amt = rounded_amounts[-1]
            rounded_amounts[-1] = (last_tline, last_amt + diff)

        total_split_currency = sum(a for _, a in rounded_amounts)

        # ── Conversión a moneda compañía ──
        if is_same_currency:
            total_split_company = total_split_currency
            line_balances = [(tl, amt) for tl, amt in rounded_amounts]
        else:
            total_split_company = payment_currency._convert(
                total_split_currency, company_currency, company, date
            )
            line_balances = []
            running_balance = 0.0
            for i, (tline, amt_cur) in enumerate(rounded_amounts):
                if i < len(rounded_amounts) - 1:
                    bal = payment_currency._convert(
                        amt_cur, company_currency, company, date
                    )
                    bal = company_currency.round(bal)
                    running_balance += bal
                    line_balances.append((tline, bal))
                else:
                    # Última línea: cuadrar por diferencia
                    bal = company_currency.round(total_split_company - running_balance)
                    line_balances.append((tline, bal))

        # ── Líneas del asiento ──
        move_lines = []

        # 1) Línea DEBE (debit) — cuenta origen/clearing
        debit_vals = {
            "name": _("Reparto cobro %(payment)s", payment=self.name or ""),
            "account_id": template.debit_account_id.id,
            "debit": total_split_company if total_split_company > 0 else 0.0,
            "credit": -total_split_company if total_split_company < 0 else 0.0,
            "partner_id": self.partner_id.id,
        }
        if not is_same_currency:
            debit_vals["currency_id"] = payment_currency.id
            debit_vals["amount_currency"] = total_split_currency
        move_lines.append(Command.create(debit_vals))

        # 2) Líneas HABER (credit) — una por línea de plantilla
        for tline, balance in line_balances:
            amt_cur = dict(rounded_amounts).get(tline, balance)  # fallback
            # Buscar amt_cur de rounded_amounts para este tline
            for tl, ac in rounded_amounts:
                if tl.id == tline.id:
                    amt_cur = ac
                    break

            credit_vals = {
                "name": tline.name or _("Reparto"),
                "account_id": tline.credit_account_id.id,
                "debit": -balance if balance < 0 else 0.0,
                "credit": balance if balance > 0 else 0.0,
                "partner_id": self.partner_id.id,
            }
            if not is_same_currency:
                credit_vals["currency_id"] = payment_currency.id
                credit_vals["amount_currency"] = -amt_cur

            # Analítica: preferir analytic_distribution, fallback a account_id
            if tline.analytic_distribution:
                credit_vals["analytic_distribution"] = tline.analytic_distribution
            elif tline.analytic_account_id:
                credit_vals["analytic_distribution"] = {
                    str(tline.analytic_account_id.id): 100.0
                }

            move_lines.append(Command.create(credit_vals))

        # ── Crear asiento ──
        move_vals = {
            "move_type": "entry",
            "journal_id": template.journal_id.id,
            "date": date,
            "ref": _(
                "Reparto cobro %(payment)s (Plantilla %(template)s)",
                payment=self.name or "",
                template=template.name,
            ),
            "company_id": company.id,
            "currency_id": payment_currency.id,
            "partner_id": self.partner_id.id,
            "line_ids": move_lines,
        }
        split_move = self.env["account.move"].sudo().create(move_vals)

        # Publicar automáticamente
        split_move.action_post()

        # Guardar referencia
        self.split_move_id = split_move.id

        # ── Crear log de auditoría ──
        self.env["account.payment.split.log"].sudo().create(
            {
                "payment_id": self.id,
                "split_move_id": split_move.id,
                "template_id": template.id,
                "company_id": company.id,
                "currency_id": payment_currency.id,
                "amount_base_currency": total_split_currency,
                "amount_base_company": total_split_company,
                "date": date,
                "state": "posted",
                "invoice_ids": [
                    (6, 0, self.reconciled_invoice_ids.ids or self.invoice_ids.ids)
                ],
            }
        )

        _logger.info(
            "Pago %s: asiento de reparto %s creado (plantilla=%s, "
            "base=%s %s, company=%s %s)",
            self.name,
            split_move.name,
            template.name,
            total_split_currency,
            payment_currency.name,
            total_split_company,
            company_currency.name,
        )

    # ------------------------------------------------------------------
    # Reversión del asiento de reparto
    # ------------------------------------------------------------------
    def _reverse_split_move(self):
        """Crea un asiento inverso para anular el reparto.

        Usa account.move._reverse_moves() directamente, evitando el wizard
        account.move.reversal que tiene constrains de tipo de diario y
        requiere contexto active_ids.
        """
        self.ensure_one()
        split_move = self.split_move_id
        if not split_move or split_move.state != "posted":
            return

        # Crear reversal con cancel=True para que se reconcilie automáticamente
        default_values = {
            "ref": _("Cancelación reparto cobro %(payment)s", payment=self.name),
            "date": fields.Date.context_today(self),
            "journal_id": split_move.journal_id.id,
            "auto_post": "no",
        }
        reverse_moves = split_move._reverse_moves(
            default_values_list=[default_values],
            cancel=True,  # Reconcilia y postea automáticamente
        )

        # Actualizar log
        log = self.env["account.payment.split.log"].search(
            [
                ("payment_id", "=", self.id),
                ("split_move_id", "=", split_move.id),
            ],
            limit=1,
        )
        if log:
            log.state = "reversed"

        _logger.info(
            "Pago %s: asiento de reparto %s revertido por cancelación. " "Reverso: %s",
            self.name,
            split_move.name,
            reverse_moves.mapped("name"),
        )

    # ------------------------------------------------------------------
    # Botones / Smart Buttons
    # ------------------------------------------------------------------
    def button_open_split_move(self):
        """Abre el asiento de reparto en una vista formulario."""
        self.ensure_one()
        if not self.split_move_id:
            return
        return {
            "name": _("Asiento de Reparto"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.split_move_id.id,
            "context": {"create": False},
        }
