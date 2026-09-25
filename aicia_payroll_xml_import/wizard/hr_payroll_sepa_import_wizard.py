import base64
from odoo import models, fields
from odoo.exceptions import UserError
from lxml import etree


class HrPayrollSepaImportWizard(models.TransientModel):
    _name = "hr.payroll.sepa.import.wizard"
    _description = "Importar SEPA Nóminas"

    file = fields.Binary(required=True)
    filename = fields.Char()

    log = fields.Text(readonly=True)

    @staticmethod
    def _normalize_iban(iban):
        """Normaliza IBAN para comparación: elimina espacios y convierte a mayúsculas"""
        if not iban:
            return ""
        return iban.replace(" ", "").upper()

    def _find_employee_and_partner(self, name, iban):
        """Busca empleado y partner con múltiples estrategias de fallback"""
        iban_normalized = self._normalize_iban(iban)
        search_method = ""
        
        # Intento 1: Buscar por IBAN exacto
        if iban:
            bank = self.env["res.partner.bank"].search([
                ("acc_number", "=", iban)
            ], limit=1)
            if bank and bank.partner_id:
                partner = bank.partner_id
                employee = self.env["hr.employee"].search([
                    ("partner_id", "=", partner.id)
                ], limit=1)
                if employee:
                    search_method = "por IBAN exacto"
                    return employee, partner, search_method
        
        # Intento 2: Buscar por IBAN normalizado (sin espacios)
        if iban_normalized and iban_normalized != iban:
            bank = self.env["res.partner.bank"].search([
                ("acc_number", "like", iban_normalized)
            ], limit=1)
            if bank and bank.partner_id:
                partner = bank.partner_id
                employee = self.env["hr.employee"].search([
                    ("partner_id", "=", partner.id)
                ], limit=1)
                if employee:
                    search_method = "por IBAN normalizado"
                    return employee, partner, search_method
        
        # Intento 3: Buscar empleado por nombre exacto
        if name:
            employee = self.env["hr.employee"].search([
                ("name", "=", name)
            ], limit=1)
            if employee and employee.partner_id:
                partner = employee.partner_id
                search_method = "por nombre exacto"
                return employee, partner, search_method
        
        # Intento 4: Buscar empleado por legal_name exacto
        if name:
            employee = self.env["hr.employee"].search([
                ("legal_name", "=", name)
            ], limit=1)
            if employee and employee.partner_id:
                partner = employee.partner_id
                search_method = "por legal_name exacto"
                return employee, partner, search_method
        
        # Intento 5: Buscar empleado por nombre similar (búsqueda parcial)
        if name:
            employee = self.env["hr.employee"].search([
                ("name", "ilike", name)
            ], limit=1)
            if employee and employee.partner_id:
                partner = employee.partner_id
                search_method = "por nombre similar"
                return employee, partner, search_method
        
        # Intento 6: Buscar empleado por legal_name similar
        if name:
            employee = self.env["hr.employee"].search([
                ("legal_name", "ilike", name)
            ], limit=1)
            if employee and employee.partner_id:
                partner = employee.partner_id
                search_method = "por legal_name similar"
                return employee, partner, search_method
        
        # Intento 7: Búsqueda por palabras clave (para nombres truncados)
        # Intenta diferentes combinaciones de palabras
        if name:
            words = name.split()
            # Probar diferentes combinaciones de palabras
            search_terms = []
            
            # Primero intenta palabras 1-2, luego 2-3, etc.
            for i in range(len(words) - 1):
                search_terms.append(" ".join(words[i:i+2]))
            
            # También intenta palabras individuales si hay 3+
            if len(words) >= 3:
                for i in range(1, len(words)):
                    search_terms.append(words[i])
            
            # Buscar con cada término
            for search_term in search_terms:
                if not search_term:
                    continue
                employees = self.env["hr.employee"].search([
                    "|",
                    ("name", "ilike", search_term),
                    ("legal_name", "ilike", search_term)
                ], limit=5)
                
                if employees:
                    for emp in employees:
                        if emp.partner_id:
                            partner = emp.partner_id
                            employee = emp
                            search_method = "por palabras clave"
                            return employee, partner, search_method
        
        # Sin resultados
        return False, False, "no encontrado"

    def action_import(self):
        self.ensure_one()

        log = []

        try:
            if not self.file:
                raise UserError("Debes subir un fichero XML")

            # =========================
            # DECODIFICAR XML
            # =========================
            xml_data = base64.b64decode(self.file)
            root = etree.fromstring(xml_data)

            ns = {
                "ns": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"
            }

            msg_id = root.xpath("//ns:MsgId/text()", namespaces=ns)
            msg_id = msg_id[0] if msg_id else "NO-ID"

            exec_date = root.xpath("//ns:ReqdExctnDt/text()", namespaces=ns)
            exec_date = exec_date[0] if exec_date else False

            lines_xml = root.xpath("//ns:CdtTrfTxInf", namespaces=ns)

            log.append("╔════════════════════════════════════════════════════════╗")
            log.append("║       IMPORTACIÓN SEPA - NÓMINAS                       ║")
            log.append("╚════════════════════════════════════════════════════════╝")
            log.append(f"\n📋 MessageId: {msg_id}")
            log.append(f"📊 Total de líneas XML: {len(lines_xml)}\n")

            # =========================
            # REMESA
            # =========================
            remittance = self.env["hr.payroll.sepa.remittance"].create({
                "name": msg_id,
                "msg_id": msg_id,
                "date_execution": exec_date,
            })

            # =========================
            # CONTABLE
            # =========================
            journal = self.env["account.journal"].search([
                ("type", "=", "bank")
            ], limit=1)

            if not journal:
                raise UserError("No hay diario bancario configurado")

            account_465 = self.env["account.account"].search([
                ("code", "=like", "465%")
            ], limit=1)

            if not account_465:
                raise UserError("No existe cuenta 465")

            account_572 = journal.default_account_id

            if not account_572:
                raise UserError("El diario bancario no tiene cuenta por defecto")

            move_lines = []
            total = 0.0
            
            # Listas para acumular resultados
            no_encontrados = []
            encontrados_iban = []
            encontrados_nombre = []
            
            # =========================
            # PROCESAR LÍNEAS XML
            # =========================
            for l in lines_xml:

                name = l.xpath(".//ns:Nm/text()", namespaces=ns)
                name = name[0] if name else "Empleado"

                iban = l.xpath(".//ns:CdtrAcct//ns:IBAN/text()", namespaces=ns)
                iban = iban[0] if iban else ""

                amount = float(l.xpath(".//ns:InstdAmt/text()", namespaces=ns)[0])

                end_to_end = l.xpath(".//ns:EndToEndId/text()", namespaces=ns)
                end_to_end = end_to_end[0] if end_to_end else ""

                # =========================
                # BÚSQUEDA DE EMPLEADO Y PARTNER
                # =========================
                employee, partner, search_method = self._find_employee_and_partner(name, iban)
                
                # Acumular resultados
                if employee:
                    if "IBAN" in search_method:
                        encontrados_iban.append((name, iban[:20] if iban else ""))
                    else:
                        encontrados_nombre.append((name, search_method))
                else:
                    no_encontrados.append((name, iban))

                # =========================
                # LÍNEA REMESA
                # =========================
                self.env["hr.payroll.sepa.remittance.line"].create({
                    "remittance_id": remittance.id,
                    "employee_id": employee.id if employee else False,
                    "partner_id": partner.id if partner else False,
                    "name": name,
                    "iban": iban,
                    "amount": amount,
                    "end_to_end_id": end_to_end,
                })

                move_lines.append((employee, partner, amount))
                total += amount

            # =========================
            # ASIENTO CONTABLE
            # =========================
            move_vals = {
                "move_type": "entry",
                "journal_id": journal.id,
                "date": exec_date,
                "ref": msg_id,
                "line_ids": [],
            }

            for emp, partner, amount in move_lines:
                move_vals["line_ids"].append((0, 0, {
                    "account_id": account_465.id,
                    "partner_id": partner.id if partner else False,
                    "name": emp.name if emp else "Empleado",
                    "debit": amount,
                    "credit": 0,
                }))

            move_vals["line_ids"].append((0, 0, {
                "account_id": account_572.id,
                "name": "Remesa SEPA Nóminas",
                "debit": 0,
                "credit": total,
            }))

            move = self.env["account.move"].create(move_vals)
            # move.action_post()

            # =========================
            # FINALIZAR
            # =========================
            remittance.write({
                "move_id": move.id,
                "total_amount": total,
                "state": "done",
            })

            # Generar log formateado con estadísticas
            total_procesados = len(encontrados_iban) + len(encontrados_nombre) + len(no_encontrados)
            total_encontrados = len(encontrados_iban) + len(encontrados_nombre)
            
            log.append("┌────────────────────────────────────────────────────────┐")
            log.append("│              RESUMEN DE RESULTADOS                     │")
            log.append("└────────────────────────────────────────────────────────┘")
            log.append(f"📈 Procesados: {total_procesados} | ✅ Encontrados: {total_encontrados} | ❌ No encontrados: {len(no_encontrados)}")
            log.append("")
            
            # Mostrar primero los NO ENCONTRADOS (son los importantes)
            if no_encontrados:
                log.append("┌────────────────────────────────────────────────────────┐")
                log.append("│  ❌ EMPLEADOS NO ENCONTRADOS ({})                   │".format(len(no_encontrados)))
                log.append("└────────────────────────────────────────────────────────┘")
                for name, iban in no_encontrados:
                    iban_display = iban[:25] + "..." if iban and len(iban) > 25 else (iban or "SIN IBAN")
                    log.append(f"  • {name}")
                    if iban:
                        log.append(f"    └─ IBAN: {iban_display}")
                log.append("")
            
            # Encontrados por IBAN
            if encontrados_iban:
                log.append("┌────────────────────────────────────────────────────────┐")
                log.append("│  ✅ ENCONTRADOS POR IBAN ({})                        │".format(len(encontrados_iban)))
                log.append("└────────────────────────────────────────────────────────┘")
                for name, iban_short in encontrados_iban:
                    log.append(f"  ✓ {name}")
                log.append("")
            
            # Encontrados por nombre
            if encontrados_nombre:
                log.append("┌────────────────────────────────────────────────────────┐")
                log.append("│  ✅ ENCONTRADOS POR NOMBRE ({})                     │".format(len(encontrados_nombre)))
                log.append("└────────────────────────────────────────────────────────┘")
                for name, method in encontrados_nombre:
                    log.append(f"  ✓ {name} ({method})")
                log.append("")
            
            # Resumen final
            log.append("┌────────────────────────────────────────────────────────┐")
            log.append("│  PROCESO COMPLETADO                                    │")
            log.append("└────────────────────────────────────────────────────────┘")
            log.append(f"💾 Asiento contable creado en BORRADOR")
            log.append(f"💰 Total procesado: {total:.2f} €")
            log.append(f"📦 Remesa: {msg_id}")

            self.log = "\n".join(log)

            return {
                "type": "ir.actions.act_window",
                "res_model": self._name,
                "res_id": self.id,
                "view_mode": "form",
                "target": "new",
            }

        except Exception as e:
            log.append(f"❌ ERROR: {str(e)}")

            self.log = "\n".join(log)

            return {
                "type": "ir.actions.act_window",
                "res_model": self._name,
                "res_id": self.id,
                "view_mode": "form",
                "target": "new",
            }
