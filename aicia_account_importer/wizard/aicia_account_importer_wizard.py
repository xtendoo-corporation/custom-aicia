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
#    Col 0: ID_Apunte          → clave de unión con Apuntes
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
    "id_apunte": 0,
    "cuenta": 2,
    "descripcion": 5,
    "importe": 6,
    "tipo": 7,
}


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

    # ── Estado y log ─────────────────────────────────────────────────────────
    state = fields.Selection(
        [("draft", "Borrador"), ("done", "Completado")],
        default="draft",
    )
    import_log = fields.Html(string="Log de importación", readonly=True)
    total_created = fields.Integer(string="Asientos creados", readonly=True)
    total_skipped = fields.Integer(string="Omitidos (ya existían)", readonly=True)
    total_errors = fields.Integer(string="Errores", readonly=True)

    # ── Acción principal ─────────────────────────────────────────────────────

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

        results = []
        created = skipped = errors = 0
        missing_accounts = set()  # Set local; se pasa por referencia a los métodos

        for id_apunte, cabecera in apuntes.items():
            lineas = lineas_by_apunte.get(id_apunte, [])
            if not lineas:
                results.append(
                    {
                        "status": "error",
                        "ref": str(cabecera["numero"]),
                        "msg": _(
                            "Asiento ID=%s (Nº %s) no tiene líneas contables."
                        ) % (id_apunte, cabecera["numero"]),
                    }
                )
                errors += 1
                continue

            result = self._process_asiento(cabecera, lineas, missing_accounts)
            results.append(result)
            if result["status"] == "created":
                created += 1
            elif result["status"] == "skipped":
                skipped += 1
            else:
                errors += 1

        self.write(
            {
                "state": "done",
                "total_created": created,
                "total_skipped": skipped,
                "total_errors": errors,
                "import_log": self._build_log_html(results, missing_accounts),
            }
        )
        # Reabrir el mismo wizard para mostrar el log de resultados
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

            validado = row[c["validado"]]
            anulado = row[c["anulado"]]

            if not validado:
                continue
            if self.skip_anulados and anulado:
                continue

            apuntes[id_apunte] = {
                "id": id_apunte,
                "numero": row[c["numero"]],
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
            cuenta = str(row[c["cuenta"]] or "").strip()
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

    def _process_asiento(self, cabecera: dict, lineas: list, missing_accounts: set) -> dict:
        """Crea un account.move a partir de la cabecera y sus líneas."""
        ref = str(cabecera["numero"])

        # Idempotencia: comprobar si ya existe por Numero_Apunte
        existing = self.env["account.move"].search(
            [("ref", "=", ref), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        if existing:
            return {
                "status": "skipped",
                "ref": ref,
                "msg": _(
                    "Asiento Nº %s (ID legado %s) ya existe en Odoo (ID %d). Omitido."
                ) % (ref, cabecera["id"], existing.id),
            }

        # Construir líneas del asiento
        line_vals = []
        errors = []
        for linea in lineas:
            vals, error = self._build_line_vals(linea, cabecera["descripcion"], missing_accounts)
            if error:
                errors.append(error)
            else:
                line_vals.append((0, 0, vals))

        if errors:
            return {
                "status": "error",
                "ref": ref,
                "msg": _("Asiento Nº %s — errores en líneas: %s")
                % (ref, "; ".join(errors)),
            }

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
            "name": cabecera["descripcion"] or "/",
            "date": cabecera["fecha"],
            "journal_id": self.journal_id.id,
            "line_ids": line_vals,
        }

        try:
            move = self.env["account.move"].create(move_vals)
            if self.move_state == "posted":
                move.action_post()
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

    def _build_line_vals(self, linea: dict, asiento_desc: str, missing_accounts: set) -> tuple:
        """Construye el dict de valores para una account.move.line.

        Devuelve (vals, None) si todo va bien, o (None, msg_error) si falla.
        """
        account = self._get_account(linea["cuenta"], missing_accounts)
        if not account:
            return None, _(
                "Cuenta '%s' no encontrada ni en colectivas ni en el plan contable."
            ) % linea["cuenta"]

        partner = None
        if linea["cuenta"][:3] in PARTNER_ACCOUNT_PREFIXES:
            nombre_tercero = linea["descripcion"] or asiento_desc
            partner, _error = self._resolve_partner(nombre_tercero)

        return (
            {
                "account_id": account.id,
                "partner_id": partner.id if partner else False,
                "name": linea["descripcion"] or asiento_desc or "/",
                "debit": linea["debit"],
                "credit": linea["credit"],
            },
            None,
        )

    # ── Resolución de cuentas contables ──────────────────────────────────────

    def _get_collective_prefix(self, code: str) -> str | None:
        """Devuelve el prefijo de 3 dígitos si el código tiene cuenta colectiva."""
        prefix = code[:3]
        return prefix if prefix in COLLECTIVE_ACCOUNT_MAP else None

    def _get_account(self, code: str, missing_accounts: set = None):
        """Resuelve la cuenta Odoo a partir del código legado de 9 dígitos:

        1. Prefijo colectivo (400/430/572) → devuelve/crea la cuenta colectiva.
        2. Normaliza a 6 dígitos (quitando ceros finales) y busca exacta.
        3. Busca por prefijo de 3 dígitos como último recurso.
        """
        if not code:
            return None

        prefix = self._get_collective_prefix(code)
        if prefix:
            col_code, col_name, col_type = COLLECTIVE_ACCOUNT_MAP[prefix]
            return self._get_or_create_account(col_code, col_name, col_type)

        # Normalizar código: 9 dígitos → 6 dígitos sin ceros finales
        normalized = code[:6].rstrip("0") or code[:3]
        account = self.env["account.account"].search(
            [("code", "=", normalized), ("company_ids", "in", [self.env.company.id])],
            limit=1,
        )
        if account:
            return account

        # Último recurso: buscar por prefijo de 3 dígitos
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

    def _resolve_partner(self, name: str) -> tuple:
        """Busca el partner por nombre (ilike). Crea si create_missing_partners=True.

        Devuelve (partner_o_None, msg_error_o_None).
        La descripción de la línea en el legado no es fiable como nombre de partner,
        por eso no bloqueamos el asiento si no se encuentra: se deja sin partner.
        """
        if not name:
            return None, None

        partner = self.env["res.partner"].search(
            [("name", "ilike", name)], limit=1
        )
        if partner:
            return partner, None

        if self.create_missing_partners:
            partner = self.env["res.partner"].create({"name": name})
            _logger.info(
                "Partner '%s' creado automáticamente durante la importación.", name
            )
            return partner, None

        return None, None  # Sin partner pero sin bloquear el asiento

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
        """Convierte el campo Fecha_Contable del legado a datetime.date.

        El campo viene como entero YYYYMMDD (ej: 20250103).
        También acepta datetime, date o string con separadores.
        """
        if value is None:
            return date.today()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        # Entero YYYYMMDD
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

    def _build_log_html(self, results: list, missing_accounts: set = None) -> str:
        """Genera el HTML del resumen de la importación."""
        created = [r for r in results if r["status"] == "created"]
        skipped = [r for r in results if r["status"] == "skipped"]
        errors = [r for r in results if r["status"] == "error"]

        html = "<div style='font-family: monospace; font-size: 12px;'>"
        html += (
            "<p><strong>Resumen:</strong> "
            f"<span style='color:green'>{len(created)} creados</span> | "
            f"<span style='color:orange'>{len(skipped)} omitidos</span> | "
            f"<span style='color:red'>{len(errors)} errores</span></p>"
        )

        # ── Cuentas no encontradas (resumen al inicio del log) ────────────────
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
        # ─────────────────────────────────────────────────────────────────────

        if errors:
            html += "<hr/><p><strong style='color:red'>❌ Errores:</strong></p><ul>"
            for r in errors:
                html += f"<li style='color:red'>{r['msg']}</li>"
            html += "</ul>"

        if skipped:
            html += (
                "<hr/><p><strong style='color:orange'>"
                "⚠️ Omitidos (ya existían):</strong></p><ul>"
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
