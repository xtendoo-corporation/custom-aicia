# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from base64 import b64decode
from collections import defaultdict
from datetime import date, datetime
from html import escape
from io import BytesIO

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

try:
    import openpyxl
except ImportError:
    _logger.warning("La librería 'openpyxl' no está instalada.")
    openpyxl = None

# ---------------------------------------------------------------------------
# Estructura del Excel de origen (sistema contable legado AICIA):
#
#  Apuntes2025.xlsx — hoja "Apuntes"  (cabecera del asiento)
#    Col 0: ID_Apunte          → clave de unión con Lineas_Apunte
#    Col 1: Numero_Apunte      → referencia del asiento (numero_asiento_aicia)
#    Col 2: Fecha_Contable     → entero YYYYMMDD  (ej: 20250103)
#    Col 3: Fecha_Introduccion → datetime (no se usa)
#    Col 4: Descripcion        → nombre del asiento
#    Col 5: Numero_Documento   → referencia adicional
#    Col 6: Importe_Total      → en céntimos; NO se usa como total. Si no coincide
#                                con la suma de las líneas solo se anota en el log
#    Col 7: Validado           → True/False; solo se importan los True
#    Col 8: Anulado            → True/False; se omiten los True si skip_anulados
#    Col 9: Clase_Apunte       → no se usa
#
#  Lineas_Apunte2025.xlsx — hoja "Lineas_Apunte"  (líneas contables)
#    Col 0: ID_Apunte          → clave de unión con Apuntes (col 0 de ambos ficheros)
#    Col 1: ID_Linea           → identificador de línea (no se usa)
#    Col 2: Cuenta_Contable    → 9 dígitos (ej: 610000495)
#    Col 3: ID_Departamento    → no se usa
#    Col 4: ID_Proyecto        → cuenta analítica (code en account.analytic.account)
#    Col 5: Descripcion        → descripción de la línea
#    Col 6: Importe            → entero en CÉNTIMOS (siempre positivo)
#    Col 7: Tipo_Contable      → "D" = Debe / "H" = Haber
#
#  Reglas de transformación:
#    - Cuenta_Contable tiene 9 dígitos: los 5 PRIMEROS más un "0" son la cuenta
#      contable de Odoo y los 4 ÚLTIMOS el código AICIA del contacto asociado a
#      la línea (aicia.partner.code). Ej.: 610003495 → cuenta 610000, contacto
#      con el código AICIA 3495.
#    - El código es único por TIPO de tercero (personal, proveedor, cliente). El
#      tipo se deduce del grupo de la cuenta (3 primeros dígitos), ver
#      PARTNER_TYPE_BY_ACCOUNT_GROUP. Las cuentas de otros grupos (bancos, gastos,
#      ingresos…) no llevan contacto.
#    - No se redirigen grupos ni se usan cuentas colectivas. Solo existe el
#      mapeo manual opcional (aicia.account.importer.account.mapping).
#    - Los importes están en CÉNTIMOS; se suman como enteros para comprobar el
#      cuadre. El total de un asiento es siempre la suma de sus líneas.
#    - Tipo_Contable "D" → debit; "H" → credit; otro valor es un error.
#    - Clave de idempotencia: Numero_Apunte (marca técnica en narration).
#    - Solo se importan apuntes con Validado=True.
# ---------------------------------------------------------------------------

# Cuenta de Odoo = ACCOUNT_PREFIX_LENGTH primeros dígitos de la cuenta legada + "0"
# (6 dígitos en total)
ACCOUNT_PREFIX_LENGTH = 5
ACCOUNT_CODE_LENGTH = 6
# Código AICIA del contacto = últimos dígitos de la cuenta legada
PARTNER_CODE_LENGTH = 4
# Tipo de tercero de cada grupo de cuentas (3 primeros dígitos de la cuenta
# legada). El código AICIA solo es único dentro de un mismo tipo. Los grupos que
# no aparecen aquí no llevan contacto.
PARTNER_TYPE_BY_ACCOUNT_GROUP = {
    # Personal: remuneraciones y sueldos con una subcuenta por empleado
    "460": "employee",
    "465": "employee",
    "610": "employee",
    "611": "employee",
    "616": "employee",
    "618": "employee",
    # Proveedores y acreedores
    "400": "supplier",
    "401": "supplier",
    "410": "supplier",
    # Clientes
    "430": "customer",
    "431": "customer",
    "436": "customer",
}
PARTNER_TYPE_LABELS = {
    "employee": "Personal",
    "supplier": "Proveedor",
    "customer": "Cliente",
}

# Índices de columnas en cada hoja (0-based, según análisis del Excel real)
APUNTES_COLS = {
    "id": 0,
    "numero": 1,
    "fecha": 2,
    "descripcion": 4,
    "numero_documento": 5,
    "importe_total": 6,
    "validado": 7,
    "anulado": 8,
    "clase_apunte": 9,
}

LINEAS_COLS = {
    "id_apunte": 0,   # ID_Apunte — clave de unión con la cabecera (col 0 de ambos ficheros)
    "cuenta": 2,
    "id_proyecto": 4,  # ID_Proyecto → cuenta analítica (code en account.analytic.account)
    "descripcion": 5,
    "importe": 6,
    "tipo": 7,
}


