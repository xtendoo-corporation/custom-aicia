# Copyright 2024 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# Wizard para importar nóminas desde CSV en AICIA siguiendo agents.md

import logging
import csv
from base64 import b64decode
from io import StringIO
from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AiciaImporterPayrollWizard(models.TransientModel):
    _name = "aicia.importer.payroll.wizard"
    _description = "Importador de Nóminas AICIA"

    data_file_payroll = fields.Binary(
        string="Archivo de Nóminas (CSV)",
        help="Seleccione el archivo CSV con las nóminas a importar.",
    )
    filename_payroll = fields.Char(string="Nombre del archivo de nóminas")

    state = fields.Selection(
        [('draft', 'Borrador'), ('done', 'Completado')],
        string="Estado",
        default='draft',
    )
    import_log = fields.Html(
        string="Log de Importación",
        readonly=True,
    )
    total_processed = fields.Integer(string="Total Procesados", readonly=True)
    total_errors = fields.Integer(string="Total Errores", readonly=True)

    def import_payroll(self):
        """
        Procesa el archivo CSV de nóminas, imprime los datos y el reparto analítico de cada empleado (analytic_line_ids), y genera un log.
        Antes de procesar, valida que todos los empleados tengan reparto analítico. Si falta reparto en alguno, muestra error y detiene la ejecución.
        Si ocurre un error al crear algún asiento, se hace rollback de todos los asientos creados en esta importación y se muestra el error en el log.
        """
        self.ensure_one()
        if not self.data_file_payroll:
            raise UserError(_("Por favor, seleccione un archivo CSV para importar."))
        decoded = b64decode(self.data_file_payroll)
        csvfile = StringIO(decoded.decode('utf-8', errors='replace'))
        reader = csv.reader(csvfile, delimiter='\t')
        # --- Validación previa: comprobar que todos los empleados tienen reparto analítico ---
        header_found = False
        header = []
        empleados_csv = []
        for row in reader:
            if not header_found and any('FECHA' in c for c in row):
                header = row
                header_found = True
                continue
            if not header_found:
                continue
            if not any(cell.strip() for cell in row):
                continue
            empleado = dict(zip(header, row))
            empleados_csv.append(empleado)
        # Buscar empleados en Odoo y comprobar reparto y suma de porcentajes
        Employee = self.env['hr.employee']
        empleados_sin_reparto = []
        empleados_porcentaje_incorrecto = []
        for empleado in empleados_csv:
            nif = empleado.get('NIF', '').strip()
            if nif:
                emp = Employee.search([('identification_id', '=', nif)], limit=1)
                if emp:
                    if not emp.analytic_line_ids:
                        empleados_sin_reparto.append(f"<li style='color:red;'>Empleado {empleado.get('Nombre','')} (NIF: {nif}) no tiene reparto analítico</li>")
                    else:
                        suma = sum((line.percentage or 0.0) for line in emp.analytic_line_ids)
                        if round(suma, 2) != 100.00:
                            empleados_porcentaje_incorrecto.append(f"<li style='color:red;'>Empleado {empleado.get('Nombre','')} (NIF: {nif}) suma porcentaje reparto: {suma:.2f}%</li>")
        if empleados_sin_reparto or empleados_porcentaje_incorrecto:
            # Mostrar error en el log y detener ejecución
            log_html = "<b>Importación detenida:</b>"
            if empleados_sin_reparto:
                log_html += "<br/>Los siguientes empleados no tienen reparto analítico:<ul>" + "\n".join(empleados_sin_reparto) + "</ul>"
            if empleados_porcentaje_incorrecto:
                log_html += "<br/>Los siguientes empleados tienen un reparto analítico cuya suma de porcentajes no es 100:<ul>" + "\n".join(empleados_porcentaje_incorrecto) + "</ul>"
            self.write({
                'state': 'done',
                'import_log': log_html,
                'total_processed': 0,
                'total_errors': len(empleados_sin_reparto) + len(empleados_porcentaje_incorrecto),
            })
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'aicia.importer.payroll.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
                'context': self.env.context,
            }
        # --- Si todos tienen reparto, procesar normalmente ---
        # Volver a abrir el CSV para procesar desde el principio
        csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter='\t')
        processed = 0
        errors = 0
        log_lines = []
        header_found = False
        header = []
        created_moves = []
        try:
            for row in reader:
                if not header_found and any('FECHA' in c for c in row):
                    header = row
                    header_found = True
                    continue
                if not header_found:
                    continue  # Saltar líneas previas
                if not any(cell.strip() for cell in row):
                    continue  # Saltar filas vacías
                empleado = dict(zip(header, row))
                print(f"Empleado: {empleado}")
                nif = empleado.get('NIF', '').strip()
                if nif:
                    emp = Employee.search([('identification_id', '=', nif)], limit=1)
                    if emp:
                        print(f"  Reparto analítico para {nif} ({empleado.get('Nombre','')}):")
                        # Parsear el campo LIQUIDO (puede venir con coma como decimal)
                        liquido_str = empleado.get('LIQUIDO', '0').replace(',', '.').strip()
                        try:
                            liquido = float(liquido_str)
                        except Exception:
                            liquido = 0.0
                        for line in emp.analytic_line_ids:
                            # Calculamos el importe proporcional: LIQUIDO * (porcentaje / 100), con dos decimales
                            porcentaje = line.percentage or 0.0
                            importe = liquido * (porcentaje / 100.0)
                            # Mostramos los campos principales del reparto, incluyendo el importe calculado
                            print(f"    Cuenta: {line.analytic_account_id.name if line.analytic_account_id else '-'} | Porcentaje: {porcentaje}% | Importe: {importe:.2f}")
                        if not emp.analytic_line_ids:
                            print("    [Sin reparto analítico]")
                        # --- Crear asiento contable (account.move) en borrador ---
                        journal = self.env['account.journal'].search([('code', '=', 'NOM')], limit=1)
                        account_gasto = self.env['account.account'].search([('code', '=', '640000')], limit=1)
                        account_pago = self.env['account.account'].search([('code', '=', '465000')], limit=1)
                        if not journal or not account_gasto or not account_pago:
                            raise UserError(_('No se encuentra el diario "NOMINA" o las cuentas "640000"/"465000".'))
                        # Comprobar si el campo address_home_id existe en hr.employee
                        partner_id = False
                        if 'address_home_id' in emp._fields:
                            partner_id = emp.address_home_id.id if emp.address_home_id else False
                        move_vals = {
                            'journal_id': journal.id,
                            'date': fields.Date.today(),
                            'ref': f"Nómina {empleado.get('Nombre','')} {empleado.get('NIF','')}",
                            'state': 'draft',
                            'line_ids': [
                                (0, 0, {
                                    'account_id': account_gasto.id,
                                    'name': f"Nómina {empleado.get('Nombre','')}",
                                    'debit': liquido,
                                    'credit': 0.0,
                                    'partner_id': partner_id,
                                }),
                                (0, 0, {
                                    'account_id': account_pago.id,
                                    'name': f"Pago nómina {empleado.get('Nombre','')}",
                                    'debit': 0.0,
                                    'credit': liquido,
                                    'partner_id': partner_id,
                                }),
                            ],
                        }
                        move = self.env['account.move'].create(move_vals)
                        created_moves.append(move.id)
                        move_url = f"/web#id={move.id}&model=account.move&view_type=form"
                        log_lines.append(f"<li><b>{empleado.get('NIF','')} - {empleado.get('Nombre','')}</b> - Asiento creado: <a href='{move_url}' target='_blank'>{move.name}</a> - Importe: {liquido:.2f} €</li>")
                    else:
                        print(f"  [Empleado con NIF {nif} no encontrado en Odoo]")
                        log_lines.append(f"<li style='color:red;'>Empleado con NIF {nif} no encontrado en Odoo</li>")
                else:
                    print("  [NIF no presente en la fila]")
                    log_lines.append(f"<li style='color:red;'>NIF no presente en la fila: {empleado}</li>")
                processed += 1
        except Exception as e:
            # Rollback: borrar todos los asientos creados en esta importación
            if created_moves:
                self.env['account.move'].browse(created_moves).unlink()
            errors += 1
            log_lines.append(f"<li style='color:red;'>Error crítico: {str(e)}. Se ha hecho rollback de todos los asientos creados en esta importación.</li>")
        resumen = f"<b>Procesados:</b> {processed} <br/><b>Errores:</b> {errors}"
        log_html = resumen + "<ul>" + "\n".join(log_lines) + "</ul>"
        self.write({
            'state': 'done',
            'import_log': log_html,
            'total_processed': processed,
            'total_errors': errors,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aicia.importer.payroll.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

