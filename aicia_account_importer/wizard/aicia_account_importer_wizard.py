# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from base64 import b64decode
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO

from odoo import _, fields, models
from odoo.exceptions import UserError

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
#    Col 9: Clase_Apunte       → no se usa en la importación
#
#  Lineas_Apunte2025.xlsx — hoja "Lineas_Apunte"  (líneas contables)
#    Col 0: Numero_Apunte      → clave real de unión con Apuntes (NO es ID_Apunte)
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
    # 572 tiene subcuentas por banco; se normaliza si la cuenta exacta no existe
    "572": ("572000", "Bancos e instituciones de crédito", "asset_cash"),
}

# Prefijos de cuentas de terceros (excluye 572 que no es partner)
PARTNER_ACCOUNT_PREFIXES = {"400", "401", "430", "431", "436"}

# Índices de columnas en cada hoja (0-based, según análisis del Excel real)
APUNTES_COLS = {
    "id": 0,
    "numero": 1,
    "fecha": 2,
    "descripcion": 4,
    "numero_documento": 5,
    "validado": 7,
    "anulado": 8,
}

LINEAS_COLS = {
    "id_apunte": 0,   # Contiene Numero_Apunte (clave real de unión, no ID_Apunte)
    "cuenta": 2,
    "descripcion": 5,
    "importe": 6,
    "tipo": 7,
}


