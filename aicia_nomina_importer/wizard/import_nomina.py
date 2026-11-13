
from odoo import models, fields
import base64
import re
import fitz
import io

class ImportNominaWizard(models.TransientModel):
    _name = 'aicia.nomina.import.wizard'
    _description = 'Importador de nóminas PDF'

    pdf_file = fields.Binary(required=True)
    filename = fields.Char()

    log_text = fields.Text(string="Resultado")
    processed_employees = fields.Integer(default=0)
    failed_pages = fields.Integer(default=0)
    log_html = fields.Html(string="Resultado de importación")

    def action_import(self):

        MONTHS = {
            "enero": "01",
            "febrero": "02",
            "marzo": "03",
            "abril": "04",
            "mayo": "05",
            "junio": "06",
            "julio": "07",
            "agosto": "08",
            "septiembre": "09",
            "setiembre": "09",
            "octubre": "10",
            "noviembre": "11",
            "diciembre": "12",
        }

        data = base64.b64decode(self.pdf_file)
        doc = fitz.open(stream=data, filetype='pdf')

        ok = []
        warnings = []

        total_pages = len(doc)

        for page in doc:

            text = page.get_text()

            nif = None
            m = re.search(
                r'\b([0-9XYZ][0-9]{7}[A-Z]|[0-9]{8}[A-Z])\b',
                text
            )

            if m:
                nif = m.group()

            # -------------------------
            # NOMBRE EMPLEADO DETECTADO (FIX MEJORADO)
            # -------------------------
            employee_name = None

            name_matches = re.findall(
                r'\d+\s*-\s*([A-ZÁÉÍÓÚÑ ,\.]{6,})',
                text
            )

            for candidate in name_matches:

                candidate = candidate.strip()

                if any(x in candidate for x in [
                    "ASOC", "SL", "SA", "S.L", "S.A", "COOP", "EMPRESA"
                ]):
                    continue

                candidate = re.sub(r'\.+', ' ', candidate)
                candidate = re.sub(r'\s+', ' ', candidate).strip()

                if "," in candidate:
                    parts = [p.strip() for p in candidate.split(",") if p.strip()]
                    candidate = " ".join(parts)

                if len(candidate.split()) < 2:
                    continue

                employee_name = candidate
                break

            employee = False

            # -------------------------
            # ✔ FIX: FALLBACK POR NOMBRE SI NO HAY NIF
            # -------------------------
            if nif:
                employee = self.env['hr.employee'].search(
                    [('identification_id', '=', nif)],
                    limit=1
                )

            if not employee and employee_name:
                employee = self.env['hr.employee'].search([
                    ('name', 'ilike', employee_name)
                ], limit=1)

            # -------------------------
            # ERROR SI NO ENCUENTRA EMPLEADO
            # -------------------------
            if not employee:
                warnings.append({
                    "page": page.number + 1,
                    "msg": "Empleado no encontrado",
                    "name": employee_name or "Nombre no detectado",
                    "nif": nif or "N/A"
                })
                continue

            text_lower = text.lower()

            # -------------------------
            # MES / AÑO DESDE PERIODO DE LIQUIDACION
            # -------------------------

            year = None
            month = None

            period_text = text_lower

            period_match = re.search(
                r'periodo de liquidación.*',
                text_lower,
                re.DOTALL
            )

            if period_match:
                period_text = period_match.group()

            year_match = re.search(
                r'\b(20\d{2})\b',
                period_text
            )

            if year_match:
                year = year_match.group(1)

            for k in MONTHS:
                if k in period_text:
                    month = k
                    break

            if not year:
                years = re.findall(r'\b(20\d{2})\b', text_lower)
                if years:
                    year = max(years)

            month_str = MONTHS.get(month, "XX")
            year_str = year or "XXXX"

            file_name = f'nomina_{month_str}_{year_str}.pdf'

            # -------------------------
            # ✔ NUEVO: CONTROL DE DUPLICADOS
            # -------------------------
            existing = self.env['ir.attachment'].search([
                ('name', '=', file_name),
                ('res_model', '=', 'hr.employee'),
                ('res_id', '=', employee.id),
            ], limit=1)

            if existing:
                warnings.append({
                    "page": page.number + 1,
                    "msg": "Nómina ya existente (no se vuelve a adjuntar)",
                    "name": employee_name or employee.name,
                    "nif": nif or "N/A"
                })
                continue

            pdf = fitz.open()
            pdf.insert_pdf(
                doc,
                from_page=page.number,
                to_page=page.number
            )

            attachment = self.env['ir.attachment'].create({
                'name': file_name,
                'datas': base64.b64encode(pdf.tobytes()),
                'mimetype': 'application/pdf',
                'res_model': 'hr.employee',
                'res_id': employee.id,
            })

            employee.message_post(
                body="Nómina importada automáticamente",
                attachment_ids=[attachment.id],
            )

            ok.append({
                "name": employee.name,
                "nif": nif,
                "file": file_name
            })

            pdf.close()

        # -------------------------
        # HTML BONITO
        # -------------------------

        ok_html = "".join([
            f"<li><b>{x['name']}</b> — {x['nif']} — {x['file']}</li>"
            for x in ok
        ])

        warn_html = "".join([
            f"""
            <li>
                📄 <b>Página {w['page']}</b> — {w['msg']}<br/>
                👤 Nombre: {w['name']}<br/>
                🪪 NIF/NIE: {w['nif']}
            </li>
            """
            for w in warnings
        ])

        self.log_html = f"""
        <div style="padding:10px">

            <h2>🧾 Resultado importación de nóminas</h2>

            <p><b>Total páginas:</b> {total_pages}</p>
            <p><b>Procesadas correctamente:</b> {len(ok)}</p>
            <p><b>Errores:</b> {len(warnings)}</p>

            <hr/>

            <h3 style="color:green;">✔ Empleados procesados</h3>
            <ul>{ok_html}</ul>

            <h3 style="color:orange;">⚠ Advertencias</h3>
            <ul>{warn_html}</ul>

        </div>
        """

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aicia.nomina.import.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
