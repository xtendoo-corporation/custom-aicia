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
#    Col 1: Numero_Apunte      → referencia del asiento (account.move.ref)
#    Col 2: Fecha_Contable     → entero YYYYMMDD  (ej: 20250103)
#    Col 3: Fecha_Introduccion → datetime (no se usa)
#    Col 4: Descripcion        → nombre del asiento
#    Col 5: Numero_Documento   → referencia adicional
#    Col 6: Importe_Total      → en céntimos (solo informativo)
#    Col 7: Validado           → True/False; solo se importan los True
#    Col 8: Anulado            → True/False; se omiten los True si skip_anulados
#    Col 9: Clase_Apunte       → "M" = Nómina (tratamiento especial); resto ignorado
#
#  Lineas_Apunte2025.xlsx — hoja "Lineas_Apunte"  (líneas contables)
#    Col 0: ID_Apunte          → clave de unión con Apuntes (col 0 de ambos ficheros)
#    Col 1: ID_Linea           → identificador de línea (no se usa)
#    Col 2: Cuenta_Contable    → 9 dígitos (ej: 430003604)
#    Col 3: ID_Departamento    → analítico (futuro uso)
#    Col 4: ID_Proyecto        → analítico (futuro uso)
#    Col 5: Descripcion        → descripción de la línea
#    Col 6: Importe            → entero en CÉNTIMOS (siempre positivo)
#    Col 7: Tipo_Contable      → "D" = Debe / "H" = Haber
#
#  Reglas de transformación:
#    - Todos los códigos de cuenta tienen 9 dígitos.
#      Los 3 primeros son el grupo contable; los 6 siguientes identifican
#      al tercero en el sistema legado.
#      400xxxxxx → colectiva 400000 (Proveedores)
#      430xxxxxx → colectiva 430000 (Clientes)
#      572xxxxxx → colectiva 572000 (Bancos) si la exacta no existe
#      El resto se normaliza a 6 dígitos quitando ceros finales.
#    - Los importes están en CÉNTIMOS. Se dividen entre 100.
#    - Tipo_Contable "D" → debit; "H" → credit.
#    - Clave de idempotencia: Numero_Apunte (campo ref en account.move).
#    - Solo se importan apuntes con Validado=True.
# ---------------------------------------------------------------------------

# Prefijos (3 dígitos) de cuentas de terceros → cuenta colectiva Odoo 6 dígitos
# Formato: "prefijo": ("código_colectiva", "nombre", "account_type")
COLLECTIVE_ACCOUNT_MAP = {
    "400": ("400000", "Proveedores", "liability_payable"),
    "401": ("400000", "Proveedores", "liability_payable"),
    "430": ("430000", "Clientes", "asset_receivable"),
    "431": ("430000", "Clientes", "asset_receivable"),
    "436": ("430000", "Clientes", "asset_receivable"),
}

# Prefijos de cuentas de terceros (excluye 572 que no es partner)
PARTNER_ACCOUNT_PREFIXES = {"400", "401", "430", "431", "436"}

# Prefijos de cuentas de nómina con subcuenta por empleado (prefijo "E" en ref)
# 610 → Tras resolver el empleado, la línea se reclasifica a 640XXX.
NOMINA_PARTNER_ACCOUNT_PREFIXES = {"610",}

# Índices de columnas en cada hoja (0-based, según análisis del Excel real)
APUNTES_COLS = {
    "id": 0,
    "numero": 1,
    "fecha": 2,
    "descripcion": 4,
    "numero_documento": 5,
    "validado": 7,
    "anulado": 8,
    "clase_apunte": 9,
}

LINEAS_COLS = {
    "id_apunte": 0,   # ID_Apunte — clave de unión con la cabecera (col 0 de ambos ficheros)
    "cuenta": 2,
    "id_proyecto": 4,  # ID_Proyecto → cuenta analítica (ref en account.analytic.account)
    "descripcion": 5,
    "importe": 6,
    "tipo": 7,
}


