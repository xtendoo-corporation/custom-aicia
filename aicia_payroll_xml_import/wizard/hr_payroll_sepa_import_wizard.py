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

            log.append("=== IMPORTACIÓN SEPA ===")
            log.append(f"✔ MessageId: {msg_id}")
            log.append(f"✔ Líneas XML: {len(lines_xml)}")

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
                # BANK → PARTNER → EMPLOYEE (CORRECTO)
                # =========================
                bank = self.env["res.partner.bank"].search([
                    ("acc_number", "=", iban)
                ], limit=1)

                partner = bank.partner_id if bank else False

                employee = self.env["hr.employee"].search([
                    ("partner_id", "=", partner.id)
                ], limit=1) if partner else False

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

            log.append("✔ Asiento creado correctamente")
            log.append(f"✔ Total: {total:.2f}")

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