class AiciaAccountImporterAccountMapping(models.TransientModel):
    """Línea de mapeo de cuentas: código legado → cuenta Odoo."""

    _name = "aicia.account.importer.account.mapping"
    _description = "Mapeo de cuentas para importación AICIA"

    wizard_id = fields.Many2one(
        "aicia.account.importer.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
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
    target_account_id = fields.Many2one(
        "account.account",
        string="Cuenta destino (Odoo)",
        required=False,  # required=True se aplica solo en la vista XML
    )



class AiciaAccountImporterWizard(models.TransientModel):
    _name = "aicia.account.importer.wizard"
    _description = "Importador de Apuntes Contables AICIA"

    # ── Ficheros ─────────────────────────────────────────────────────────────
    file_apuntes = fields.Binary(
        string="Apuntes2025.xlsx  (cabecera de asientos)",
        required=True,
    )
    filename_apuntes = fields.Char()
    file_lineas = fields.Binary(
        string="Lineas_Apunte2025.xlsx  (líneas contables)",
        required=True,
    )
    filename_lineas = fields.Char()

    # ── Configuración ────────────────────────────────────────────────────────
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario por defecto",
        required=True,
        domain=[("type", "in", ["general", "sale", "purchase"])],
    )
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
    account_mapping_ids = fields.One2many(
        "aicia.account.importer.account.mapping",
        "wizard_id",
        string="Mapeo de cuentas",
        help=(
            "Define aquí las cuentas del sistema legado que deben redirigirse "
            "a otra cuenta de Odoo antes de importar."
        ),
    )


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

    def action_delete_draft_moves(self):
        """Elimina todos los asientos en borrador del diario seleccionado.

        Útil para limpiar una importación fallida antes de reimportar.
        """
        self.ensure_one()
        if not self.journal_id:
            raise UserError(_("Selecciona un diario primero."))

        draft_moves = self.env["account.move"].search(
            [
                ("journal_id", "=", self.journal_id.id),
                ("state", "=", "draft"),
            ]
        )
        count = len(draft_moves)
        if not count:
            raise UserError(
                _("No hay asientos en borrador en el diario '%s'.")
                % self.journal_id.name
            )

        draft_moves.unlink()
        _logger.info(
            "Limpieza: %d borradores eliminados del diario '%s' (ID %d).",
            count,
            self.journal_id.name,
            self.journal_id.id,
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Limpieza completada"),
                "message": _(
                    "%d asientos en borrador eliminados del diario '%s'."
                ) % (count, self.journal_id.name),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": self._name,
                    "res_id": self.id,
                    "view_mode": "form",
                    "target": "new",
                },
            },
        }

    def action_import(self):
        """Punto de entrada: cruza los dos Excel y crea los account.move."""
        self.ensure_one()
        if not openpyxl:
            raise UserError(
                _("La librería 'openpyxl' no está instalada en el servidor.")
            )
        if not self.file_apuntes or not self.file_lineas:
            raise UserError(
                _("Debes subir los dos archivos Excel antes de importar.")
            )

        apuntes = self._parse_apuntes(b64decode(self.file_apuntes))
        lineas_by_apunte = self._parse_lineas(b64decode(self.file_lineas))

        # Construir diccionario de mapeo de cuentas {source_code: account_record}
        account_mapping = {
            m.source_code.strip(): m.target_account_id
            for m in self.account_mapping_ids
            if m.source_code and m.target_account_id
        }

        results = []
        created = skipped = errors = warnings = 0
        missing_accounts = set()
        missing_partners = {}

        for id_apunte, cabecera in apuntes.items():
            lineas = lineas_by_apunte.get(id_apunte, [])
            if not lineas:
                # Diagnóstico: muestra los IDs disponibles en el fichero de líneas
                ids_lineas = sorted(lineas_by_apunte.keys())
                ids_str = ", ".join(str(x) for x in ids_lineas[:20])
                if len(ids_lineas) > 20:
                    ids_str += f" … ({len(ids_lineas)} en total)"
                results.append(
                    {
                        "status": "error",
                        "ref": str(cabecera["numero"]),
                        "msg": _(
                            "Asiento ID=%s (Nº %s) no tiene líneas contables. "
                            "IDs encontrados en Lineas_Apunte: [%s]"
                        ) % (id_apunte, cabecera["numero"], ids_str or "ninguno"),
                    }
                )
                errors += 1
                continue

            result = self._process_asiento(
                cabecera, lineas, missing_accounts, missing_partners, account_mapping
            )
            results.append(result)
            if result["status"] == "created":
                created += 1
            elif result["status"] == "skipped":
                skipped += 1
            elif result["status"] == "warning":
                warnings += 1
            else:
                errors += 1

        self.write(
            {
                "state": "draft",
                "total_created": created,
                "total_skipped": skipped,
                "total_errors": errors,
                "total_warnings": warnings,
                "import_log": self._build_log_html(
                    results, missing_accounts, missing_partners
                ),
            }
        )

        # ── Poblar pestaña Cuentas con las cuentas no encontradas ────────────
        # Solo añadir las que aún no tienen fila en el mapeo (con o sin destino)
        existing_sources = {
            m.source_code.strip()
            for m in self.account_mapping_ids
            if m.source_code
        }
        new_mappings = []
        for code in sorted(missing_accounts):
            if code not in existing_sources:
                new_mappings.append(
                    (0, 0, {"wizard_id": self.id, "source_code": code})
                )
        if new_mappings:
            self.write({"account_mapping_ids": new_mappings})

        # Reabrir el mismo wizard (estado draft) para mostrar log + pestaña Cuentas
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
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
            # Normalizar a int para evitar desajustes int/float/str entre los dos Excel
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

            # Número del apunte normalizado — es la clave real de unión con Lineas_Apunte
            numero_raw = row[c["numero"]]
            try:
                numero_key = int(float(numero_raw))
            except (ValueError, TypeError):
                numero_key = str(numero_raw).strip()

            apuntes[numero_key] = {
                "id": id_apunte,
                "numero": numero_key,
                "fecha": self._parse_fecha_contable(row[c["fecha"]]),
                "descripcion": str(row[c["descripcion"]] or "").strip(),
                "numero_documento": str(row[c["numero_documento"]] or "").strip(),
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
            lineas_by_apunte[id_apunte].append(
                {
                    "cuenta": cuenta,
                    "descripcion": descripcion,
                    "debit": importe if tipo == "D" else 0.0,
                    "credit": importe if tipo == "H" else 0.0,
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
    ) -> dict:
        """Crea un account.move a partir de la cabecera y sus líneas."""
        ref = str(cabecera["numero"])

        # Idempotencia: busca SOLO en el diario de importación y excluye
        # los cancelados (pueden reimportarse sin problema).
        existing = self.env["account.move"].search(
            [
                ("ref", "=", ref),
                ("journal_id", "=", self.journal_id.id),
                ("state", "in", ["draft", "posted"]),
            ],
            limit=1,
        )
        if existing:
            state_label = {"draft": "borrador", "posted": "confirmado"}.get(
                existing.state, existing.state
            )
            return {
                "status": "skipped",
                "ref": ref,
                "msg": _(
                    "Asiento Nº %s ya existe en Odoo (ID %d, estado: %s). "
                    "Elimínalo o resetéalo a borrador para poder reimportarlo."
                ) % (ref, existing.id, state_label),
            }

        # Construir líneas del asiento
        line_vals = []
        errors = []
        line_warnings = []
        for linea in lineas:
            vals, error, warning = self._build_line_vals(
                linea, cabecera["descripcion"], missing_accounts, missing_partners,
                account_mapping,
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
                "ref": ref,
                "msg": _("Asiento Nº %s — errores en líneas: %s")
                % (ref, "; ".join(errors)),
            }
        if not line_vals:
            return {
                "status": "error",
                "ref": ref,
                "msg": _("Asiento Nº %s no generó ninguna línea válida.") % ref,
            }

        # ── Propagar partner a TODAS las líneas del mismo asiento ────────────
        # El partner se detecta en las líneas de cliente/proveedor (400/430…)
        # y se copia a las demás líneas (contrapartidas, bancos, etc.)
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
                "ref": ref,
                "msg": _(
                    "Asiento Nº %s no cuadra: Debe=%.2f Haber=%.2f (diferencia=%.2f)"
                ) % (ref, total_debe, total_haber, abs(total_debe - total_haber)),
            }

        move_vals = {
            "ref": ref,
            "date": cabecera["fecha"],
            "journal_id": self.journal_id.id,
            "line_ids": line_vals,
            "narration": cabecera["descripcion"] or "/",
        }

        try:
            move = self.env["account.move"].create(move_vals)
            # Si hay socios no resueltos → forzar borrador siempre
            if not line_warnings and self.move_state == "posted":
                move.action_post()

            if line_warnings:
                # Deduplicar refs en el mensaje del asiento
                refs_uniq = sorted({w.split("'")[1] for w in line_warnings if "'" in w})
                refs_str = ", ".join(refs_uniq) if refs_uniq else "; ".join(line_warnings)
                return {
                    "status": "warning",
                    "ref": ref,
                    "msg": _(
                        "Asiento Nº %s creado en BORRADOR (ID Odoo %d) "
                        "— socios no resueltos: %s"
                    ) % (ref, move.id, refs_str),
                }
            return {
                "status": "created",
                "ref": ref,
                "msg": _("Asiento Nº %s creado (ID Odoo %d).") % (ref, move.id),
            }
        except Exception as exc:
            return {
                "status": "error",
                "ref": ref,
                "msg": _("Error al crear asiento Nº %s: %s") % (ref, str(exc)),
            }

    def _build_line_vals(
        self,
        linea: dict,
        asiento_desc: str,
        missing_accounts: set,
        missing_partners: dict,
        account_mapping: dict = None,
    ) -> tuple:
        """Construye el dict de valores para una account.move.line."""
        account = self._get_account(linea["cuenta"], missing_accounts, account_mapping)
        if not account:
            return None, _(
                "Cuenta '%s' no encontrada ni en colectivas ni en el plan contable."
            ) % linea["cuenta"], None

        partner = None
        warning_msg = None
        if linea["cuenta"][:3] in PARTNER_ACCOUNT_PREFIXES:
            ref_code = self._partner_ref_from_account(linea["cuenta"])
            partner = self._resolve_partner(ref_code)
            if not partner:
                if self.create_missing_partners:
                    partner = self._create_partner(
                        ref_code, linea["cuenta"], linea["descripcion"]
                    )
                else:
                    warning_msg = _(
                        "Socio no encontrado para ref '%s' (cuenta legada: %s)"
                    ) % (ref_code, linea["cuenta"])
                    if missing_partners is not None:
                        missing_partners[ref_code] = linea["cuenta"]

        return (
            {
                "account_id": account.id,
                "partner_id": partner.id if partner else False,
                "name": linea["descripcion"] or asiento_desc or "/",
                "debit": linea["debit"],
                "credit": linea["credit"],
            },
            None,
            warning_msg,
        )

    # ── Resolución de cuentas contables ──────────────────────────────────────

    def _get_collective_prefix(self, code: str) -> str | None:
        """Devuelve el prefijo de 3 dígitos si el código tiene cuenta colectiva."""
        prefix = code[:3]
        return prefix if prefix in COLLECTIVE_ACCOUNT_MAP else None

    def _get_account(self, code: str, missing_accounts: set = None, account_mapping: dict = None):
        """Resuelve la cuenta Odoo a partir del código legado de 9 dígitos.

        Orden de resolución:
          0. Mapeo manual del usuario (account_mapping_ids) — tiene prioridad absoluta.
          1. Prefijo colectivo (400/430/572) → devuelve/crea la cuenta colectiva.
          2. Normaliza a 6 dígitos (quitando ceros finales) y busca exacta.
          3. Busca por prefijo de 3 dígitos como último recurso.
        """
        if not code:
            return None

        # ── 0. Mapeo manual definido por el usuario ───────────────────────────
        if account_mapping:
            normalized_for_map = code[:6].rstrip("0") or code[:3]
            for src, target_acc in account_mapping.items():
                # Coincidencia: código exacto de 9 dígitos, código normalizado,
                # o el código comienza con el prefijo indicado por el usuario.
                if (
                    code == src
                    or normalized_for_map == src
                    or code.startswith(src)
                    or normalized_for_map.startswith(src)
                ):
                    _logger.debug(
                        "Cuenta '%s' redirigida a '%s' por mapeo de usuario.",
                        code, target_acc.code,
                    )
                    return target_acc

        # ── 1. Prefijo colectivo ──────────────────────────────────────────────
        prefix = self._get_collective_prefix(code)
        if prefix:
            col_code, col_name, col_type = COLLECTIVE_ACCOUNT_MAP[prefix]
            return self._get_or_create_account(col_code, col_name, col_type)

        # ── 2. Normalizar a 6 dígitos ─────────────────────────────────────────
        normalized = code[:6].rstrip("0") or code[:3]
        account = self.env["account.account"].search(
            [("code", "=", normalized), ("company_ids", "in", [self.env.company.id])],
            limit=1,
        )
        if account:
            return account

        # ── 3. Búsqueda por prefijo de 3 dígitos ─────────────────────────────
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
        if not account and missing_accounts is not None:
            missing_accounts.add(code)
        return account

    def _get_or_create_account(self, code: str, name: str, account_type: str):
        """Obtiene la cuenta colectiva; la crea si no existe en el plan contable."""
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
        return account

    # ── Resolución de partners ────────────────────────────────────────────────

    def _partner_ref_from_account(self, code: str) -> str:
        """Construye el ref del partner a partir del código de cuenta legado de 9 dígitos.

        Los últimos 5 dígitos del código identifican al tercero en el sistema legado.
        El prefijo de letra se determina por el tipo de cuenta:
          430/431/436 → "C" (cliente)
          400/401     → "P" (proveedor)

        Nota: el módulo aicia_importer almacena el ref con prefijo "C" tanto para
        clientes como para proveedores. _resolve_partner lo tiene en cuenta.

        Ejemplos:
          "430003604" → "C03604"
          "400001234" → "P01234"
        """
        prefix = code[:3] if code else ""
        last5 = code[-5:] if len(code) >= 5 else code
        tipo = "C" if prefix in {"430", "431", "436"} else "P"
        return f"{tipo}{last5}"

    def _resolve_partner(self, ref_code: str):
        """Busca el partner en res.partner para el ref_code derivado de la cuenta legada.

        Los últimos 5 dígitos de la cuenta contable corresponden al ID del contacto
        en el sistema legado. El módulo aicia_importer almacena los partners así:
          - clientes:    campo ``codigo_cliente``  = "C{id}"  y  ``ref`` = "C{id}"
          - proveedores: campo ``codigo_proveedor`` = "C{id}"  y  ``ref`` = "C{id}"
            (el importer usa prefijo 'C' para ambos tipos de contacto)

        El campo puede o no tener los ceros de relleno del legado
        (ej: tanto "C03604" como "C3604" son válidos).

        Cadena de búsqueda (en orden, sin duplicados):
          Paso 1 — campo específico ``codigo_cliente`` ó ``codigo_proveedor``:
            · "C{digits}"     — con ceros (como guarda el importer para ambos tipos)
            · "C{id_entero}"  — sin ceros de relleno
            · "P{digits}"     — por si se importó con prefijo P
            · "P{id_entero}"  — sin ceros con prefijo P
            · solo dígitos con y sin ceros
          Paso 2 — campo estándar ``ref`` (mismo conjunto ampliado de candidatos):
            · prefijo propio con/sin ceros, prefijo contrario con/sin ceros,
              solo dígitos con y sin ceros
        """
        if not ref_code:
            return None

        tipo = ref_code[0]    # "C" o "P"
        digits = ref_code[1:]  # "03604" — últimos 5 dígitos de la cuenta
        # Versión sin ceros de relleno: "03604" → "3604", "00050" → "50"
        digits_int = str(int(digits)) if digits.isdigit() else digits.lstrip("0") or "0"
        tipo_contrario = "P" if tipo == "C" else "C"

        # Candidatos para el campo específico (preservando orden, sin duplicados)
        candidatos_especificos = list(dict.fromkeys([
            f"C{digits}",           # C03604 — prefijo C con ceros (como guarda el importer)
            f"C{digits_int}",       # C3604  — prefijo C sin ceros
            f"C{digits.zfill(6)}", # C003604 — prefijo C con 6 dígitos rellenos
            f"P{digits}",           # P03604 — por si se importó con prefijo P
            f"P{digits_int}",       # P3604  — prefijo P sin ceros
            f"P{digits.zfill(6)}", # P003604 — prefijo P con 6 dígitos rellenos
            digits,                 # 03604  — solo dígitos con ceros
            digits_int,             # 3604   — solo dígitos sin ceros
        ]))

        # Candidatos para el campo ref estándar
        candidatos_ref = list(dict.fromkeys([
            ref_code,                               # C03604 / P01234
            f"{tipo}{digits_int}",                  # C3604  / P1234
            f"{tipo}{digits.zfill(6)}",             # C003604 ← relleno 6 dígitos
            f"{tipo_contrario}{digits}",            # P03604 / C01234
            f"{tipo_contrario}{digits_int}",        # P3604  / C1234
            f"{tipo_contrario}{digits.zfill(6)}",   # P003604 / C003604
            digits,                                 # 03604  / 01234
            digits_int,                             # 3604   / 1234
        ]))

        # ── Paso 1: buscar por campo específico del contacto ─────────────────
        # El importer usa codigo_cliente para clientes y codigo_proveedor para
        # proveedores, ambos con prefijo "C" independientemente del tipo.
        campo_especifico = "codigo_cliente" if tipo == "C" else "codigo_proveedor"
        for val in candidatos_especificos:
            partner = self.env["res.partner"].search(
                [(campo_especifico, "=", val)], limit=1
            )
            if partner:
                _logger.debug(
                    "Partner encontrado por %s='%s' (ref_code='%s').",
                    campo_especifico, val, ref_code,
                )
                return partner

        # ── Paso 2: buscar por campo estándar ref (fallback) ─────────────────
        for ref in candidatos_ref:
            partner = self.env["res.partner"].search(
                [("ref", "=", ref)], limit=1
            )
            if partner:
                _logger.debug(
                    "Partner encontrado por ref='%s' (ref_code='%s').",
                    ref, ref_code,
                )
                return partner

        return None

    def _create_partner(self, ref_code: str, account_code: str, name: str):
        """Crea un partner a partir del ref_code y el código de cuenta legado.

        - Cuentas 430/431/436 → customer_rank=1
        - Cuentas 400/401    → supplier_rank=1
        - Nombre: descripción de la línea o ref_code si no hay descripción.
        """
        # Antes de crear, verificar si ya fue creado en esta misma sesión
        existing = self.env["res.partner"].search(
            [("ref", "=", ref_code)], limit=1
        )
        if existing:
            return existing

        prefix = account_code[:3] if account_code else ""
        is_customer = prefix in {"430", "431", "436"}
        is_supplier = prefix in {"400", "401"}
        vals = {
            "name": name or ref_code,
            "ref": ref_code,
            "customer_rank": 1 if is_customer else 0,
            "supplier_rank": 1 if is_supplier else 0,
        }
        partner = self.env["res.partner"].create(vals)
        _logger.info(
            "Partner '%s' (ref=%s) creado automáticamente.", vals["name"], ref_code
        )
        return partner

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

    # ── Generación del log HTML ───────────────────────────────────────────────

    def _build_log_html(
        self,
        results: list,
        missing_accounts: set = None,
        missing_partners: dict = None,
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