class AiciaAccountImporterAccountMapping(models.Model):
    """Mapeo manual de cuentas: código legado → cuenta Odoo (persistente y global).

    Es opcional y está vacío por defecto. Permite forzar una redirección
    puntual; sin reglas, la cuenta destino son los 5 primeros dígitos más un 0.
    """

    _name = "aicia.account.importer.account.mapping"
    _description = "Mapeo de cuentas para importación AICIA (persistente)"
    _rec_name = "source_code"
    _order = "source_code"

    source_code = fields.Char(
        string="Código origen (legado)",
        required=True,
        help=(
            "Código del sistema legado que se quiere redirigir. "
            "Puede ser el código de 9 dígitos tal cual viene del Excel "
            "(ej: 478000000) o sólo el prefijo (ej: 478000). "
            "Se aplica por coincidencia exacta o por prefijo."
        ),
    )
    source_code_normalized = fields.Char(
        string="Código origen normalizado",
        compute="_compute_source_code_normalized",
        store=True,
        index=True,
    )
    target_account_id = fields.Many2one(
        "account.account",
        string="Cuenta destino (Odoo)",
        required=False,
    )

    @api.depends("source_code")
    def _compute_source_code_normalized(self):
        for mapping in self:
            mapping.source_code_normalized = mapping._normalize_source_code(
                mapping.source_code
            )

    @api.constrains("source_code")
    def _check_source_code(self):
        for mapping in self:
            normalized_code = mapping._normalize_source_code(mapping.source_code)
            if not normalized_code:
                raise ValidationError(
                    _("Debes indicar un código origen válido para el mapeo.")
                )
            duplicated = self.search(
                [
                    ("source_code_normalized", "=", normalized_code),
                    ("id", "!=", mapping.id),
                ],
                limit=1,
            )
            if duplicated:
                raise ValidationError(
                    _("Ya existe un mapeo para el código origen '%s'.")
                    % normalized_code
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "source_code" in vals:
                vals["source_code"] = self._normalize_source_code(vals["source_code"])
        return super().create(vals_list)

    def write(self, vals):
        if "source_code" in vals:
            vals = dict(
                vals,
                source_code=self._normalize_source_code(vals["source_code"]),
            )
        return super().write(vals)

    @api.model
    def _normalize_source_code(self, code):
        return str(code or "").strip().replace(" ", "")


class AiciaAccountImporterWizard(models.TransientModel):
    _name = "aicia.account.importer.wizard"
    _description = "Importador de Apuntes Contables AICIA"

    # ── Ficheros ─────────────────────────────────────────────────────────────
    file_apuntes = fields.Binary(
        string="Apuntes2025.xlsx  (cabecera de asientos)",
    )
    filename_apuntes = fields.Char()
    file_lineas = fields.Binary(
        string="Lineas_Apunte2025.xlsx  (líneas contables)",
    )
    filename_lineas = fields.Char()

    # ── Configuración ────────────────────────────────────────────────────────
    move_state = fields.Selection(
        [("draft", "Borrador"), ("posted", "Confirmado")],
        string="Estado de los asientos importados",
        default="draft",
        required=True,
    )
    skip_anulados = fields.Boolean(
        string="Omitir asientos anulados",
        default=True,
    )
    missing_account_mode = fields.Selection(
        [
            ("create", "Crear la cuenta en Odoo"),
            ("fallback", "Enviar a una cuenta de reserva"),
            ("error", "No importar el asiento (error)"),
        ],
        string="Si la cuenta no existe en Odoo",
        default="create",
        required=True,
        help=(
            "Crear: se crea la cuenta (5 primeros dígitos + 0) con el nombre "
            "'*Cuenta legada XXXXXX (revisar)' para renombrarla después. "
            "Cuenta de reserva: la línea va a la cuenta elegida y su nombre lleva "
            "el código legado. Error: el asiento no se importa."
        ),
    )
    fallback_account_id = fields.Many2one(
        "account.account",
        string="Cuenta de reserva",
        help="Cuenta a la que van las líneas cuya cuenta no existe en Odoo.",
    )

    # ── Mapeo manual de cuentas ──────────────────────────────────────────────
    account_mapping_ids = fields.Many2many(
        "aicia.account.importer.account.mapping",
        "aicia_account_importer_wizard_mapping_rel",
        "wizard_id",
        "mapping_id",
        string="Mapeo de cuentas (global)",
        help=(
            "Define aquí las cuentas del sistema legado que deben redirigirse "
            "a otra cuenta de Odoo antes de importar. El mapeo es global y persistente."
        ),
        readonly=False,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Cargar todos los mapeos existentes al abrir el wizard
        res["account_mapping_ids"] = [
            (6, 0, self.env["aicia.account.importer.account.mapping"].search([]).ids)
        ]
        return res

    # ── Estado y log ─────────────────────────────────────────────────────────
    state = fields.Selection(
        [("draft", "Borrador"), ("done", "Completado")],
        default="draft",
    )
    import_log = fields.Html(string="Log de importación", readonly=True)
    total_created = fields.Integer(string="Asientos creados", readonly=True)
    total_skipped = fields.Integer(string="Omitidos (ya existían)", readonly=True)
    total_errors = fields.Integer(string="Errores", readonly=True)
    total_warnings = fields.Integer(
        string="Con avisos (borrador)", readonly=True
    )
    total_accounts_created = fields.Integer(
        string="Cuentas creadas automáticamente", readonly=True
    )
    total_mismatches = fields.Integer(
        string="Asientos con total de cabecera ≠ suma de líneas (informativo)",
        readonly=True,
    )
    total_debe = fields.Float(
        string="Total Debe importado (suma de líneas)",
        digits=(16, 2),
        readonly=True,
    )
    total_haber = fields.Float(
        string="Total Haber importado (suma de líneas)",
        digits=(16, 2),
        readonly=True,
    )

    # ── Acciones sobre el mapeo manual ───────────────────────────────────────

    def _reload_account_mapping_ids(self):
        self.write(
            {
                "account_mapping_ids": [
                    (
                        6,
                        0,
                        self.env["aicia.account.importer.account.mapping"].search([]).ids,
                    )
                ]
            }
        )

    def action_open_account_mappings(self):
        """Abre la tabla persistente global de mapeos de cuentas."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Mapeo de cuentas AICIA"),
            "res_model": "aicia.account.importer.account.mapping",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "target": "current",
            "context": {"default_target_account_id": False},
        }

    def action_reload_account_mappings(self):
        """Recarga en el wizard los mapeos persistentes guardados."""
        self.ensure_one()
        self._reload_account_mapping_ids()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Mapeos recargados"),
                "message": _("Se han recargado los mapeos globales guardados."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_clear_account_mappings(self):
        """Borra todos los mapeos globales de cuentas AICIA."""
        self.ensure_one()
        AccountMapping = self.env["aicia.account.importer.account.mapping"]
        AccountMapping.search([]).unlink()
        self.write({"account_mapping_ids": [(5, 0, 0)]})
        return False

    DELETE_BATCH = 500

    def action_delete_imported_moves(self):
        """Elimina los asientos creados por este importador, confirmados o no.

        Solo toca los asientos que llevan Nº de asiento AICIA, es decir, los que
        importó este módulo. Los confirmados se pasan antes a borrador. No toca
        facturas ni asientos creados de otra forma.
        """
        self.ensure_one()
        Move = self.env["account.move"].with_context(force_delete=True)
        moves = Move.search([("numero_asiento_aicia", "!=", False)])
        count = len(moves)
        if not count:
            raise UserError(_("No hay asientos importados por el importador AICIA."))
        ids = moves.ids
        for start in range(0, count, self.DELETE_BATCH):
            batch = Move.browse(ids[start : start + self.DELETE_BATCH])
            batch.filtered(lambda m: m.state != "draft").button_draft()
            batch.unlink()
            _logger.info("Borrado de importados: %d/%d", min(start + self.DELETE_BATCH, count), count)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Asientos importados eliminados"),
                "message": _("%d asientos importados eliminados.") % count,
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": self._name,
                    "res_id": self.id,
                    "view_mode": "form",
                    "views": [(False, "form")],
                    "target": "new",
                },
            },
        }

    # ── Acción principal ─────────────────────────────────────────────────────

    def action_import(self):
        """Punto de entrada: cruza los dos Excel y crea los account.move."""
        self.ensure_one()
        if not self.file_apuntes and not self.file_lineas:
            return self._action_apply_account_mappings_to_existing_move_lines()
        if not self.file_apuntes or not self.file_lineas:
            raise UserError(
                _("Debes subir los dos archivos Excel antes de importar.")
            )

        if self.missing_account_mode == "fallback":
            if not self.fallback_account_id:
                raise UserError(
                    _("Elige la cuenta de reserva o cambia la opción de cuentas inexistentes.")
                )
            if self.env.company not in self.fallback_account_id.company_ids:
                raise UserError(
                    _("La cuenta de reserva no pertenece a la compañía actual.")
                )

        activity_log = []
        self._append_import_activity(
            activity_log,
            "info",
            _("Iniciando importación de apuntes contables AICIA."),
        )
        if not openpyxl:
            raise UserError(
                _("La librería 'openpyxl' no está instalada en el servidor.")
            )

        self._append_import_activity(activity_log, "info", _("Leyendo archivo de apuntes."))
        apuntes = self._parse_apuntes(b64decode(self.file_apuntes))
        self._append_import_activity(
            activity_log,
            "success",
            _("%d cabeceras de asiento válidas leídas.") % len(apuntes),
        )

        self._append_import_activity(activity_log, "info", _("Leyendo archivo de líneas."))
        lineas_by_apunte = self._parse_lineas(b64decode(self.file_lineas))
        total_lineas = sum(len(lineas) for lineas in lineas_by_apunte.values())
        self._append_import_activity(
            activity_log,
            "success",
            _("%d líneas contables leídas.") % total_lineas,
        )

        # Reglas de mapeo manual de cuentas (vacías por defecto)
        account_mapping = self._get_account_mapping_rules()
        self._append_import_activity(
            activity_log,
            "info",
            _("%d reglas de mapeo manual de cuentas cargadas.")
            % len(account_mapping.get("prefixes", account_mapping)),
        )
        runtime = self._prepare_import_runtime(
            apuntes, lineas_by_apunte, account_mapping
        )
        results = []
        created = skipped = errors = warnings = 0
        total_debe_cents = total_haber_cents = 0
        mismatches = []
        missing_accounts = set()
        missing_partners = {}
        total_apuntes = len(apuntes)

        for index, (id_apunte, cabecera) in enumerate(apuntes.items(), start=1):
            numero_key = cabecera["numero"]
            # Join por ID_Apunte (col 0 de ambos ficheros)
            lineas = lineas_by_apunte.get(id_apunte) or []
            self._append_import_activity(
                activity_log,
                "info",
                _("Procesando asiento %(index)d/%(total)d — ID=%(id)s, Nº=%(num)s, líneas=%(lines)d.")
                % {
                    "index": index,
                    "total": total_apuntes,
                    "id": id_apunte,
                    "num": numero_key,
                    "lines": len(lineas),
                },
            )
            if not lineas:
                ids_lineas = sorted(lineas_by_apunte.keys(), key=str)
                ids_str = ", ".join(str(x) for x in ids_lineas[:20])
                if len(ids_lineas) > 20:
                    ids_str += f" … ({len(ids_lineas)} en total)"
                result = {
                    "status": "error",
                    "ref": str(numero_key),
                    "msg": _(
                        "Asiento ID=%s (Nº %s) no tiene líneas contables. "
                        "IDs encontrados en Lineas_Apunte: [%s]"
                    ) % (id_apunte, numero_key, ids_str or "ninguno"),
                }
                results.append(result)
                self._append_import_activity(activity_log, "error", result["msg"])
                errors += 1
                continue

            result = self._process_asiento(
                cabecera,
                lineas,
                missing_accounts,
                missing_partners,
                account_mapping,
                runtime=runtime,
            )
            results.append(result)
            if result["status"] in ("created", "warning"):
                total_debe_cents += result.get("debe_cents", 0)
                total_haber_cents += result.get("haber_cents", 0)
            if result.get("header_mismatch"):
                mismatches.append(result["header_mismatch"])
            if result["status"] == "created":
                created += 1
                activity_status = "success"
            elif result["status"] == "skipped":
                skipped += 1
                activity_status = "warning"
            elif result["status"] == "warning":
                warnings += 1
                activity_status = "warning"
            else:
                errors += 1
                activity_status = "error"
            self._append_import_activity(activity_log, activity_status, result["msg"])

        # Cuentas no encontradas: se añaden al mapeo manual (sin destino) para
        # que el usuario pueda asignarles una cuenta y reimportar.
        AccountMapping = self.env["aicia.account.importer.account.mapping"]
        existing_sources = set(
            AccountMapping.search([]).mapped("source_code_normalized")
        )
        new_mappings = []
        for code in sorted(missing_accounts):
            norm_code = AccountMapping._normalize_source_code(code)
            if norm_code and norm_code not in existing_sources:
                new_mappings.append({"source_code": norm_code})
                existing_sources.add(norm_code)
        if new_mappings:
            AccountMapping.create(new_mappings)
            self._append_import_activity(
                activity_log,
                "warning",
                _("%d cuentas no encontradas añadidas al mapeo manual.")
                % len(new_mappings),
            )
        elif missing_accounts:
            self._append_import_activity(
                activity_log,
                "info",
                _("Las cuentas no encontradas ya existían en el mapeo manual."),
            )

        created_accounts = runtime.get("created_accounts", {})
        origin_counts = runtime.get("account_origin_counts", {})
        if created_accounts:
            self._append_import_activity(
                activity_log,
                "warning",
                _("%d cuentas creadas automáticamente; revisa su nombre y tipo.")
                % len(created_accounts),
            )
        fallback_counts = {
            code: n for (origin, code), n in origin_counts.items() if origin == "fallback"
        }
        if fallback_counts:
            self._append_import_activity(
                activity_log,
                "warning",
                _("%(lines)d líneas de %(accounts)d cuentas inexistentes enviadas a la cuenta de reserva.")
                % {"lines": sum(fallback_counts.values()), "accounts": len(fallback_counts)},
            )
        self._reload_account_mapping_ids()
        self._append_import_activity(
            activity_log,
            "info",
            _(
                "Totales importados (suma de líneas): Debe %(debe).2f € — "
                "Haber %(haber).2f €."
            )
            % {"debe": total_debe_cents / 100, "haber": total_haber_cents / 100},
        )
        self._append_import_activity(
            activity_log,
            "success" if not errors else "warning",
            _(
                "Importación finalizada: %(created)d creados, %(skipped)d omitidos, "
                "%(warnings)d avisos y %(errors)d errores."
            )
            % {
                "created": created,
                "skipped": skipped,
                "warnings": warnings,
                "errors": errors,
            },
        )

        self.write(
            {
                "state": "done",
                "total_created": created,
                "total_skipped": skipped,
                "total_errors": errors,
                "total_warnings": warnings,
                "total_mismatches": len(mismatches),
                "total_accounts_created": len(created_accounts),
                "total_debe": total_debe_cents / 100,
                "total_haber": total_haber_cents / 100,
                "import_log": self._build_log_html(
                    results,
                    missing_accounts,
                    missing_partners,
                    activity_log,
                    totals={
                        "debe": total_debe_cents / 100,
                        "haber": total_haber_cents / 100,
                    },
                    mismatches=mismatches,
                    created_accounts={
                        code: (acc.display_name, origin_counts.get(("created", code), 0))
                        for code, acc in created_accounts.items()
                    },
                    fallback_accounts=fallback_counts,
                ),
            }
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }

    def _action_apply_account_mappings_to_existing_move_lines(self):
        """Aplica los mapeos guardados sobre apuntes contables ya existentes."""
        self.ensure_one()
        activity_log = []
        self._append_import_activity(
            activity_log,
            "info",
            _(
                "No se han indicado archivos Excel; se revisarán los apuntes "
                "contables existentes con el mapeo de cuentas guardado."
            ),
        )

        results = []
        moved_count = skipped_count = 0
        processed_line_ids = set()
        mapping_rules = self._get_account_mapping_rules()
        for source_code, target_account in mapping_rules.get("prefixes", mapping_rules):
            if self.env.company not in target_account.company_ids:
                skipped_count += 1
                msg = _(
                    "Mapeo %(source)s omitido: la cuenta destino %(target)s "
                    "no pertenece a la compañía actual."
                ) % {
                    "source": source_code,
                    "target": target_account.display_name,
                }
                results.append({"status": "skipped", "ref": source_code, "msg": msg})
                self._append_import_activity(activity_log, "warning", msg)
                continue

            source_accounts = self._get_source_accounts_for_mapping(
                source_code, target_account
            )
            if not source_accounts:
                skipped_count += 1
                msg = _(
                    "Mapeo %(source)s omitido: no existe ninguna cuenta origen "
                    "en Odoo para ese código."
                ) % {"source": source_code}
                results.append({"status": "skipped", "ref": source_code, "msg": msg})
                self._append_import_activity(activity_log, "info", msg)
                continue

            domain = [
                ("company_id", "=", self.env.company.id),
                ("account_id", "in", source_accounts.ids),
            ]
            if processed_line_ids:
                domain.append(("id", "not in", list(processed_line_ids)))
            move_lines = self.env["account.move.line"].search(domain)
            if not move_lines:
                skipped_count += 1
                msg = _(
                    "Mapeo %(source)s → %(target)s sin apuntes pendientes de mover."
                ) % {
                    "source": source_code,
                    "target": target_account.display_name,
                }
                results.append({"status": "skipped", "ref": source_code, "msg": msg})
                self._append_import_activity(activity_log, "info", msg)
                continue

            move_lines.with_context(check_move_validity=False).write(
                {"account_id": target_account.id}
            )
            processed_line_ids.update(move_lines.ids)
            moved_count += len(move_lines)
            msg = _(
                "Mapeo %(source)s → %(target)s aplicado a %(count)d apuntes."
            ) % {
                "source": source_code,
                "target": target_account.display_name,
                "count": len(move_lines),
            }
            results.append({"status": "created", "ref": source_code, "msg": msg})
            self._append_import_activity(activity_log, "success", msg)

        if not mapping_rules.get("prefixes", mapping_rules):
            msg = _("No hay mapeos de cuentas configurados.")
            results.append({"status": "skipped", "ref": "-", "msg": msg})
            self._append_import_activity(activity_log, "warning", msg)
            skipped_count = 1

        self._append_import_activity(
            activity_log,
            "success" if moved_count else "warning",
            _(
                "Revisión finalizada: %(moved)d apuntes movidos, "
                "%(skipped)d mapeos sin cambios."
            )
            % {"moved": moved_count, "skipped": skipped_count},
        )
        self._reload_account_mapping_ids()
        self.write(
            {
                "state": "done",
                "total_created": moved_count,
                "total_skipped": skipped_count,
                "total_errors": 0,
                "total_warnings": 0,
                "import_log": self._build_log_html(
                    results, set(), {}, activity_log
                ),
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }

    # ── Utilidades de lectura de celdas ───────────────────────────────────────

    @staticmethod
    def _cell(row, index):
        """Valor de la celda o None si la fila es más corta que el índice."""
        return row[index] if len(row) > index else None

    @staticmethod
    def _to_cents(value) -> int:
        """Convierte un importe del Excel (céntimos) a entero.

        Lanza ValueError/TypeError si el valor no es numérico.
        """
        if value is None or value == "":
            return 0
        return int(round(float(value)))

    # ── Parseo de Apuntes2025.xlsx ────────────────────────────────────────────

    def _parse_apuntes(self, content: bytes) -> dict:
        """Lee Apuntes2025.xlsx y devuelve {ID_Apunte: cabecera_dict}.

        Solo incluye apuntes Validado=True y Anulado=False (si skip_anulados).
        """
        wb = self._open_workbook(content, "Apuntes2025.xlsx")
        ws = wb.worksheets[0]

        apuntes = {}
        c = APUNTES_COLS
        for row in ws.iter_rows(min_row=2, values_only=True):
            id_apunte = self._cell(row, c["id"])
            if id_apunte is None:
                continue
            try:
                id_apunte = int(float(id_apunte))
            except (ValueError, TypeError):
                id_apunte = str(id_apunte).strip()

            validado = self._cell(row, c["validado"])
            anulado = self._cell(row, c["anulado"])

            if not validado:
                continue
            if self.skip_anulados and anulado:
                continue

            numero_raw = self._cell(row, c["numero"])
            try:
                numero_key = int(float(numero_raw))
            except (ValueError, TypeError):
                numero_key = str(numero_raw).strip()

            # Importe_Total de la cabecera (céntimos). Solo sirve para avisar si
            # no coincide con la suma de las líneas; None si falta o no es válido.
            try:
                importe_total = self._cell(row, c["importe_total"])
                importe_total = (
                    None
                    if importe_total is None or importe_total == ""
                    else self._to_cents(importe_total)
                )
            except (ValueError, TypeError):
                importe_total = None

            clase_raw = self._cell(row, c["clase_apunte"])

            # Clave: ID_Apunte (col 0) — es la clave de unión con el fichero de líneas.
            # Numero_Apunte (col 1) se guarda en "numero" y se usa como nº de asiento AICIA.
            apuntes[id_apunte] = {
                "id": id_apunte,
                "numero": numero_key,
                "fecha": self._parse_fecha_contable(self._cell(row, c["fecha"])),
                "descripcion": str(self._cell(row, c["descripcion"]) or "").strip(),
                "numero_documento": str(
                    self._cell(row, c["numero_documento"]) or ""
                ).strip(),
                "importe_total": importe_total,
                "clase_apunte": str(clase_raw or "").strip().upper(),
            }

        if not apuntes:
            raise UserError(
                _(
                    "El archivo Apuntes2025.xlsx no contiene asientos válidos "
                    "(Validado=True, Anulado=False)."
                )
            )
        return apuntes

    # ── Parseo de Lineas_Apunte2025.xlsx ─────────────────────────────────────

    def _parse_lineas(self, content: bytes) -> dict:
        """Lee Lineas_Apunte2025.xlsx y devuelve {ID_Apunte: [linea_dict, ...]}.

        Cada línea lleva su importe en céntimos enteros ("cents") para sumar sin
        errores de coma flotante. Las líneas con importe o tipo inválidos llevan
        el motivo en "error" y hacen fallar el asiento al que pertenecen.
        """
        wb = self._open_workbook(content, "Lineas_Apunte2025.xlsx")
        ws = wb.worksheets[0]

        lineas_by_apunte = defaultdict(list)
        c = LINEAS_COLS
        for row in ws.iter_rows(min_row=2, values_only=True):
            id_apunte = self._cell(row, c["id_apunte"])
            if id_apunte is None:
                continue
            # Normalizar a int para que el cruce con Apuntes funcione
            # independientemente del tipo devuelto por openpyxl (int/float/str)
            try:
                id_apunte = int(float(id_apunte))
            except (ValueError, TypeError):
                id_apunte = str(id_apunte).strip()
            cuenta_raw = self._cell(row, c["cuenta"])
            if isinstance(cuenta_raw, (int, float)):
                cuenta = str(int(cuenta_raw)).zfill(9)
            else:
                cuenta = str(cuenta_raw or "").strip().zfill(9)
            tipo = str(self._cell(row, c["tipo"]) or "").strip().upper()
            descripcion = str(self._cell(row, c["descripcion"]) or "").strip()

            error = None
            cents = 0
            importe_raw = self._cell(row, c["importe"])
            try:
                cents = self._to_cents(importe_raw)
            except (ValueError, TypeError):
                error = _("Importe no numérico '%s'") % importe_raw
            if not error and cents < 0:
                error = _("Importe negativo '%s'") % importe_raw
            if not error and tipo not in ("D", "H"):
                error = _("Tipo_Contable inválido '%s' (debe ser D o H)") % tipo

            # ID_Proyecto → cuenta analítica (col 4)
            id_proyecto_raw = self._cell(row, c["id_proyecto"])
            try:
                id_proyecto = int(float(id_proyecto_raw)) if id_proyecto_raw is not None else None
            except (ValueError, TypeError):
                id_proyecto = str(id_proyecto_raw).strip() if id_proyecto_raw else None

            importe = round(cents / 100, 2)
            lineas_by_apunte[id_apunte].append(
                {
                    "cuenta": cuenta,
                    "descripcion": descripcion,
                    "cents": cents,
                    "tipo": tipo,
                    "debit": importe if tipo == "D" else 0.0,
                    "credit": importe if tipo == "H" else 0.0,
                    "id_proyecto": id_proyecto,
                    "error": error,
                }
            )

        return lineas_by_apunte

    # ── Procesamiento de un asiento ───────────────────────────────────────────

    def _process_asiento(
        self,
        cabecera: dict,
        lineas: list,
        missing_accounts: set,
        missing_partners: dict,
        account_mapping: dict = None,
        runtime: dict | None = None,
    ) -> dict:
        """Crea un account.move a partir de la cabecera y sus líneas.

        El total del asiento es siempre la suma de sus líneas (en céntimos). Si
        la cabecera trae un Importe_Total distinto, no se usa: el asiento se
        importa igual y la diferencia solo queda anotada en el log.
        """
        legacy_number = str(cabecera["numero"])
        # ── Detectar si es un asiento de nómina ──────────────────────────────
        # Criterio: Numero_Documento empieza por "NO-" (insensible a mayúsculas).
        # Solo afecta al diario: las nóminas van siempre al diario misceláneo.
        is_nomina = str(cabecera.get("numero_documento", "") or "").upper().startswith("NO-")
        nomina_tag = " 💼" if is_nomina else ""

        # Detectar el diario automáticamente según las cuentas de las líneas
        journal = self._get_journal_for_lines(lineas, is_nomina=is_nomina, runtime=runtime)
        # Idempotencia: busca en el diario detectado usando una marca técnica.
        legacy_marker = self._legacy_import_marker(legacy_number)
        runtime = runtime or {}
        existing = runtime.get("existing_moves", {}).get((journal.id, legacy_marker))
        if existing and not isinstance(existing, dict):
            existing = {
                "id": existing.id,
                "state": existing.state,
            }
        if not existing:
            existing_move = self.env["account.move"].search(
                [
                    ("journal_id", "=", journal.id),
                    ("state", "in", ["draft", "posted"]),
                    ("narration", "ilike", legacy_marker),
                ],
                limit=1,
            )
            if existing_move:
                existing = {"id": existing_move.id, "state": existing_move.state}
                runtime.setdefault("existing_moves", {})[
                    (journal.id, legacy_marker)
                ] = existing
        if existing:
            state_label = {"draft": "borrador", "posted": "confirmado"}.get(
                existing["state"], existing["state"]
            )
            return {
                "status": "skipped",
                "ref": legacy_number,
                "msg": _(
                    "Asiento Nº %s%s ya existe en Odoo (ID %d, estado: %s). "
                    "Elimínalo o resetéalo a borrador para poder reimportarlo."
                ) % (legacy_number, nomina_tag, existing["id"], state_label),
            }

        # Construir líneas del asiento
        line_vals = []
        errors = []
        line_warnings = []
        for linea in lineas:
            vals, error, warning = self._build_line_vals(
                linea,
                cabecera["descripcion"],
                missing_accounts,
                missing_partners,
                account_mapping,
                runtime=runtime,
            )
            if error:
                errors.append(error)
            else:
                line_vals.append((0, 0, vals))
                if warning:
                    line_warnings.append(warning)

        if errors:
            return {
                "status": "error",
                "ref": legacy_number,
                "msg": _("Asiento Nº %s%s — errores en líneas: %s")
                % (legacy_number, nomina_tag, "; ".join(errors)),
            }
        if not line_vals:
            return {
                "status": "error",
                "ref": legacy_number,
                "msg": _("Asiento Nº %s%s no generó ninguna línea válida.")
                % (legacy_number, nomina_tag),
            }

        # ── Totales a partir de las líneas (enteros en céntimos) ─────────────
        debe_cents = sum(linea["cents"] for linea in lineas if linea["tipo"] == "D")
        haber_cents = sum(linea["cents"] for linea in lineas if linea["tipo"] == "H")
        if debe_cents != haber_cents:
            return {
                "status": "error",
                "ref": legacy_number,
                "msg": _(
                    "Asiento Nº %s%s no cuadra: Debe=%.2f Haber=%.2f (diferencia=%.2f)"
                ) % (
                    legacy_number,
                    nomina_tag,
                    debe_cents / 100,
                    haber_cents / 100,
                    abs(debe_cents - haber_cents) / 100,
                ),
            }

        # El Importe_Total de la cabecera no se usa como total: solo se compara
        # con la suma de las líneas para anotar en el log los descuadres del legado.
        header_cents = cabecera.get("importe_total")
        header_mismatch = None
        if header_cents is not None and header_cents != debe_cents:
            header_mismatch = {
                "ref": legacy_number,
                "header": header_cents / 100,
                "lines": debe_cents / 100,
            }

        move_vals = {
            "ref": self._build_move_ref(cabecera) or False,
            "name": "/",
            "date": cabecera["fecha"],
            "journal_id": journal.id,
            "line_ids": line_vals,
            "narration": self._build_move_narration(cabecera, legacy_number),
            "numero_asiento_aicia": legacy_number,
        }

        try:
            with self.env.cr.savepoint():
                move = self.env["account.move"].create(move_vals)
        except Exception as exc:
            return {
                "status": "error",
                "ref": legacy_number,
                "msg": _("Error al crear asiento Nº %s%s: %s")
                % (legacy_number, nomina_tag, str(exc)),
            }
        runtime.setdefault("existing_moves", {})[(journal.id, legacy_marker)] = move

        needs_review = bool(line_warnings)
        post_error = None
        if not needs_review and self.move_state == "posted":
            try:
                with self.env.cr.savepoint():
                    move.action_post()
            except Exception as exc:
                post_error = str(exc)

        totals = {"debe_cents": debe_cents, "haber_cents": haber_cents}
        reasons = []
        if line_warnings:
            refs_uniq = sorted({w.split("'")[1] for w in line_warnings if "'" in w})
            reasons.append(
                _("contactos no resueltos: %s")
                % (", ".join(refs_uniq) if refs_uniq else "; ".join(line_warnings))
            )
        if post_error:
            reasons.append(_("no se pudo confirmar: %s") % post_error)
        if reasons:
            return {
                "status": "warning",
                "ref": legacy_number,
                "msg": _(
                    "Asiento Nº %s%s creado en BORRADOR (ID Odoo %d) — %s"
                ) % (legacy_number, nomina_tag, move.id, "; ".join(reasons)),
                "header_mismatch": header_mismatch,
                **totals,
            }
        return {
            "status": "created",
            "ref": legacy_number,
            "msg": _("Asiento Nº %s%s creado (ID Odoo %d).")
            % (legacy_number, nomina_tag, move.id),
            "header_mismatch": header_mismatch,
            **totals,
        }

    def _build_line_vals(
        self,
        linea: dict,
        asiento_desc: str,
        missing_accounts: set,
        missing_partners: dict,
        account_mapping: dict = None,
        runtime: dict | None = None,
    ) -> tuple:
        """Construye el dict de valores para una account.move.line.

        La cuenta legada de 9 dígitos se divide en:
          - 5 primeros + "0" → cuenta contable de Odoo
          - 4 últimos         → código AICIA del contacto (aicia.partner.code),
                                único por tipo de tercero

        Solo los grupos de cuenta con tipo de tercero (personal, proveedor,
        cliente) llevan contacto. Devuelve (vals, error, warning). Si no existe
        contacto con ese código, la línea se crea sin contacto y se devuelve un
        aviso.
        """
        if linea.get("error"):
            return None, linea["error"], None

        legacy_account_code = linea["cuenta"]

        account, origin = self._resolve_account(
            legacy_account_code,
            missing_accounts,
            account_mapping,
            runtime=runtime,
        )
        if not account:
            return None, _(
                "Cuenta '%(account)s' no encontrada en el plan contable "
                "(cuenta legada: %(legacy)s)."
            ) % {
                "account": self._odoo_account_code(legacy_account_code),
                "legacy": legacy_account_code,
            }, None

        partner = None
        warning_msg = None
        partner_type = PARTNER_TYPE_BY_ACCOUNT_GROUP.get(legacy_account_code[:3])
        if partner_type:
            partner_code = self._partner_code_from_account(legacy_account_code)
            partner = self._resolve_partner_by_aicia_code(
                partner_code, partner_type, runtime=runtime
            )
            if not partner:
                warning_msg = _(
                    "Contacto no encontrado para el código AICIA '%(code)s' de tipo "
                    "%(type)s (cuenta legada: %(legacy)s)"
                ) % {
                    "code": partner_code,
                    "type": PARTNER_TYPE_LABELS[partner_type],
                    "legacy": legacy_account_code,
                }
                if missing_partners is not None:
                    missing_partners[(partner_type, partner_code)] = legacy_account_code

        # ── Distribución analítica por ID_Proyecto (100%) ────────────────────
        # ID_Proyecto=0 es un proyecto válido ([0] AICIA), por lo que se debe
        # distinguir explícitamente de la ausencia de valor (None).
        analytic_distribution = {}
        id_proyecto = linea.get("id_proyecto")
        if id_proyecto is not None:
            runtime = runtime or {}
            analytic = runtime.get("analytic_by_code", {}).get(str(id_proyecto))
            if analytic is None:
                analytic = self.env["account.analytic.account"].search(
                    [("code", "=", str(id_proyecto))], order="id", limit=1
                )
                runtime.setdefault("analytic_by_code", {})[str(id_proyecto)] = analytic
            if analytic:
                analytic_distribution = {str(analytic.id): 100.0}
            else:
                _logger.debug(
                    "Cuenta analítica no encontrada para ID_Proyecto=%s", id_proyecto
                )

        return (
            {
                "account_id": account.id,
                "partner_id": partner.id if partner else False,
                "name": self._line_name(
                    linea["descripcion"] or asiento_desc or "/",
                    origin,
                    legacy_account_code,
                ),
                "debit": linea["debit"],
                "credit": linea["credit"],
                "analytic_distribution": analytic_distribution or False,
            },
            None,
            warning_msg,
        )

    # ── Resolución de diarios ────────────────────────────────────────────────

    def _get_journal_for_lines(
        self, lineas: list, is_nomina: bool = False, runtime: dict | None = None
    ):
        """Determina el diario automáticamente según los prefijos de cuenta.
        - Nóminas (is_nomina=True)  → diario misceláneo (type='general') siempre
        - Cuentas 430/431/436       → diario de ventas (type='sale')
        - Cuentas 400/401           → diario de compras (type='purchase')
        - Ambos o ninguno           → diario misceláneo (type='general')
        """
        journal_type = self._get_journal_type_for_lines(lineas, is_nomina=is_nomina)
        runtime = runtime or {}
        journal = runtime.get("journals_by_type", {}).get(journal_type)
        if not journal:
            journal = self.env["account.journal"].search(
                [("type", "=", journal_type), ("company_id", "=", self.env.company.id)],
                limit=1,
            )
            runtime.setdefault("journals_by_type", {})[journal_type] = journal
        if not journal:
            journal = runtime.get("fallback_journal")
        if not journal:
            journal = self.env["account.journal"].search(
                [("company_id", "=", self.env.company.id)], limit=1
            )
            runtime["fallback_journal"] = journal
        if not journal:
            raise UserError(_("No se encontró ningún diario contable en la empresa."))
        return journal

    def _get_journal_type_for_lines(self, lineas: list, is_nomina: bool = False) -> str:
        if is_nomina:
            return "general"
        prefixes = {l["cuenta"][:3] for l in lineas if l.get("cuenta")}
        has_customer = bool(prefixes & {"430", "431", "436"})
        has_supplier = bool(prefixes & {"400", "401"})
        if has_customer and not has_supplier:
            return "sale"
        if has_supplier and not has_customer:
            return "purchase"
        return "general"

    # ── Resolución de cuentas contables ──────────────────────────────────────

    @staticmethod
    def _odoo_account_code(legacy_code: str) -> str:
        """Cuenta de Odoo (6 dígitos) de una cuenta legada: 5 primeros + "0"."""
        return str(legacy_code or "")[:ACCOUNT_PREFIX_LENGTH] + "0"

    @staticmethod
    def _partner_code_from_account(legacy_code: str) -> str:
        """Código AICIA del contacto: últimos dígitos de la cuenta legada, como número."""
        last = str(legacy_code or "")[-PARTNER_CODE_LENGTH:]
        return str(int(last)) if last.isdigit() else last

    def _get_exact_account_by_code(self, code: str, runtime: dict | None = None):
        """Busca una cuenta exacta de la empresa por su código."""
        if not code:
            return None
        if runtime is None:
            runtime = {}
        cache = runtime.setdefault("accounts_by_code", {})
        if code in cache:
            return cache[code] or None
        if runtime.get("accounts_preloaded"):
            return None
        account = self.env["account.account"].search(
            [("code", "=", code), ("company_ids", "in", [self.env.company.id])],
            limit=1,
        )
        cache[code] = account
        return account or None

    def _get_account(
        self,
        code: str,
        missing_accounts: set = None,
        account_mapping: dict = None,
        runtime: dict | None = None,
    ):
        """Cuenta Odoo para un código legado de 9 dígitos (ver _resolve_account)."""
        return self._resolve_account(
            code, missing_accounts, account_mapping, runtime=runtime
        )[0]

    def _resolve_account(
        self,
        code: str,
        missing_accounts: set = None,
        account_mapping: dict = None,
        runtime: dict | None = None,
    ):
        """Devuelve (cuenta, origen) para un código legado de 9 dígitos.

        Orden de resolución:
          1. Mapeo manual del usuario (opcional): exacto o por prefijo → "mapped".
          2. Cuenta de Odoo cuyo código son los 5 primeros dígitos más un "0"
             → "found".
          3. Si no existe, según ``missing_account_mode``:
             - "create": se crea la cuenta → "created".
             - "fallback": se usa la cuenta de reserva → "fallback".
             - "error": devuelve (None, "missing") y registra el código de
               6 dígitos en ``missing_accounts``.

        No hay cuentas colectivas, redirecciones de grupo ni búsquedas por prefijo.
        """
        if not code:
            return None, "missing"

        mapped_account = self._match_account_mapping(code, account_mapping)
        if mapped_account:
            return mapped_account, "mapped"

        account_code = self._odoo_account_code(code)
        account = self._get_exact_account_by_code(account_code, runtime=runtime)
        if account:
            return account, "found"

        if runtime is None:
            runtime = {}
        mode = self.missing_account_mode or "error"
        if mode == "create":
            account = self._create_legacy_account(account_code, runtime)
            self._count_account_origin(runtime, "created", account_code)
            return account, "created"
        if mode == "fallback" and self.fallback_account_id:
            self._count_account_origin(runtime, "fallback", account_code)
            return self.fallback_account_id, "fallback"
        if missing_accounts is not None:
            missing_accounts.add(account_code)
        return None, "missing"

    @staticmethod
    def _count_account_origin(runtime, origin, account_code):
        counts = runtime.setdefault("account_origin_counts", {})
        counts[(origin, account_code)] = counts.get((origin, account_code), 0) + 1

    @staticmethod
    def _line_name(name, origin, legacy_code):
        """En la cuenta de reserva el nombre de la línea conserva el código legado."""
        return f"[{legacy_code}] {name}" if origin == "fallback" else name

    def _guess_account_type(self, account_code, runtime):
        """Tipo contable de una cuenta nueva: el de la cuenta más parecida del plan."""
        cache = runtime.setdefault("account_type_by_prefix", {})
        Account = self.env["account.account"]
        for length in (3, 2, 1):
            prefix = account_code[:length]
            if prefix not in cache:
                reference = Account.search(
                    [
                        ("code", "=like", f"{prefix}%"),
                        ("company_ids", "in", [self.env.company.id]),
                    ],
                    order="code",
                    limit=1,
                )
                cache[prefix] = reference.account_type if reference else None
            if cache[prefix]:
                return cache[prefix]
        return "expense"

    def _create_legacy_account(self, account_code, runtime):
        """Crea la cuenta que falta en Odoo (una sola vez por código)."""
        created = runtime.setdefault("created_accounts", {})
        if account_code in created:
            return created[account_code]
        account = self.env["account.account"].create(
            {
                "code": account_code,
                "name": _("*Cuenta legada %s (revisar)") % account_code,
                "account_type": self._guess_account_type(account_code, runtime),
                "company_ids": [(4, self.env.company.id)],
            }
        )
        created[account_code] = account
        runtime.setdefault("accounts_by_code", {})[account_code] = account
        return account

    def _get_account_mapping_rules(self, runtime: dict | None = None):
        """Devuelve reglas persistentes ordenadas: exactas antes que prefijos."""
        runtime = runtime or {}
        if runtime.get("compiled_mapping_rules"):
            return runtime["compiled_mapping_rules"]
        mappings = self.env["aicia.account.importer.account.mapping"].search(
            [("target_account_id", "!=", False)]
        )
        rules = []
        for mapping in mappings:
            source_code = mapping.source_code_normalized or mapping.source_code
            if source_code:
                rules.append((source_code, mapping.target_account_id))
        compiled = self._compile_account_mapping_rules(rules)
        runtime["compiled_mapping_rules"] = compiled
        return compiled

    def _get_source_accounts_for_mapping(self, source_code: str, target_account):
        """Busca cuentas Odoo que pueden actuar como origen para un mapeo."""
        Account = self.env["account.account"]
        normalized_source = self.env[
            "aicia.account.importer.account.mapping"
        ]._normalize_source_code(source_code)
        if not normalized_source:
            return Account.browse()

        domain = [("company_ids", "in", [self.env.company.id])]
        if len(normalized_source) < ACCOUNT_CODE_LENGTH:
            domain.append(("code", "=like", f"{normalized_source}%"))
        else:
            # Código legado de 9 dígitos → cuenta de Odoo (5 primeros + "0")
            account_code = (
                normalized_source
                if len(normalized_source) == ACCOUNT_CODE_LENGTH
                else self._odoo_account_code(normalized_source)
            )
            domain.append(("code", "=", account_code))

        source_accounts = Account.search(domain)
        if target_account:
            source_accounts -= target_account
        return source_accounts

    def _match_account_mapping(self, code: str, account_mapping=None):
        if not code:
            return None

        normalized_code = self.env[
            "aicia.account.importer.account.mapping"
        ]._normalize_source_code(code)
        mapping_rules = account_mapping or self._get_account_mapping_rules()

        if isinstance(mapping_rules, dict):
            target_account = mapping_rules.get("exact", {}).get(normalized_code)
            if target_account:
                return target_account
            for source_code, target_account in mapping_rules.get("prefixes", []):
                if normalized_code.startswith(source_code):
                    _logger.debug(
                        "Cuenta '%s' redirigida a '%s' por prefijo de usuario '%s'.",
                        code,
                        target_account.code,
                        source_code,
                    )
                    return target_account
            return None

        for source_code, target_account in mapping_rules:
            if normalized_code == source_code:
                return target_account
        for source_code, target_account in mapping_rules:
            if normalized_code.startswith(source_code):
                return target_account
        return None

    # ── Resolución de contactos ──────────────────────────────────────────────

    def _resolve_partner_by_aicia_code(
        self, code: str, partner_type: str, runtime: dict | None = None
    ):
        """Devuelve el contacto que tiene ese código AICIA para ese tipo, o None.

        El código son los 4 últimos dígitos de la cuenta legada. Un contacto
        puede tener varios códigos; cada código pertenece a un único contacto
        dentro de su tipo de tercero (personal, proveedor, cliente).
        """
        code = str(code or "").strip()
        if not code or not partner_type:
            return None
        if runtime is None:
            runtime = {}
        cache = runtime.setdefault("partner_by_aicia_code", {})
        key = (partner_type, code)
        if key in cache:
            return cache[key]
        record = self.env["aicia.partner.code"].search(
            [("partner_type", "=", partner_type), ("code", "=", code)], limit=1
        )
        partner = record.partner_id or None
        cache[key] = partner
        return partner

    # ── Preparación del contexto de importación ──────────────────────────────

    def _prepare_import_runtime(self, apuntes, lineas_by_apunte, account_mapping):
        account_model = self.env["account.account"]
        accounts = account_model.search([("company_ids", "in", [self.env.company.id])])
        accounts_by_code = {account.code: account for account in accounts}

        journals = self.env["account.journal"].search(
            [("company_id", "=", self.env.company.id)]
        )
        journals_by_type = {}
        for journal in journals:
            journals_by_type.setdefault(journal.type, journal)

        project_codes = {
            str(linea["id_proyecto"])
            for lineas in lineas_by_apunte.values()
            for linea in lineas
            if linea.get("id_proyecto") is not None
        }
        analytic_by_code = {}
        if project_codes:
            # Si varias cuentas analíticas comparten código se usa la de menor id,
            # de forma determinista (en vez de la última que devuelva la búsqueda).
            analytics = self.env["account.analytic.account"].search(
                [("code", "in", sorted(project_codes))], order="id"
            )
            for analytic in analytics:
                analytic_by_code.setdefault(analytic.code, analytic)

        # Códigos AICIA de contacto presentes en el fichero: una sola búsqueda.
        partner_keys = set()
        for lineas in lineas_by_apunte.values():
            for linea in lineas:
                cuenta = linea.get("cuenta")
                partner_type = PARTNER_TYPE_BY_ACCOUNT_GROUP.get(cuenta[:3]) if cuenta else None
                if partner_type:
                    partner_keys.add(
                        (partner_type, self._partner_code_from_account(cuenta))
                    )
        partner_by_aicia_code = {key: None for key in partner_keys}
        if partner_keys:
            for record in self.env["aicia.partner.code"].search(
                [
                    ("partner_type", "in", sorted({t for t, _c in partner_keys})),
                    ("code", "in", sorted({c for _t, c in partner_keys})),
                ]
            ):
                key = (record.partner_type, record.code)
                if key in partner_by_aicia_code:
                    partner_by_aicia_code[key] = record.partner_id

        return {
            "accounts_by_code": accounts_by_code,
            "accounts_preloaded": True,
            "compiled_mapping_rules": self._compile_account_mapping_rules(account_mapping),
            "journals_by_type": journals_by_type,
            "fallback_journal": journals[:1],
            "analytic_by_code": analytic_by_code,
            "partner_by_aicia_code": partner_by_aicia_code,
            "existing_moves": self._prepare_existing_move_index(apuntes, lineas_by_apunte),
        }

    @staticmethod
    def _compile_account_mapping_rules(rules):
        if isinstance(rules, dict):
            return rules
        exact = {}
        prefixes = []
        for source_code, target_account in sorted(
            rules or [], key=lambda rule: len(rule[0]), reverse=True
        ):
            exact[source_code] = target_account
            prefixes.append((source_code, target_account))
        return {"exact": exact, "prefixes": prefixes}

    def _prepare_existing_move_index(self, apuntes, lineas_by_apunte):
        journals = self.env["account.journal"].search(
            [("company_id", "=", self.env.company.id)]
        )
        journals_by_type = {}
        for journal in journals:
            journals_by_type.setdefault(journal.type, journal)
        fallback_journal = journals[:1]
        journal_ids = set()
        for id_apunte, cabecera in apuntes.items():
            lineas = lineas_by_apunte.get(id_apunte) or []
            is_nomina = str(cabecera.get("numero_documento", "") or "").upper().startswith(
                "NO-"
            )
            journal_type = self._get_journal_type_for_lines(lineas, is_nomina=is_nomina)
            journal = journals_by_type.get(journal_type) or fallback_journal
            if journal:
                journal_ids.add(journal.id)

        if not journal_ids:
            return {}

        moves = self.env["account.move"].search_read(
            [
                ("journal_id", "in", sorted(journal_ids)),
                ("state", "in", ["draft", "posted"]),
                ("narration", "ilike", "[AICIA_IMPORT_ID:"),
            ],
            ["journal_id", "state", "narration"],
        )
        existing_moves = {}
        for move in moves:
            marker = self._extract_legacy_marker_from_narration(move.get("narration"))
            journal_data = move.get("journal_id")
            journal_id = journal_data[0] if journal_data else False
            if marker and journal_id:
                existing_moves[(journal_id, marker)] = move
        return existing_moves

    @staticmethod
    def _extract_legacy_marker_from_narration(narration):
        text = str(narration or "")
        start = text.find("[AICIA_IMPORT_ID:")
        if start == -1:
            return None
        end = text.find("]", start)
        if end == -1:
            return None
        return text[start : end + 1]

    # ── Utilidades ────────────────────────────────────────────────────────────

    def _open_workbook(self, content: bytes, label: str):
        """Abre un workbook openpyxl desde bytes; lanza UserError si falla."""
        try:
            return openpyxl.load_workbook(
                BytesIO(content), read_only=True, data_only=True
            )
        except Exception as exc:
            raise UserError(
                _("No se pudo abrir el archivo '%s': %s") % (label, str(exc))
            ) from exc

    @staticmethod
    def _legacy_import_marker(legacy_number: str) -> str:
        """Marca técnica para detectar reimportaciones sin ocupar name/ref."""
        return f"[AICIA_IMPORT_ID:{legacy_number}]"

    def _build_move_ref(self, cabecera: dict) -> str:
        """Texto visible en Referencia del asiento Odoo."""
        descripcion = str(cabecera.get("descripcion") or "").strip()
        numero_documento = str(cabecera.get("numero_documento") or "").strip()
        return descripcion or numero_documento or ""

    def _build_move_narration(self, cabecera: dict, legacy_number: str) -> str:
        """Conserva la descripción y añade la marca técnica del legado."""
        descripcion = str(cabecera.get("descripcion") or "").strip()
        numero_documento = str(cabecera.get("numero_documento") or "").strip()
        marker = self._legacy_import_marker(legacy_number)

        parts = []
        if descripcion:
            parts.append(descripcion)
        if numero_documento and numero_documento != descripcion:
            parts.append(_("Documento origen: %s") % numero_documento)
        parts.append(marker)
        return "\n".join(parts)

    @staticmethod
    def _parse_fecha_contable(value) -> date:
        """Convierte el campo Fecha_Contable del legado a datetime.date."""
        if value is None:
            return date.today()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(int(value)), "%Y%m%d").date()
        except (ValueError, TypeError):
            pass
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(str(value).strip(), fmt).date()
            except ValueError:
                continue
        _logger.warning(
            "No se pudo parsear Fecha_Contable: %s — se usa fecha de hoy.", value
        )
        return date.today()

    @staticmethod
    def _append_import_activity(activity_log: list, level: str, message: str):
        """Añade una entrada cronológica al log de importación."""
        if activity_log is None:
            return
        activity_log.append(
            {
                "time": fields.Datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "message": str(message or ""),
            }
        )

    # ── Generación del log HTML ───────────────────────────────────────────────

    def _build_log_html(
        self,
        results: list,
        missing_accounts: set = None,
        missing_partners: dict = None,
        activity_log: list = None,
        totals: dict = None,
        mismatches: list = None,
        created_accounts: dict = None,
        fallback_accounts: dict = None,
    ) -> str:
        """Genera el HTML del resumen de la importación."""
        created = [r for r in results if r["status"] == "created"]
        skipped = [r for r in results if r["status"] == "skipped"]
        errors = [r for r in results if r["status"] == "error"]
        warn_results = [r for r in results if r["status"] == "warning"]

        html = "<div style='font-family: monospace; font-size: 12px;'>"
        html += (
            "<p><strong>Resumen:</strong> "
            f"<span style='color:green'>{len(created)} creados</span> | "
            f"<span style='color:orange'>{len(skipped)} omitidos</span> | "
            f"<span style='color:#e67e00'>{len(warn_results)} con avisos (borrador)</span> | "
            f"<span style='color:red'>{len(errors)} errores</span></p>"
        )
        if totals:
            html += (
                "<p><strong>Totales importados (suma de las líneas):</strong> "
                f"Debe {totals['debe']:,.2f} € — Haber {totals['haber']:,.2f} €</p>"
            )

        # ── Actividad cronológica de importación ─────────────────────────────
        if activity_log:
            status_styles = {
                "info": ("#1f4e79", "ℹ️"),
                "success": ("green", "✅"),
                "warning": ("#e67e00", "⚠️"),
                "error": ("red", "❌"),
            }
            html += (
                "<hr/>"
                "<p><strong style='color:#1f4e79'>📋 Actividad de importación:"
                "</strong></p>"
                "<div style='max-height:360px; overflow:auto; border:1px solid #ddd; "
                "padding:8px; background:#fafafa;'>"
                "<ul style='list-style:none; padding-left:0; margin:0;'>"
            )
            for entry in activity_log:
                color, icon = status_styles.get(entry["level"], status_styles["info"])
                html += (
                    f"<li style='color:{color}; padding:2px 0;'>"
                    f"<span style='color:#777'>[{escape(entry['time'])}]</span> "
                    f"{icon} {escape(entry['message'])}</li>"
                )
            html += "</ul></div>"

        # ── Totales de cabecera que no coinciden con la suma de líneas ───────
        if mismatches:
            html += (
                "<hr/>"
                f"<p><strong style='color:#1f4e79'>🧮 Total de cabecera distinto de la "
                f"suma de líneas ({len(mismatches)} asientos — informativo: se importan "
                f"con la suma de sus líneas):</strong></p><ul>"
            )
            for m in mismatches:
                html += (
                    f"<li style='color:#1f4e79'>Nº {escape(str(m['ref']))}: "
                    f"cabecera {m['header']:,.2f} € — líneas {m['lines']:,.2f} €</li>"
                )
            html += "</ul>"

        # ── Cuentas creadas automáticamente / enviadas a la cuenta de reserva ─
        if created_accounts:
            html += (
                "<hr/>"
                f"<p><strong style='color:#7B3F00'>🆕 Cuentas creadas automáticamente "
                f"({len(created_accounts)} — revisa su nombre y tipo):</strong></p>"
                "<ul style='columns:2; column-gap:24px; list-style:none; padding:0;'>"
            )
            for code, (name, lines_count) in sorted(created_accounts.items()):
                html += (
                    f"<li style='padding:1px 0;'><code>{escape(str(code))}</code> "
                    f"<span style='color:#999; font-size:10px;'>"
                    f"({lines_count} líneas)</span></li>"
                )
            html += "</ul>"
        if fallback_accounts:
            html += (
                "<hr/>"
                f"<p><strong style='color:#7B3F00'>↪️ Cuentas inexistentes enviadas a la "
                f"cuenta de reserva ({len(fallback_accounts)}):</strong></p>"
                "<ul style='columns:2; column-gap:24px; list-style:none; padding:0;'>"
            )
            for code, lines_count in sorted(fallback_accounts.items()):
                html += (
                    f"<li style='padding:1px 0;'><code>{escape(str(code))}</code> "
                    f"<span style='color:#999; font-size:10px;'>"
                    f"({lines_count} líneas)</span></li>"
                )
            html += "</ul>"

        # ── Cuentas no encontradas ────────────────────────────────────────────
        missing = missing_accounts or set()
        if missing:
            html += (
                "<hr/>"
                f"<p><strong style='color:#8B0000'>🔍 Cuentas no encontradas en el "
                f"plan contable ({len(missing)} únicas — créalas o mapéalas antes de "
                f"reimportar):</strong></p>"
                "<ul style='columns:3; column-gap:24px; list-style:none; padding:0;'>"
            )
            for code in sorted(missing):
                html += (
                    f"<li style='color:#8B0000; padding:1px 0;'>"
                    f"<code>{escape(str(code))}</code></li>"
                )
            html += "</ul>"

        # ── Contactos no encontrados ──────────────────────────────────────────
        missing_p = missing_partners or {}
        if missing_p:
            html += (
                "<hr/>"
                f"<p><strong style='color:#7B3F00'>👤 Contactos no encontrados por código "
                f"AICIA y tipo ({len(missing_p)} únicos — sus asientos quedaron en borrador):"
                f"</strong></p>"
                "<ul style='columns:3; column-gap:24px; list-style:none; padding:0;'>"
            )
            for (ptype, ref_code), cuenta in sorted(missing_p.items()):
                html += (
                    f"<li style='color:#7B3F00; padding:2px 0;'>"
                    f"<code>{escape(str(ref_code))}</code> "
                    f"<span style='color:#999; font-size:10px;'>"
                    f"({escape(PARTNER_TYPE_LABELS.get(ptype, ptype))}, "
                    f"cta: {escape(str(cuenta))})</span>"
                    f"</li>"
                )
            html += '</ul>'

        if errors:
            html += "<hr/><p><strong style='color:red'>❌ Errores:</strong></p><ul>"
            for r in errors:
                html += f"<li style='color:red'>{escape(r['msg'])}</li>"
            html += "</ul>"

        if warn_results:
            html += (
                "<hr/><p><strong style='color:#e67e00'>"
                "⚠️ Con avisos (borrador):</strong></p><ul>"
            )
            for r in warn_results:
                html += f"<li style='color:#e67e00'>{escape(r['msg'])}</li>"
            html += "</ul>"

        if skipped:
            html += (
                "<hr/><p><strong style='color:orange'>"
                "⏭️ Omitidos (ya existían):</strong></p><ul>"
            )
            for r in skipped:
                html += f"<li style='color:orange'>{escape(r['msg'])}</li>"
            html += "</ul>"

        if created:
            html += "<hr/><p><strong style='color:green'>✅ Creados:</strong></p><ul>"
            for r in created:
                html += f"<li style='color:green'>{escape(r['msg'])}</li>"
            html += "</ul>"

        html += "</div>"
        return html