class AiciaAccountImporterAccountMapping(models.Model):
    """Línea de mapeo de cuentas: código legado → cuenta Odoo (persistente y global)."""

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
            "(ej: 478000000) o sólo el prefijo (ej: 478). "
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

    @api.model
    def _get_default_mapping_values(self):
        default_mapping_model = self.env[
            "aicia.account.importer.account.mapping.default"
        ].sudo()
        return [
            (
                self._normalize_source_code(record.source_code),
                str(record.target_account_code or "").strip(),
            )
            for record in default_mapping_model.search([], order="source_code")
            if record.source_code and record.target_account_code
        ]

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

    @api.model
    def _load_default_mappings_stats(self):
        """Carga mapeos por defecto sin sobrescribir configuraciones existentes."""
        default_mappings = self._get_default_mapping_values()
        if not default_mappings:
            return {
                "created": 0,
                "created_accounts": 0,
                "updated": 0,
                "missing_target": 0,
                "unchanged": 0,
            }

        source_codes = []
        seen_sources = set()
        target_codes = set()
        for source_code, target_code in default_mappings:
            normalized_source = self._normalize_source_code(source_code)
            if not normalized_source or normalized_source in seen_sources:
                continue
            source_codes.append(normalized_source)
            seen_sources.add(normalized_source)
            target_codes.add(target_code)

        account_by_code = {
            account.code: account
            for account in self.env["account.account"].search(
                [
                    ("code", "in", sorted(target_codes)),
                    ("company_ids", "in", [self.env.company.id]),
                ]
            )
        }
        existing_mappings = {
            mapping.source_code_normalized: mapping
            for mapping in self.search(
                [("source_code_normalized", "in", source_codes)]
            )
        }

        vals_list = []
        queued_sources = set()
        stats = {
            "created": 0,
            "created_accounts": 0,
            "updated": 0,
            "missing_target": 0,
            "unchanged": 0,
        }
        for source_code, target_code in default_mappings:
            normalized_source = self._normalize_source_code(source_code)
            if not normalized_source or normalized_source in queued_sources:
                continue

            target_account = account_by_code.get(target_code)
            mapping = existing_mappings.get(normalized_source)
            if not mapping:
                if not target_account:
                    target_account = self._create_missing_target_account(target_code)
                    account_by_code[target_code] = target_account
                    stats["created_accounts"] += 1
                vals = {"source_code": normalized_source}
                vals["target_account_id"] = target_account.id
                stats["created"] += 1
                vals_list.append(vals)
                queued_sources.add(normalized_source)
                continue

            if not target_account:
                target_account = self._create_missing_target_account(target_code)
                account_by_code[target_code] = target_account
                stats["created_accounts"] += 1

            if not mapping.target_account_id:
                mapping.write({"target_account_id": target_account.id})
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
            queued_sources.add(normalized_source)

        if vals_list:
            self.create(vals_list)
        return stats

    @api.model
    def load_default_mappings(self):
        self._load_default_mappings_stats()
        return True

    def _reload_active_wizard_mappings(self):
        """Sincroniza el M2M del wizard cuando la acción se lanza desde él."""
        wizard_id = False
        if self.env.context.get("active_model") == "aicia.account.importer.wizard":
            wizard_id = self.env.context.get("active_id")
        if not wizard_id:
            wizard_id = self.env.context.get("aicia_account_importer_wizard_id")
        if not wizard_id:
            return False

        wizard = self.env["aicia.account.importer.wizard"].browse(wizard_id).exists()
        if not wizard:
            return False

        wizard._reload_account_mapping_ids()
        return wizard

    def _guess_account_type_for_code(self, code):
        """Determina un tipo contable razonable para cuentas creadas automáticamente."""
        normalized_code = str(code or "").strip()
        prefix = normalized_code[:3]
        if prefix in COLLECTIVE_ACCOUNT_MAP:
            return COLLECTIVE_ACCOUNT_MAP[prefix][2]
        if prefix == "572":
            return "asset_cash"

        Account = self.env["account.account"]
        company_domain = [("company_ids", "in", [self.env.company.id])]
        for length in (3, 2, 1):
            if len(normalized_code) < length:
                continue
            reference = Account.search(
                company_domain + [("code", "=like", f"{normalized_code[:length]}%")],
                order="code",
                limit=1,
            )
            if reference:
                return reference.account_type
        return "expense"

    def _create_missing_target_account(self, code):
        """Crea la cuenta destino ausente para que el mapeo quede operativo."""
        normalized_code = str(code or "").strip()
        if not normalized_code:
            raise ValidationError(_("El código de la cuenta destino por defecto es inválido."))

        return self.env["account.account"].create(
            {
                "code": normalized_code,
                "name": "*Cuenta no encontrada",
                "account_type": self._guess_account_type_for_code(normalized_code),
                "company_ids": [(4, self.env.company.id)],
            }
        )

    def action_load_default_mappings(self):
        stats = self.env[
            "aicia.account.importer.account.mapping"
        ]._load_default_mappings_stats()
        wizard = self._reload_active_wizard_mappings()
        message = _(
            "Creados: %(created)d, cuentas destino creadas: %(created_accounts)d, "
            "completados: %(updated)d, sin cambios: %(unchanged)d."
        ) % {
            "created": stats["created"],
            "created_accounts": stats["created_accounts"],
            "updated": stats["updated"],
            "unchanged": stats["unchanged"],
        }
        next_action = {"type": "ir.actions.client", "tag": "reload"}
        if wizard:
            next_action = {
                "type": "ir.actions.act_window",
                "res_model": wizard._name,
                "res_id": wizard.id,
                "view_mode": "form",
                "views": [(False, "form")],
                "target": "new",
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Mapeos por defecto recargados"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": next_action,
            },
        }


class AiciaAccountImporterAccountMappingDefault(models.Model):
    """Catálogo técnico de mapeos por defecto cargado desde XML."""

    _name = "aicia.account.importer.account.mapping.default"
    _description = "Mapeos por defecto para importación AICIA"
    _rec_name = "source_code"
    _order = "source_code"

    source_code = fields.Char(required=True)
    target_account_code = fields.Char(required=True)


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
    create_missing_partners = fields.Boolean(
        string="Crear partners si no existen",
        default=True,
        help=(
            "Si está activo, crea automáticamente el partner cuando no se "
            "encuentra en Odoo. Si está inactivo, la línea queda sin partner."
        ),
    )
    skip_anulados = fields.Boolean(
        string="Omitir asientos anulados",
        default=True,
    )

    # ── Mapeo de cuentas ─────────────────────────────────────────────────────
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
        string="Con socios no resueltos (borrador)", readonly=True
    )

    # ── Acción principal ─────────────────────────────────────────────────────

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

    def action_load_default_account_mappings(self):
        """Carga los mapeos por defecto y refresca la pestaña del wizard."""
        self.ensure_one()
        stats = self.env[
            "aicia.account.importer.account.mapping"
        ]._load_default_mappings_stats()
        self._reload_account_mapping_ids()
        message = _(
            "Creados: %(created)d, cuentas destino creadas: %(created_accounts)d, "
            "completados: %(updated)d, sin cambios: %(unchanged)d."
        ) % {
            "created": stats["created"],
            "created_accounts": stats["created_accounts"],
            "updated": stats["updated"],
            "unchanged": stats["unchanged"],
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Mapeos por defecto recargados"),
                "message": message,
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

    def action_clear_account_mappings(self):
        """Borra todos los mapeos globales de cuentas AICIA."""
        self.ensure_one()
        AccountMapping = self.env["aicia.account.importer.account.mapping"]
        AccountMapping.search([]).unlink()
        self.write({"account_mapping_ids": [(5, 0, 0)]})
        return False

    def action_delete_draft_moves(self):
        """Elimina todos los asientos en borrador de los diarios de importación."""
        self.ensure_one()
        draft_moves = self.env["account.move"].search(
            [
                ("state", "=", "draft"),
                ("journal_id.type", "in", ["sale", "purchase", "general"]),
            ]
        )
        count = len(draft_moves)
        if not count:
            raise UserError(
                _("No hay asientos en borrador en los diarios de importación.")
            )
        draft_moves.unlink()
        _logger.info("Limpieza: %d borradores eliminados.", count)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Limpieza completada"),
                "message": _("%d asientos en borrador eliminados.") % count,
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

    def action_import(self):
        """Punto de entrada: cruza los dos Excel y crea los account.move."""
        self.ensure_one()
        if not self.file_apuntes and not self.file_lineas:
            return self._action_apply_account_mappings_to_existing_move_lines()
        if not self.file_apuntes or not self.file_lineas:
            raise UserError(
                _("Debes subir los dos archivos Excel antes de importar.")
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

        # Construir diccionario de mapeo de cuentas {source_code: account_record}
        account_mapping = self._get_account_mapping_rules()
        self._append_import_activity(
            activity_log,
            "info",
            _("%d reglas de mapeo de cuentas cargadas.")
            % len(account_mapping.get("prefixes", account_mapping)),
        )
        runtime = self._prepare_import_runtime(
            apuntes, lineas_by_apunte, account_mapping
        )
        results = []
        created = skipped = errors = warnings = 0
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
                ids_lineas = sorted(lineas_by_apunte.keys())
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

        AccountMapping = self.env["aicia.account.importer.account.mapping"]
        existing_sources = set(runtime.get("mapping_sources", set()))
        new_mappings = []
        for code in sorted(missing_accounts):
            norm_code = AccountMapping._normalize_source_code(code)
            if norm_code and norm_code not in existing_sources:
                new_mappings.append({"source_code": norm_code})
                existing_sources.add(norm_code)
        if new_mappings:
            created_mappings = AccountMapping.create(new_mappings)
            runtime.setdefault("mapping_sources", set()).update(
                created_mappings.mapped("source_code_normalized")
            )
            runtime.setdefault("mapping_by_source", {}).update(
                {
                    mapping.source_code_normalized: mapping
                    for mapping in created_mappings
                    if mapping.source_code_normalized
                }
            )
            self._append_import_activity(
                activity_log,
                "warning",
                _("%d cuentas no encontradas añadidas al mapeo global.")
                % len(new_mappings),
            )
        elif missing_accounts:
            self._append_import_activity(
                activity_log,
                "info",
                _("Las cuentas no encontradas ya existían en el mapeo global."),
            )

        self._reload_account_mapping_ids()
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
                "import_log": self._build_log_html(
                    results, missing_accounts, missing_partners, activity_log
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
            id_apunte = row[c["id"]]
            if id_apunte is None:
                continue
            try:
                id_apunte = int(float(id_apunte))
            except (ValueError, TypeError):
                id_apunte = str(id_apunte).strip()

            validado = row[c["validado"]]
            anulado = row[c["anulado"]]

            if not validado:
                continue
            if self.skip_anulados and anulado:
                continue

            numero_raw = row[c["numero"]]
            try:
                numero_key = int(float(numero_raw))
            except (ValueError, TypeError):
                numero_key = str(numero_raw).strip()

            # Clase_Apunte: "M" = nómina; puede estar en col 9 o ser None
            clase_raw = row[c["clase_apunte"]] if len(row) > c["clase_apunte"] else None
            clase_apunte = str(clase_raw or "").strip().upper()

            # Clave: ID_Apunte (col 0) — es la clave de unión con el fichero de líneas.
            # Numero_Apunte (col 1) se guarda en "numero" y se usa como ref del asiento en Odoo.
            apuntes[id_apunte] = {
                "id": id_apunte,
                "numero": numero_key,
                "fecha": self._parse_fecha_contable(row[c["fecha"]]),
                "descripcion": str(row[c["descripcion"]] or "").strip(),
                "numero_documento": str(row[c["numero_documento"]] or "").strip(),
                "clase_apunte": clase_apunte,
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
        """Lee Lineas_Apunte2025.xlsx y devuelve {ID_Apunte: [linea_dict, ...]}."""
        wb = self._open_workbook(content, "Lineas_Apunte2025.xlsx")
        ws = wb.worksheets[0]

        lineas_by_apunte = defaultdict(list)
        c = LINEAS_COLS
        for row in ws.iter_rows(min_row=2, values_only=True):
            id_apunte = row[c["id_apunte"]]
            if id_apunte is None:
                continue
            # Normalizar a int para que el cruce con Apuntes funcione
            # independientemente del tipo devuelto por openpyxl (int/float/str)
            try:
                id_apunte = int(float(id_apunte))
            except (ValueError, TypeError):
                id_apunte = str(id_apunte).strip()
            cuenta_raw = row[c["cuenta"]]
            if isinstance(cuenta_raw, (int, float)):
                cuenta = str(int(cuenta_raw)).zfill(9)
            else:
                cuenta = str(cuenta_raw or "").strip().zfill(9)
            importe_cents = row[c["importe"]] or 0
            tipo = str(row[c["tipo"]] or "").strip().upper()
            descripcion = str(row[c["descripcion"]] or "").strip()

            importe = round(importe_cents / 100, 2)

            # ID_Proyecto → cuenta analítica (col 4)
            id_proyecto_raw = row[c["id_proyecto"]] if len(row) > c["id_proyecto"] else None
            try:
                id_proyecto = int(float(id_proyecto_raw)) if id_proyecto_raw is not None else None
            except (ValueError, TypeError):
                id_proyecto = str(id_proyecto_raw).strip() if id_proyecto_raw else None

            lineas_by_apunte[id_apunte].append(
                {
                    "cuenta": cuenta,
                    "descripcion": descripcion,
                    "debit": importe if tipo == "D" else 0.0,
                    "credit": importe if tipo == "H" else 0.0,
                    "id_proyecto": id_proyecto,
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
        """Crea un account.move a partir de la cabecera y sus líneas."""
        legacy_number = str(cabecera["numero"])
        # ── Detectar si es un asiento de nómina ──────────────────────────────
        # Criterio: Numero_Documento empieza por "NO-" (insensible a mayúsculas)
        is_nomina = str(cabecera.get("numero_documento", "") or "").upper().startswith("NO-")

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
            nomina_tag = " 💼" if is_nomina else ""
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
                linea, cabecera["descripcion"], missing_accounts, missing_partners,
                account_mapping, is_nomina=is_nomina, runtime=runtime,
            )
            if error:
                errors.append(error)
            else:
                line_vals.append((0, 0, vals))
                if warning:
                    line_warnings.append(warning)

        nomina_tag = " 💼" if is_nomina else ""

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

        # ── Propagar partner a TODAS las líneas del mismo asiento ────────────
        partner_id_asiento = None
        for _cmd, _id, v in line_vals:
            if v.get("partner_id"):
                partner_id_asiento = v["partner_id"]
                break
        if partner_id_asiento:
            for _cmd, _id, v in line_vals:
                if not v.get("partner_id"):
                    v["partner_id"] = partner_id_asiento

        # Validar cuadre contable
        total_debe = sum(v[2]["debit"] for v in line_vals)
        total_haber = sum(v[2]["credit"] for v in line_vals)
        if abs(total_debe - total_haber) > 0.005:
            return {
                "status": "error",
                "ref": legacy_number,
                "msg": _(
                    "Asiento Nº %s%s no cuadra: Debe=%.2f Haber=%.2f (diferencia=%.2f)"
                ) % (
                    legacy_number,
                    nomina_tag,
                    total_debe,
                    total_haber,
                    abs(total_debe - total_haber),
                ),
            }

        move_vals = {
            "ref": self._build_move_ref(cabecera) or False,
            "name": "/",
            "date": cabecera["fecha"],
            "journal_id": journal.id,
            "line_ids": line_vals,
            "narration": self._build_move_narration(cabecera, legacy_number),
        }

        try:
            move = self.env["account.move"].create(move_vals)
            runtime.setdefault("existing_moves", {})[(journal.id, legacy_marker)] = move
            if not line_warnings and self.move_state == "posted":
                move.action_post()

            if line_warnings:
                refs_uniq = sorted({w.split("'")[1] for w in line_warnings if "'" in w})
                refs_str = ", ".join(refs_uniq) if refs_uniq else "; ".join(line_warnings)
                return {
                    "status": "warning",
                    "ref": legacy_number,
                    "msg": _(
                        "Asiento Nº %s%s creado en BORRADOR (ID Odoo %d) "
                        "— socios no resueltos: %s"
                    ) % (legacy_number, nomina_tag, move.id, refs_str),
                }
            return {
                "status": "created",
                "ref": legacy_number,
                "msg": _("Asiento Nº %s%s creado (ID Odoo %d).")
                % (legacy_number, nomina_tag, move.id),
            }
        except Exception as exc:
            return {
                "status": "error",
                "ref": legacy_number,
                "msg": _("Error al crear asiento Nº %s%s: %s")
                % (legacy_number, nomina_tag, str(exc)),
            }

    def _build_line_vals(
        self,
        linea: dict,
        asiento_desc: str,
        missing_accounts: set,
        missing_partners: dict,
        account_mapping: dict = None,
        is_nomina: bool = False,
        runtime: dict | None = None,
    ) -> tuple:
        """Construye el dict de valores para una account.move.line.

        Para nóminas (is_nomina=True):
          - Las cuentas se resuelven sin aplicar cuentas colectivas (640, 642, 465…
            se buscan directamente en el plan contable).
          - Si la cuenta legada es 610XXXXXX, primero se resuelve el empleado y
            después la línea se reclasifica a 640XXX, siempre con 6 dígitos.
        """
        legacy_account_code = linea["cuenta"]
        partner = None
        warning_msg = None

        if is_nomina:
            # Nóminas: partner con prefijo "E" en cuentas con subcuenta de empleado.
            if legacy_account_code[:3] in NOMINA_PARTNER_ACCOUNT_PREFIXES:
                ref_code = self._partner_ref_from_account(
                    legacy_account_code, is_nomina=True
                )
                partner = self._resolve_partner_nomina(ref_code, runtime=runtime)
                if not partner:
                    if self.create_missing_partners:
                        partner = self._create_partner(
                            ref_code, legacy_account_code, linea["descripcion"],
                            is_nomina=True, runtime=runtime,
                        )
                    else:
                        warning_msg = _(
                            "Empleado no encontrado para ref '%s' (cuenta legada: %s)"
                        ) % (ref_code, legacy_account_code)
                        if missing_partners is not None:
                            missing_partners[ref_code] = legacy_account_code
        else:
            if legacy_account_code[:3] in PARTNER_ACCOUNT_PREFIXES:
                ref_code = self._partner_ref_from_account(legacy_account_code)
                partner = self._resolve_partner(ref_code, runtime=runtime)
                if not partner:
                    if self.create_missing_partners:
                        partner = self._create_partner(
                            ref_code, legacy_account_code, linea["descripcion"], runtime=runtime
                        )
                    else:
                        warning_msg = _(
                            "Socio no encontrado para ref '%s' (cuenta legada: %s)"
                        ) % (ref_code, legacy_account_code)
                        if missing_partners is not None:
                            missing_partners[ref_code] = legacy_account_code

        account = None
        account_lookup_code = legacy_account_code
        if is_nomina:
            account = self._match_account_mapping(legacy_account_code, account_mapping)
            if not account:
                account_lookup_code = self._get_nomina_account_code_for_lookup(
                    legacy_account_code
                )

        if not account:
            if account_lookup_code != legacy_account_code:
                account = self._get_exact_account_by_code(account_lookup_code, runtime=runtime)
                if not account and missing_accounts is not None:
                    missing_accounts.add(account_lookup_code)
            else:
                account = self._get_account(
                    account_lookup_code,
                    missing_accounts,
                    account_mapping,
                    skip_collective=is_nomina,
                    runtime=runtime,
                )
        if account and account_lookup_code != legacy_account_code:
            self._register_automatic_account_mapping(
                legacy_account_code, account, runtime=runtime
            )
        if not account:
            return None, _(
                "Cuenta '%s' no encontrada ni en colectivas ni en el plan contable."
            ) % account_lookup_code, None

        # ── Distribución analítica por ID_Proyecto (100%) ────────────────────
        analytic_distribution = {}
        id_proyecto = linea.get("id_proyecto")
        if id_proyecto:
            runtime = runtime or {}
            analytic = runtime.get("analytic_by_code", {}).get(str(id_proyecto))
            if analytic is None:
                analytic = self.env["account.analytic.account"].search(
                    [("code", "=", str(id_proyecto))], limit=1
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
                "name": linea["descripcion"] or asiento_desc or "/",
                "debit": linea["debit"],
                "credit": linea["credit"],
                "analytic_distribution": analytic_distribution or False,
            },
            None,
            warning_msg,
        )

    # ── Resolución de cuentas contables ──────────────────────────────────────

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

    def _normalize_account_code_to_six_digits(self, code: str) -> str:
        """Devuelve el código contable truncado a 6 dígitos, rellenando con ceros."""
        normalized_code = str(code or "").strip().replace(" ", "")
        if not normalized_code:
            return ""
        return normalized_code[:6].ljust(6, "0")

    def _get_nomina_account_code_for_lookup(self, code: str) -> str:
        """Devuelve la cuenta contable efectiva para líneas de nómina.

        Regla especial:
          - 610XXXXXX → 640XXX, manteniendo siempre 6 dígitos.
        """
        six_digit_code = self._normalize_account_code_to_six_digits(code)
        if six_digit_code.startswith("610"):
            return f"640{six_digit_code[3:6]}"
        return code

    def _get_exact_account_by_code(self, code: str, runtime: dict | None = None):
        """Busca una cuenta exacta de la empresa sin aplicar fallback adicional."""
        if not code:
            return None
        runtime = runtime or {}
        account = runtime.get("accounts_by_code", {}).get(code)
        if account is not None:
            return account
        account = self.env["account.account"].search(
            [("code", "=", code), ("company_ids", "in", [self.env.company.id])],
            limit=1,
        )
        runtime.setdefault("accounts_by_code", {})[code] = account
        if account and code[:3] not in runtime.setdefault("accounts_by_prefix", {}):
            runtime["accounts_by_prefix"][code[:3]] = account
        return account

    def _get_collective_prefix(self, code: str) -> str | None:
        """Devuelve el prefijo de 3 dígitos si el código tiene cuenta colectiva."""
        prefix = code[:3]
        return prefix if prefix in COLLECTIVE_ACCOUNT_MAP else None

    def _normalize_account_code_for_lookup(self, code: str) -> str:
        """Normaliza el código legado para resolver la cuenta Odoo.

        Regla especial para bancos 572:
          - 572XXXXXX siempre se trunca a 572XXX (6 dígitos) para evitar
            cuentas contables de más de 6 posiciones en la conversión.

        Regla general:
          - el resto mantiene la normalización histórica del módulo, quitando
            ceros finales sobre los primeros 6 dígitos.
        """
        normalized_code = str(code or "").strip().replace(" ", "")
        if not normalized_code:
            return ""
        if normalized_code.startswith("572"):
            return normalized_code[:6]
        return normalized_code[:6].rstrip("0") or normalized_code[:3]

    def _get_account(
        self,
        code: str,
        missing_accounts: set = None,
        account_mapping: dict = None,
        skip_collective: bool = False,
        runtime: dict | None = None,
    ):
        """Resuelve la cuenta Odoo a partir del código legado de 9 dígitos.

        Orden de resolución:
          0. Mapeo manual del usuario (account_mapping_ids) — tiene prioridad absoluta.
          1. Prefijo colectivo (400/430/572) → devuelve/crea la cuenta colectiva.
             (Omitido si skip_collective=True, p.ej. en asientos de nómina)
          2. Normaliza a 6 dígitos (quitando ceros finales) y busca exacta.
          3. Busca por prefijo de 3 dígitos como último recurso.
        """
        if not code:
            return None

        # ── 0. Mapeo manual definido por el usuario ───────────────────────────
        mapped_account = self._match_account_mapping(code, account_mapping)
        if mapped_account:
            return mapped_account

        normalized = self._normalize_account_code_for_lookup(code)

        # ── 1. Subcuentas de bancos 572 → truncado exacto a 6 dígitos ─────────
        if not skip_collective and code.startswith("572"):
            account = self._get_exact_account_by_code(normalized, runtime=runtime)
            if account:
                self._register_automatic_account_mapping(code, account, runtime=runtime)
                return account

        # ── 2. Prefijo colectivo ──────────────────────────────────────────────
        # Se omite en nóminas para que 640xxxxxx → 640000 por normalización directa
        if not skip_collective:
            prefix = self._get_collective_prefix(code)
            if prefix:
                col_code, col_name, col_type = COLLECTIVE_ACCOUNT_MAP[prefix]
                account = self._get_or_create_account(
                    col_code, col_name, col_type, runtime=runtime
                )
                self._register_automatic_account_mapping(code, account, runtime=runtime)
                return account

        # ── 3. Normalizar a 6 dígitos ─────────────────────────────────────────
        account = self._get_exact_account_by_code(normalized, runtime=runtime)
        if account:
            self._register_automatic_account_mapping(code, account, runtime=runtime)
            return account

        # ── 4. Búsqueda por prefijo de 3 dígitos ─────────────────────────────
        runtime = runtime or {}
        account = runtime.get("accounts_by_prefix", {}).get(code[:3]) or None
        if account is None and "accounts_by_prefix" not in runtime:
            account = (
                self.env["account.account"].search(
                    [
                        ("code", "=like", code[:3] + "%"),
                        ("company_ids", "in", [self.env.company.id]),
                    ],
                    limit=1,
                )
                or None
            )
            runtime.setdefault("accounts_by_prefix", {})[code[:3]] = account
        if account:
            self._register_automatic_account_mapping(code, account, runtime=runtime)
        if not account and missing_accounts is not None:
            missing_accounts.add(code)
        return account

    def _register_automatic_account_mapping(
        self, source_code: str, target_account, runtime: dict | None = None
    ):
        """Persiste cambios automáticos de subcuentas para revisión futura."""
        if not source_code or not target_account:
            return

        AccountMapping = self.env["aicia.account.importer.account.mapping"]
        normalized_source = AccountMapping._normalize_source_code(source_code)
        if not normalized_source:
            return

        runtime = runtime or {}
        mapping = runtime.get("mapping_by_source", {}).get(normalized_source)
        if mapping is None and normalized_source not in runtime.get("mapping_sources", set()):
            mapping = AccountMapping.search(
                [("source_code_normalized", "=", normalized_source)], limit=1
            )
            runtime.setdefault("mapping_by_source", {})[normalized_source] = mapping
            runtime.setdefault("mapping_sources", set()).add(normalized_source)
        if not mapping:
            mapping = AccountMapping.create(
                {
                    "source_code": normalized_source,
                    "target_account_id": target_account.id,
                }
            )
            runtime.setdefault("mapping_by_source", {})[normalized_source] = mapping
            runtime.setdefault("mapping_sources", set()).add(normalized_source)
            self._store_runtime_mapping_rule(normalized_source, target_account, runtime=runtime)
            return

        if not mapping.target_account_id:
            mapping.write({"target_account_id": target_account.id})
            self._store_runtime_mapping_rule(normalized_source, target_account, runtime=runtime)

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
        if len(normalized_source) < 6:
            domain.append(("code", "=like", f"{normalized_source}%"))
        else:
            candidate_codes = {normalized_source}
            if len(normalized_source) > 6:
                candidate_codes.add(normalized_source[:6])
            domain.append(("code", "in", sorted(candidate_codes)))

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
        normalized_for_map = self._normalize_account_code_for_lookup(normalized_code)
        mapping_rules = account_mapping or self._get_account_mapping_rules()

        if isinstance(mapping_rules, dict):
            exact_rules = mapping_rules.get("exact", {})
            target_account = exact_rules.get(normalized_code) or exact_rules.get(
                normalized_for_map
            )
            if target_account:
                return target_account

            for source_code, target_account in mapping_rules.get("prefixes", []):
                if normalized_code.startswith(source_code) or normalized_for_map.startswith(
                    source_code
                ):
                    _logger.debug(
                        "Cuenta '%s' redirigida a '%s' por prefijo de usuario '%s'.",
                        code,
                        target_account.code,
                        source_code,
                    )
                    return target_account
            return None

        for source_code, target_account in mapping_rules:
            if normalized_code == source_code or normalized_for_map == source_code:
                _logger.debug(
                    "Cuenta '%s' redirigida a '%s' por mapeo exacto.",
                    code,
                    target_account.code,
                )
                return target_account

        for source_code, target_account in mapping_rules:
            if normalized_code.startswith(source_code) or normalized_for_map.startswith(
                source_code
            ):
                _logger.debug(
                    "Cuenta '%s' redirigida a '%s' por prefijo de usuario '%s'.",
                    code,
                    target_account.code,
                    source_code,
                )
                return target_account

        return None

    def _get_or_create_account(
        self, code: str, name: str, account_type: str, runtime: dict | None = None
    ):
        """Obtiene la cuenta colectiva; la crea si no existe en el plan contable."""
        runtime = runtime or {}
        account = runtime.get("accounts_by_code", {}).get(code)
        if account is None:
            account = self.env["account.account"].search(
                [("code", "=", code), ("company_ids", "in", [self.env.company.id])],
                limit=1,
            )
        if not account:
            account = self.env["account.account"].create(
                {
                    "code": code,
                    "name": name,
                    "account_type": account_type,
                    "company_ids": [(4, self.env.company.id)],
                }
            )
            _logger.info(
                "Cuenta colectiva '%s - %s' creada automáticamente.", code, name
            )
        runtime.setdefault("accounts_by_code", {})[code] = account
        runtime.setdefault("accounts_by_prefix", {}).setdefault(code[:3], account)
        return account

    # ── Resolución de partners ────────────────────────────────────────────────

    def _partner_ref_from_account(self, code: str, is_nomina: bool = False) -> str:
        """Construye el ref del partner a partir del código de cuenta legado de 9 dígitos.

        Los últimos 5 dígitos del código identifican al tercero en el sistema legado.
        El prefijo de letra se determina por el tipo de cuenta:
          430/431/436      → "C" (cliente)
          400/401          → "P" (proveedor)
          610 en nómina    → "E" (empleado)

        Ejemplos:
          "430003604" → "C03604"
          "400001234" → "P01234"
          "610001234" (nómina) → "E01234"
        """
        prefix = code[:3] if code else ""
        last5 = code[-5:] if len(code) >= 5 else code
        if is_nomina:
            tipo = "E"
        elif prefix in {"430", "431", "436"}:
            tipo = "C"
        else:
            tipo = "P"
        return f"{tipo}{last5}"

    def _resolve_partner(self, ref_code: str, runtime: dict | None = None):
        """Busca el partner en res.partner para el ref_code derivado de la cuenta legada.

        Cadena de búsqueda (en orden, sin duplicados):
          Paso 1 — campo específico ``codigo_cliente`` ó ``codigo_proveedor``.
          Paso 2 — campo estándar ``ref``.
        """
        if not ref_code:
            return None
        runtime = runtime or {}
        if ref_code in runtime.get("partner_by_ref", {}):
            return runtime["partner_by_ref"][ref_code]

        tipo = ref_code[0]    # "C" o "P"
        digits = ref_code[1:]
        digits_int = str(int(digits)) if digits.isdigit() else digits.lstrip("0") or "0"
        tipo_contrario = "P" if tipo == "C" else "C"

        candidatos_especificos = list(dict.fromkeys([
            f"C{digits}", f"C{digits_int}", f"C{digits.zfill(6)}",
            f"P{digits}", f"P{digits_int}", f"P{digits.zfill(6)}",
            digits, digits_int,
        ]))
        candidatos_ref = list(dict.fromkeys([
            ref_code,
            f"{tipo}{digits_int}",
            f"{tipo}{digits.zfill(6)}",
            f"{tipo_contrario}{digits}",
            f"{tipo_contrario}{digits_int}",
            f"{tipo_contrario}{digits.zfill(6)}",
            digits, digits_int,
        ]))

        campo_especifico = "codigo_cliente" if tipo == "C" else "codigo_proveedor"
        partner_model = self.env["res.partner"]
        if campo_especifico in partner_model._fields:
            for val in candidatos_especificos:
                partner = partner_model.search(
                    [(campo_especifico, "=", val)], limit=1
                )
                if partner:
                    _logger.debug(
                        "Partner encontrado por %s='%s' (ref_code='%s').",
                        campo_especifico, val, ref_code,
                    )
                    runtime.setdefault("partner_by_ref", {})[ref_code] = partner
                    return partner

        for ref in candidatos_ref:
            partner = partner_model.search([("ref", "=", ref)], limit=1)
            if partner:
                _logger.debug(
                    "Partner encontrado por ref='%s' (ref_code='%s').", ref, ref_code
                )
                runtime.setdefault("partner_by_ref", {})[ref_code] = partner
                return partner

        runtime.setdefault("partner_by_ref", {})[ref_code] = None
        return None

    def _resolve_partner_nomina(self, ref_code: str, runtime: dict | None = None):
        """Busca el partner del empleado via hr.employee.codigo_empleado.

        Construye candidatos a partir del código (prefijo "E" + últimos 5 dígitos),
        busca en hr.employee por campo ``codigo_empleado`` y devuelve el
        res.partner asociado al empleado (employee.partner_id / address_home_id).

        Candidatos de búsqueda:
          E03604, E3604, E003604, 03604, 3604
        """
        if not ref_code:
            return None
        runtime = runtime or {}
        if ref_code in runtime.get("nomina_partner_by_ref", {}):
            return runtime["nomina_partner_by_ref"][ref_code]

        digits = ref_code[1:]  # últimos 5 dígitos de la cuenta
        digits_int = str(int(digits)) if digits.isdigit() else digits.lstrip("0") or "0"

        candidatos = list(dict.fromkeys([
            ref_code,                   # E03604
            f"E{digits_int}",           # E3604
            f"E{digits.zfill(6)}",      # E003604
            digits,                     # 03604
            digits_int,                 # 3604
        ]))

        # ── Buscar primero en hr.employee por codigo_empleado ─────────────────
        if self.env.registry.models.get("hr.employee"):
            Employee = self.env["hr.employee"]
            for cand in candidatos:
                employee = Employee.search(
                    [("codigo_empleado", "=", cand)], limit=1
                )
                if employee:
                    partner = self._get_employee_partner(employee)
                    if partner:
                        _logger.debug(
                            "Empleado encontrado por codigo_empleado='%s' → partner ID %d.",
                            cand, partner.id,
                        )
                        runtime.setdefault("nomina_partner_by_ref", {})[ref_code] = partner
                        return partner
                    _logger.debug(
                        "Empleado encontrado por codigo_empleado='%s' pero sin partner asociado.",
                        cand,
                    )
                    runtime.setdefault("nomina_partner_by_ref", {})[ref_code] = None
                    return None

        # ── Fallback: buscar en res.partner por campo ref ─────────────────────
        for cand in candidatos:
            partner = self.env["res.partner"].search(
                [("ref", "=", cand)], limit=1
            )
            if partner:
                _logger.debug(
                    "Empleado encontrado por ref='%s' (ref_code='%s').", cand, ref_code
                )
                runtime.setdefault("nomina_partner_by_ref", {})[ref_code] = partner
                return partner
        runtime.setdefault("nomina_partner_by_ref", {})[ref_code] = None
        return None

    def _get_employee_partner(self, employee):
        """Devuelve el partner asociado usando los campos disponibles en la versión."""
        for field_name in (
            "partner_id",
            "work_contact_id",
            "address_home_id",
            "private_address_id",
            "home_address_id",
        ):
            if field_name in getattr(employee, "_fields", {}):
                partner = getattr(employee, field_name)
                if partner:
                    return partner
        return None

    def _create_partner(
        self,
        ref_code: str,
        account_code: str,
        name: str,
        is_nomina: bool = False,
        runtime: dict | None = None,
    ):
        """Crea un partner a partir del ref_code y el código de cuenta legado.

        - Cuentas 430/431/436 → customer_rank=1
        - Cuentas 400/401    → supplier_rank=1
        - Nómina (is_nomina) → sin customer_rank ni supplier_rank (empleado)
        - Nombre: descripción de la línea o ref_code si no hay descripción.
        """
        runtime = runtime or {}
        cached_partner = runtime.get("partner_by_ref", {}).get(ref_code)
        if cached_partner:
            return cached_partner
        existing = self.env["res.partner"].search([("ref", "=", ref_code)], limit=1)
        if existing:
            runtime.setdefault("partner_by_ref", {})[ref_code] = existing
            return existing

        prefix = account_code[:3] if account_code else ""
        is_customer = not is_nomina and prefix in {"430", "431", "436"}
        is_supplier = not is_nomina and prefix in {"400", "401"}
        vals = {
            "name": name or ref_code,
            "ref": ref_code,
            "customer_rank": 1 if is_customer else 0,
            "supplier_rank": 1 if is_supplier else 0,
        }
        partner = self.env["res.partner"].create(vals)
        tipo_label = "Empleado" if is_nomina else "Partner"
        _logger.info(
            "%s '%s' (ref=%s) creado automáticamente.", tipo_label, vals["name"], ref_code
        )
        runtime.setdefault("partner_by_ref", {})[ref_code] = partner
        if is_nomina:
            runtime.setdefault("nomina_partner_by_ref", {})[ref_code] = partner
        return partner

    def _prepare_import_runtime(self, apuntes, lineas_by_apunte, account_mapping):
        account_model = self.env["account.account"]
        accounts = account_model.search([("company_ids", "in", [self.env.company.id])])
        accounts_by_code = {account.code: account for account in accounts}
        accounts_by_prefix = {}
        for account in accounts:
            accounts_by_prefix.setdefault(account.code[:3], account)

        mapping_model = self.env["aicia.account.importer.account.mapping"]
        mappings = mapping_model.search([])
        mapping_by_source = {
            mapping.source_code_normalized: mapping
            for mapping in mappings
            if mapping.source_code_normalized
        }
        mapping_sources = set(mapping_by_source)

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
            if linea.get("id_proyecto")
        }
        analytic_by_code = {}
        if project_codes:
            analytics = self.env["account.analytic.account"].search(
                [("code", "in", sorted(project_codes))]
            )
            analytic_by_code = {analytic.code: analytic for analytic in analytics}

        return {
            "accounts_by_code": accounts_by_code,
            "accounts_by_prefix": accounts_by_prefix,
            "mapping_by_source": mapping_by_source,
            "mapping_sources": mapping_sources,
            "compiled_mapping_rules": self._compile_account_mapping_rules(account_mapping),
            "journals_by_type": journals_by_type,
            "fallback_journal": journals[:1],
            "analytic_by_code": analytic_by_code,
            "partner_by_ref": {},
            "nomina_partner_by_ref": {},
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

    def _store_runtime_mapping_rule(
        self, source_code, target_account, runtime: dict | None = None
    ):
        runtime = runtime or {}
        compiled = runtime.get("compiled_mapping_rules")
        if not compiled or not source_code or not target_account:
            return
        compiled.setdefault("exact", {})[source_code] = target_account
        prefixes = [rule for rule in compiled.get("prefixes", []) if rule[0] != source_code]
        prefixes.append((source_code, target_account))
        compiled["prefixes"] = sorted(prefixes, key=lambda rule: len(rule[0]), reverse=True)

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
            f"<span style='color:#e67e00'>{len(warn_results)} con socios no resueltos (borrador)</span> | "
            f"<span style='color:red'>{len(errors)} errores</span></p>"
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

        # ── Cuentas no encontradas ────────────────────────────────────────────
        missing = missing_accounts or set()
        if missing:
            html += (
                "<hr/>"
                f"<p><strong style='color:#8B0000'>🔍 Cuentas no encontradas en el "
                f"plan contable ({len(missing)} únicas — créalas antes de reimportar):"
                f"</strong></p>"
                "<ul style='columns:3; column-gap:24px; list-style:none; padding:0;'>"
            )
            for code in sorted(missing):
                html += (
                    f"<li style='color:#8B0000; padding:1px 0;'>"
                    f"<code>{code}</code></li>"
                )
            html += "</ul>"

        # ── Socios no encontrados ─────────────────────────────────────────────
        missing_p = missing_partners or {}
        if missing_p:
            html += (
                "<hr/>"
                f"<p><strong style='color:#7B3F00'>👤 Socios no encontrados por ref "
                f"({len(missing_p)} únicos — sus asientos quedaron en borrador):"
                f"</strong></p>"
                "<ul style='columns:3; column-gap:24px; list-style:none; padding:0;'>"
            )
            for ref_code, cuenta in sorted(missing_p.items()):
                html += (
                    f"<li style='color:#7B3F00; padding:2px 0;'>"
                    f"<code>{ref_code}</code>"
                    f"<span style='color:#999; font-size:10px;'> (cta: {cuenta})</span>"
                    f"</li>"
                )
            html += '</ul>'
        # ─────────────────────────────────────────────────────────────────────

        if errors:
            html += "<hr/><p><strong style='color:red'>❌ Errores:</strong></p><ul>"
            for r in errors:
                html += f"<li style='color:red'>{r['msg']}</li>"
            html += "</ul>"

        if warn_results:
            html += (
                "<hr/><p><strong style='color:#e67e00'>"
                "⚠️ Con socios no resueltos (borrador):</strong></p><ul>"
            )
            for r in warn_results:
                html += f"<li style='color:#e67e00'>{r['msg']}</li>"
            html += "</ul>"

        if skipped:
            html += (
                "<hr/><p><strong style='color:orange'>"
                "⏭️ Omitidos (ya existían):</strong></p><ul>"
            )
            for r in skipped:
                html += f"<li style='color:orange'>{r['msg']}</li>"
            html += "</ul>"

        if created:
            html += "<hr/><p><strong style='color:green'>✅ Creados:</strong></p><ul>"
            for r in created:
                html += f"<li style='color:green'>{r['msg']}</li>"
            html += "</ul>"

        html += "</div>"
        return html
