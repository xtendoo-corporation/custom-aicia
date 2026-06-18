import logging
from base64 import b64decode
from io import BytesIO
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import openpyxl
except ImportError:
    _logger.warning("openpyxl library not installed. Please install it to use this module.")
    openpyxl = None


class AiciaImporterWizard(models.TransientModel):
    _name = "aicia.importer.wizard"
    _description = "Importador de Proveedores y Clientes AICIA"

    # Mapeo de códigos de provincia
    PROVINCE_MAP = {
        '1': 'ALAVA',
        '2': 'ALBACETE',
        '3': 'ALACANT/ALICANTE',
        '4': 'ALMERIA',
        '5': 'AVILA',
        '6': 'BADAJOZ',
        '7': 'ILLES BALEARS',
        '8': 'BARCELONA',
        '9': 'BURGOS',
        '10': 'CACERES',
        '11': 'CADIZ',
        '12': 'CASTELLON DE LA PLANA',
        '13': 'CIUDAD REAL',
        '14': 'CORDOBA',
        '15': 'A CORUÑA',
        '16': 'CUENCA',
        '17': 'GIRONA',
        '18': 'GRANADA',
        '19': 'GUADALAJARA',
        '20': 'GUIPUZCOA',
        '21': 'HUELVA',
        '22': 'HUESCA',
        '23': 'JAEN',
        '24': 'LEON',
        '25': 'LLEIDA',
        '26': 'LA RIOJA',
        '27': 'LUGO',
        '28': 'MADRID',
        '29': 'MALAGA',
        '30': 'MURCIA',
        '31': 'NAFARROA/NAVARRA',
        '32': 'OURENSE',
        '33': 'ASTURIAS',
        '34': 'PALENCIA',
        '35': 'LAS PALMAS',
        '36': 'PONTEVEDRA',
        '37': 'SALAMANCA',
        '38': 'STA. CRUZ TENERIFE',
        '39': 'CANTABRIA',
        '40': 'SEGOVIA',
        '41': 'SEVILLA',
        '42': 'SORIA',
        '43': 'TARRAGONA',
        '44': 'TERUEL',
        '45': 'TOLEDO',
        '46': 'VALENCIA',
        '47': 'VALLADOLID',
        '48': 'VIZCAYA',
        '49': 'ZAMORA',
        '50': 'ZARAGOZA',
        '51': 'CEUTA',
        '52': 'MELILLA',
    }

    data_file_suppliers = fields.Binary(
        string="Archivo de Proveedores",
        help="Seleccione el archivo Excel con los proveedores a importar.",
    )
    filename_suppliers = fields.Char(string="Nombre del archivo de proveedores")

    data_file_customers = fields.Binary(
        string="Archivo de Clientes",
        help="Seleccione el archivo Excel con los clientes a importar.",
    )
    filename_customers = fields.Char(string="Nombre del archivo de clientes")

    data_file_employees = fields.Binary(
        string="Archivo de Personal",
        help="Seleccione el archivo Excel con el personal a importar.",
    )
    filename_employees = fields.Char(string="Nombre del archivo de personal")

    data_file_projects = fields.Binary(
        string="Archivo de Proyectos",
        help="Seleccione el archivo Excel con los proyectos a importar.",
    )
    filename_projects = fields.Char(string="Nombre del archivo de proyectos")

    data_file_project_assignments = fields.Binary(
        string="Archivo de Asignación de Proyectos",
        help="Seleccione el archivo Excel con la relación entre proyectos y empleados.",
    )
    filename_project_assignments = fields.Char(string="Nombre del archivo de asignaciones")

    update_existing = fields.Boolean(
        string="Actualizar existentes",
        default=False,
        help="Si está marcado, actualiza los contactos existentes. Si no, solo crea nuevos.",
    )

    # Campos para mostrar el resultado de la importación
    state = fields.Selection(
        [('draft', 'Borrador'), ('done', 'Completado')],
        string="Estado",
        default='draft',
    )
    import_log = fields.Html(
        string="Log de Importación",
        readonly=True,
    )
    total_created = fields.Integer(string="Total Creados", readonly=True)
    total_updated = fields.Integer(string="Total Actualizados", readonly=True)
    total_errors = fields.Integer(string="Total Errores", readonly=True)

    def import_suppliers(self):
        """Procesa los archivos Excel e importa proveedores y/o clientes."""
        self.ensure_one()

        if not openpyxl:
            raise UserError(
                _("La librería 'openpyxl' no está instalada. "
                  "Por favor, instálela con: pip install openpyxl")
            )

        if not self.data_file_suppliers and not self.data_file_customers and not self.data_file_employees and not self.data_file_projects and not self.data_file_project_assignments:
            raise UserError(_("Por favor, seleccione al menos un archivo para importar."))

        _logger.info("=" * 80)
        _logger.info("INICIO DE IMPORTACIÓN AICIA")
        _logger.info("=" * 80)

        # Crear mapeo de provincias desde el diccionario interno
        _logger.info(">>> Cargando mapeo de provincias")
        province_map = self._get_province_mapping()
        _logger.info(f">>> PROVINCIAS: {len(province_map)} códigos mapeados")

        total_created = 0
        total_updated = 0
        total_errors = 0
        all_errors = []
        import_types = []  # Para rastrear qué tipos de archivos se importaron

        # Importar proveedores si se proporciona el archivo
        if self.data_file_suppliers:
            _logger.info(">>> Iniciando importación de PROVEEDORES")
            result = self._import_file(self.data_file_suppliers, is_supplier=True, province_map=province_map)
            total_created += result['created']
            total_updated += result['updated']
            total_errors += result['errors']
            all_errors.extend([f"[Proveedores] {e}" for e in result['error_list']])
            import_types.append('suppliers')
            _logger.info(f">>> PROVEEDORES: {result['created']} creados, {result['updated']} actualizados, {result['errors']} errores")

        # Importar clientes si se proporciona el archivo
        if self.data_file_customers:
            _logger.info(">>> Iniciando importación de CLIENTES")
            result = self._import_file(self.data_file_customers, is_supplier=False, province_map=province_map)
            total_created += result['created']
            total_updated += result['updated']
            total_errors += result['errors']
            all_errors.extend([f"[Clientes] {e}" for e in result['error_list']])
            import_types.append('customers')
            _logger.info(f">>> CLIENTES: {result['created']} creados, {result['updated']} actualizados, {result['errors']} errores")

        # Importar personal si se proporciona el archivo
        if self.data_file_employees:
            _logger.info(">>> Iniciando importación de PERSONAL")
            result = self._import_employees(self.data_file_employees, province_map=province_map)
            total_created += result['created']
            total_updated += result['updated']
            total_errors += result['errors']
            all_errors.extend([f"[Personal] {e}" for e in result['error_list']])
            import_types.append('employees')
            _logger.info(f">>> PERSONAL: {result['created']} creados, {result['updated']} actualizados, {result['errors']} errores")

        # Importar proyectos si se proporciona el archivo
        if self.data_file_projects:
            _logger.info(">>> Iniciando importación de PROYECTOS")
            result = self._import_projects(self.data_file_projects)
            total_created += result['created']
            total_updated += result['updated']
            total_errors += result['errors']
            all_errors.extend([f"[Proyectos] {e}" for e in result['error_list']])
            import_types.append('projects')
            _logger.info(f">>> PROYECTOS: {result['created']} creados, {result['updated']} actualizados, {result['errors']} errores")

        # Importar asignaciones de proyectos si se proporciona el archivo
        if self.data_file_project_assignments:
            _logger.info(">>> Iniciando importación de ASIGNACIONES DE PROYECTOS")
            result = self._import_project_assignments(self.data_file_project_assignments)
            total_created += result['created']
            total_updated += result['updated']
            total_errors += result['errors']
            all_errors.extend([f"[Asignaciones] {e}" for e in result['error_list']])
            import_types.append('project_assignments')
            _logger.info(f">>> ASIGNACIONES: {result['created']} creadas, {result['updated']} actualizadas, {result['errors']} errores")

        _logger.info("=" * 80)
        _logger.info(f"FIN DE IMPORTACIÓN - Total: {total_created} creados, {total_updated} actualizados, {total_errors} errores")
        _logger.info("=" * 80)

        # Generar log HTML para mostrar en el wizard
        log_html = self._generate_import_log_html(total_created, total_updated, total_errors, all_errors, import_types)

        # Actualizar el wizard con los resultados
        self.write({
            'state': 'done',
            'import_log': log_html,
            'total_created': total_created,
            'total_updated': total_updated,
            'total_errors': total_errors,
        })

        # Reabrir el wizard para mostrar los resultados
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'aicia.importer.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def _generate_import_log_html(self, total_created, total_updated, total_errors, all_errors, import_types=None):
        """Genera un log HTML con los resultados de la importación."""

        # Determinar el texto según el tipo de importación
        if import_types and len(import_types) == 1:
            # Solo se importó un tipo
            if import_types[0] == 'suppliers':
                entity_text = 'Proveedores'
            elif import_types[0] == 'customers':
                entity_text = 'Clientes'
            elif import_types[0] == 'employees':
                entity_text = 'Empleados'
            elif import_types[0] == 'projects':
                entity_text = 'Proyectos'
            elif import_types[0] == 'project_assignments':
                entity_text = 'Asignaciones de Proyectos'
            else:
                entity_text = 'Contactos'
        else:
            # Se importaron varios tipos o ninguno especificado
            entity_text = 'Contactos'

        # Estilo para el log
        html = """
        <div style="font-family: Arial, sans-serif; padding: 10px;">
            <h3 style="color: #2e7d32; margin-bottom: 15px;">
                <i class="fa fa-check-circle"></i> Importación Completada
            </h3>
            <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 15px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr style="border-bottom: 1px solid #ddd;">
                        <td style="padding: 8px; font-weight: bold; width: 60%;">
                            <i class="fa fa-plus-circle" style="color: #4caf50;"></i> <span style="color: #4caf50;">{entity} creados:</span>
                        </td>
                        <td style="padding: 8px; text-align: right; font-size: 18px; color: #4caf50;">
                            <b>{created}</b>
                        </td>
                    </tr>
                    <tr style="border-bottom: 1px solid #ddd;">
                        <td style="padding: 8px; font-weight: bold;">
                            <i class="fa fa-refresh" style="color: #2196f3;"></i> <span style="color: #2196f3;">{entity} actualizados:</span>
                        </td>
                        <td style="padding: 8px; text-align: right; font-size: 18px; color: #2196f3;">
                            <b>{updated}</b>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">
                            <i class="fa fa-exclamation-triangle" style="color: {error_color};"></i> <span style="color: {error_color};">Errores encontrados:</span>
                        </td>
                        <td style="padding: 8px; text-align: right; font-size: 18px; color: {error_color};">
                            <b>{errors}</b>
                        </td>
                    </tr>
                </table>
            </div>
        """.format(
            entity=entity_text,
            created=total_created,
            updated=total_updated,
            errors=total_errors,
            error_color='#f44336' if total_errors > 0 else '#9e9e9e'
        )

        # Añadir detalles de errores si existen
        if all_errors:
            html += """
            <div style="margin-top: 20px;">
                <h4 style="color: #f44336; margin-bottom: 10px;">
                    <i class="fa fa-list"></i> Detalle de Errores:
                </h4>
                <div style="background-color: #ffebee; padding: 10px; border-left: 4px solid #f44336;
                            max-height: 400px; overflow-y: auto; border-radius: 3px;">
                    <ul style="margin: 0; padding-left: 20px;">
            """
            # Mostrar todos los errores
            for error in all_errors:
                html += f"<li style='margin-bottom: 5px; color:#f44336;'>{error}</li>"

            html += """
                    </ul>
                </div>
            </div>
            """
        else:
            html += """
            <div style="background-color: #e8f5e9; padding: 15px; border-left: 4px solid #4caf50;
                        border-radius: 3px; margin-top: 15px;">
                <p style="margin: 0; color: #2e7d32;">
                    <i class="fa fa-check"></i> <b>¡Importación exitosa sin errores!</b>
                </p>
            </div>
            """

        html += "</div>"
        return html

    def _get_province_mapping(self):
        """Crea un mapeo código -> res.country.state usando el diccionario PROVINCE_MAP."""
        province_map = {}
        country_es = self.env['res.country'].search([('code', '=', 'ES')], limit=1)

        if not country_es:
            _logger.warning("No se encontró el país España (ES) en la base de datos")
            return {}

        # Mapeo específico de códigos a códigos de provincia en Odoo
        code_mapping = {
            '1': 'VI',  # ALAVA -> Araba/Álava
            '2': 'AB',  # ALBACETE
            '3': 'A',  # ALACANT/ALICANTE -> Alacant (Alicante)
            '4': 'AL',  # ALMERIA -> Almería
            '5': 'AV',  # AVILA -> Ávila
            '6': 'BA',  # BADAJOZ -> Badajoz
            '7': 'PM',  # ILLES BALEARS -> Illes Balears
            '8': 'B',  # BARCELONA
            '9': 'BU',  # BURGOS
            '01': 'VI',      # ALAVA -> Araba/Álava
            '02': 'AB',      # ALBACETE
            '03': 'A',       # ALACANT/ALICANTE -> Alacant (Alicante)
            '04': 'AL',      # ALMERIA -> Almería
            '05': 'AV',      # AVILA -> Ávila
            '06': 'BA',      # BADAJOZ -> Badajoz
            '07': 'PM',      # ILLES BALEARS -> Illes Balears
            '08': 'B',       # BARCELONA
            '09': 'BU',      # BURGOS
            '10': 'CC',     # CACERES -> Cáceres
            '11': 'CA',     # CADIZ -> Cádiz
            '12': 'CS',     # CASTELLON -> Castelló
            '13': 'CR',     # CIUDAD REAL
            '14': 'CO',     # CORDOBA -> Córdoba
            '15': 'C',      # A CORUÑA
            '16': 'CU',     # CUENCA
            '17': 'GI',     # GIRONA
            '18': 'GR',     # GRANADA
            '19': 'GU',     # GUADALAJARA
            '20': 'SS',     # GUIPUZCOA -> Gipuzkoa
            '21': 'H',      # HUELVA
            '22': 'HU',     # HUESCA
            '23': 'J',      # JAEN -> Jaén
            '24': 'LE',     # LEON -> León
            '25': 'L',      # LLEIDA
            '26': 'LO',     # LA RIOJA
            '27': 'LU',     # LUGO
            '28': 'M',      # MADRID
            '29': 'MA',     # MALAGA -> Málaga
            '30': 'MU',     # MURCIA
            '31': 'NA',     # NAFARROA/NAVARRA -> Navarra
            '32': 'OR',     # OURENSE
            '33': 'O',      # ASTURIAS
            '34': 'P',      # PALENCIA
            '35': 'GC',     # LAS PALMAS
            '36': 'PO',     # PONTEVEDRA
            '37': 'SA',     # SALAMANCA
            '38': 'TF',     # STA. CRUZ TENERIFE -> Santa Cruz de Tenerife
            '39': 'S',      # CANTABRIA
            '40': 'SG',     # SEGOVIA
            '41': 'SE',     # SEVILLA
            '42': 'SO',     # SORIA
            '43': 'T',      # TARRAGONA
            '44': 'TE',     # TERUEL
            '45': 'TO',     # TOLEDO
            '46': 'V',      # VALENCIA -> València
            '47': 'VA',     # VALLADOLID
            '48': 'BI',     # VIZCAYA -> Bizkaia
            '49': 'ZA',     # ZAMORA
            '50': 'Z',      # ZARAGOZA
            '51': 'CE',     # CEUTA
            '52': 'ME',     # MELILLA
        }

        for codigo, odoo_code in code_mapping.items():
            # Buscar la provincia en Odoo por código
            state = self.env['res.country.state'].search([
                ('country_id', '=', country_es.id),
                ('code', '=', odoo_code)
            ], limit=1)

            if state:
                province_map[codigo] = state.id
                _logger.debug(f"Provincia mapeada: código {codigo} ({self.PROVINCE_MAP.get(codigo)}) -> {state.name} (código Odoo: {odoo_code}, ID: {state.id})")
            else:
                _logger.warning(f"No se encontró provincia en Odoo para código: {codigo}, código Odoo: {odoo_code}")

        _logger.info(f"Mapeo de provincias completado: {len(province_map)}/52 provincias mapeadas")
        return province_map


    def _import_file(self, data_file, is_supplier=True, province_map=None):
        """Importa un archivo Excel de proveedores o clientes."""
        try:
            # Decodificar el archivo
            file_data = b64decode(data_file)
            workbook = openpyxl.load_workbook(BytesIO(file_data))
            sheet = workbook.active

            # Obtener las filas del archivo
            rows = list(sheet.iter_rows(values_only=True))

            if len(rows) < 2:
                raise UserError(_("El archivo no contiene datos para importar."))

            # La primera fila son los encabezados
            headers = rows[0]
            data_rows = rows[1:]
            total_rows = len(data_rows)

            tipo = "proveedores" if is_supplier else "clientes"
            _logger.info(f"Iniciando importación de {total_rows} {tipo}...")

            # Procesar cada fila
            created_count = 0
            updated_count = 0
            error_count = 0
            errors = []
            batch_size = 50  # Hacer commit cada 50 registros

            for idx, row in enumerate(data_rows, start=2):  # start=2 porque la fila 1 es encabezado
                try:
                    # Log de progreso cada 100 registros
                    current = idx - 1
                    if current % 100 == 0:
                        _logger.info(f"Procesando {tipo}: {current}/{total_rows} ({int(current*100/total_rows)}%)")

                    result = self._process_partner_row(row, headers, is_supplier, province_map)
                    if result == 'created':
                        created_count += 1
                    elif result == 'updated':
                        updated_count += 1

                    # Hacer commit cada batch_size para que se vea el progreso
                    if current % batch_size == 0:
                        self.env.cr.commit()

                except Exception as e:
                    error_count += 1

                    # Intentar obtener información adicional para el error
                    data = dict(zip(headers, row))
                    partner_name = ''

                    # Intentar obtener el nombre del cliente/proveedor
                    try:
                        if is_supplier:
                            partner_id = data.get('ID_Proveedor', '')
                            partner_name = data.get('Nombre', '')
                            if partner_id:
                                partner_name = f"{partner_name} (ID: {partner_id})" if partner_name else f"(ID: {partner_id})"
                        else:
                            partner_id = data.get('ID_Cliente', '')
                            partner_name = data.get('Nombre', '')
                            if partner_id:
                                partner_name = f"{partner_name} (ID: C{partner_id})" if partner_name else f"(ID: C{partner_id})"
                    except:
                        partner_name = ''

                    # Construir mensaje de error detallado
                    error_base = str(e)

                    # Intentar detectar qué columna causó el error buscando en el stack trace
                    import traceback
                    tb_str = traceback.format_exc()

                    # Buscar patrones comunes de errores con campos
                    column_hint = ''
                    for header in headers:
                        if f"'{header}'" in error_base or f'"{header}"' in tb_str or f"data.get('{header}'" in tb_str:
                            column_hint = f" [Columna: {header}]"
                            break

                    # Construir el mensaje final
                    if partner_name:
                        error_msg = f"Fila {idx} - {partner_name}{column_hint}: {error_base}"
                    else:
                        error_msg = f"Fila {idx}{column_hint}: {error_base}"

                    errors.append(error_msg)
                    _logger.error(error_msg)
                    _logger.debug(f"Stack trace: {tb_str}")

            # Commit final
            self.env.cr.commit()
            _logger.info(f"Importación de {tipo} completada: {created_count} creados, {updated_count} actualizados, {error_count} errores")

            return {
                'created': created_count,
                'updated': updated_count,
                'errors': error_count,
                'error_list': errors,
            }

        except Exception as e:
            raise UserError(
                _("Error al procesar el archivo: %s") % str(e)
            )

    def _process_partner_row(self, row, headers, is_supplier=True, province_map=None):
        """Procesa una fila del Excel y crea o actualiza el proveedor o cliente."""
        # Mapear los datos de la fila
        data = dict(zip(headers, row))

        # Campos principales - Detectar si es proveedor o cliente por los campos
        if is_supplier:
            id_proveedor = str(data.get('ID_Proveedor', '')).strip() if data.get('ID_Proveedor') else False
            vat = data.get('CIF')
            vat = str(vat).strip() if vat is not None else False
            if id_proveedor:
                ref = ref = f"C{id_proveedor}"

        else:
            # Para clientes, añadir prefijo 'C' al ID_Cliente
            id_cliente = str(data.get('ID_Cliente', '')).strip() if data.get('ID_Cliente') else False
            vat = data.get('NIF')
            vat = str(vat).strip() if vat is not None else False
            if id_cliente:
                ref = f"C{id_cliente}"
            else:
                ref = False

        name = data.get('Nombre', '').strip() if data.get('Nombre') else False
        protecter_partner = data.get('Socio_Protector', '') if data.get('Socio_Protector') else False

        if not name:
            raise UserError(_("El campo 'Nombre' es obligatorio."))

        # Construir nombre completo si hay nombre2
        # Para que aparezca en complete_name, usamos company_name
        nombre2 = data.get('Nombre2')
        nombre2 = str(nombre2).strip() if nombre2 is not None else False
        full_name = f"({nombre2}) {name}" if nombre2 else name

        # Preparar valores para el contacto
        partner_vals = {
            'name': name,
            'is_company': True,
        }

        # Si hay nombre2, lo guardamos en company_name para que aparezca en complete_name
        if nombre2:
            partner_vals['company_name'] = nombre2

        # Marcar como proveedor o cliente
        if is_supplier:
            partner_vals['supplier_rank'] = 1
            partner_vals['codigo_proveedor'] = ref
        else:
            partner_vals['customer_rank'] = 1
            partner_vals['codigo_cliente'] = ref

        # Referencia interna (ya incluye la 'C' para clientes)
        if ref:
            partner_vals['ref'] = ref
        if protecter_partner:
            print("-"*50)
            print("protecter_partner: ",protecter_partner)
            partner_vals['protecter_partner'] = protecter_partner == True
            print("partner_vals['protecter_partner']:",partner_vals['protecter_partner'])
            print("-"*50)

        # País - Por defecto España si no se especifica
        country = self.env['res.country'].search([('code', '=', 'ES')], limit=1)
        if country:
            partner_vals['country_id'] = country.id

        # NIF/CIF
        print("*"*50)
        print("vat before processing:",vat)
        if vat:
            vat = vat.upper()
            print("vat after upper():",vat)

            # Si NO empieza por dos letras (código de país), añadir ES
            if not (len(vat) >= 2 and vat[:2].isalpha()):
                vat = 'ES' + vat
                print("vat after adding ES:",vat)

            partner_vals['vat'] = vat
            print("partner_vals['vat']:",partner_vals['vat'])
        print("*"*50)
        # Teléfonos - Concatenar teléfono fijo y móvil si ambos existen
        phone = data.get('Telefono')
        phone = str(phone).strip() if phone is not None else False
        mobile = data.get('TelefonoMovil')
        mobile = str(mobile).strip() if mobile is not None else False

        if phone and mobile:
            # Si hay ambos, concatenar con separador
            partner_vals['phone'] = f"{phone} / {mobile}"
        elif phone:
            partner_vals['phone'] = phone
        elif mobile:
            partner_vals['phone'] = mobile

        # Email
        email = data.get('Correo_Electronico', '').strip() if data.get('Correo_Electronico') else False
        if email:
            partner_vals['email'] = email

        # Dirección
        street = data.get('Direccion')
        street = str(street).strip() if street is not None else False
        street2 = data.get('Direccion2')
        street2 = str(street2).strip() if street2 is not None else False

        if street:
            partner_vals['street'] = street
        if street2:
            partner_vals['street2'] = street2

        # Ciudad y código postal
        city = data.get('Localidad')
        city = str(city).strip() if city is not None else False
        if city:
            partner_vals['city'] = city

        zip_code = data.get('Cod_Postal')
        zip_code = str(zip_code).strip() if zip_code is not None else False

        if zip_code:
            partner_vals['zip'] = zip_code

        # País - Por defecto España si no se especifica
        country = self.env['res.country'].search([('code', '=', 'ES')], limit=1)
        if country:
            partner_vals['country_id'] = country.id

        # Provincia - extraer del código postal (2 primeros dígitos)
        if province_map and zip_code:
            # Extraer los dos primeros caracteres del código postal
            try:
                zip_str = str(zip_code).strip()
                if len(zip_str) >= 2:
                    provincia_codigo = zip_str[:2]
                    # Eliminar ceros a la izquierda para códigos como "01", "02", etc.
                    provincia_codigo = str(int(provincia_codigo))

                    if provincia_codigo in province_map:
                        partner_vals['state_id'] = province_map[provincia_codigo]
                        _logger.debug(f"✓ Provincia asignada desde CP {zip_code}: código {provincia_codigo} -> state_id {province_map[provincia_codigo]}")
                    else:
                        _logger.warning(f"✗ Código de provincia no encontrado: '{provincia_codigo}' extraído del CP: {zip_code}")
                else:
                    _logger.warning(f"✗ Código postal demasiado corto para extraer provincia: '{zip_code}'")
            except Exception as e:
                _logger.warning(f"✗ Error al extraer provincia del código postal '{zip_code}': {str(e)}")

        # Comentarios/Observaciones
        comment = data.get('Observaciones', '').strip() if data.get('Observaciones') else ''
        comment2 = data.get('Observaciones2', '').strip() if data.get('Observaciones2') else ''

        if comment or comment2:
            full_comment = '\n'.join(filter(None, [comment, comment2]))
            partner_vals['comment'] = full_comment

        # Persona de contacto
        contact_person = data.get('Persona_Contacto')
        contact_person = str(contact_person).strip() if contact_person is not None else False


        # Buscar si el proveedor ya existe
        # Prioridad: 1. por ref, 2. por vat, 3. por nombre
        existing_partner = False

        if ref:
            if is_supplier:
                existing_partner = self.env['res.partner'].search([('codigo_proveedor', '=', ref)], limit=1)
                _logger.debug(f"Búsqueda por ref '{ref}': {'encontrado' if existing_partner else 'no encontrado'}")
            else:
                existing_partner = self.env['res.partner'].search([('codigo_cliente', '=', ref)], limit=1)
                _logger.debug(f"Búsqueda por ref '{ref}': {'encontrado' if existing_partner else 'no encontrado'}")

        # if not existing_partner and vat:
        #     existing_partner = self.env['res.partner'].search([('vat', '=', vat)], limit=1)
        #     _logger.debug(f"Búsqueda por vat '{vat}': {'encontrado' if existing_partner else 'no encontrado'}")
        #
        # if not existing_partner:
        #     existing_partner = self.env['res.partner'].search([('name', '=', name)], limit=1)
        #     _logger.debug(f"Búsqueda por nombre '{name}': {'encontrado' if existing_partner else 'no encontrado'}")
        print("*"*50)
        print("partner_vals:",partner_vals)
        print("*"*50)
        if existing_partner:
            if self.update_existing:
                existing_partner.with_context(import_file=True,check_vies=False).write(partner_vals)

                # Forzar complete_name si hay nombre2
                if nombre2:
                    self.env.cr.execute(
                        "UPDATE res_partner SET complete_name = %s WHERE id = %s",
                        (full_name, existing_partner.id)
                    )

                # Si hay persona de contacto y no existe, crearla
                if contact_person:
                    self._create_contact_person(existing_partner, contact_person, data)

                # Crear o actualizar cuenta bancaria
                self._create_or_update_bank_account(existing_partner, data)

                return 'updated'
            else:
                return 'skipped'
        else:
            # Crear nuevo proveedor
            new_partner = self.env['res.partner'].with_context(import_file=True,check_vies=False).create(partner_vals)

            # Forzar complete_name si hay nombre2 escribiendo directamente en BD
            if nombre2:
                self.env.cr.execute(
                    "UPDATE res_partner SET complete_name = %s WHERE id = %s",
                    (full_name, new_partner.id)
                )

            # Si hay persona de contacto, crearla como contacto del proveedor
            if contact_person:
                self._create_contact_person(new_partner, contact_person, data)

            # Crear cuenta bancaria si hay datos
            self._create_or_update_bank_account(new_partner, data)

            return 'created'

    def _create_contact_person(self, partner, contact_name, data):
        """Crea una persona de contacto para el proveedor."""
        # Verificar si ya existe un contacto con ese nombre
        existing_contact = self.env['res.partner'].search([
            ('parent_id', '=', partner.id),
            ('name', '=', contact_name),
        ], limit=1)

        if not existing_contact:
            contact_vals = {
                'name': contact_name,
                'parent_id': partner.id,
                'type': 'contact',
            }

            # Si hay email específico para el contacto (aunque en este caso va al principal)
            email = data.get('Correo_Electronico', '').strip() if data.get('Correo_Electronico') else False
            if email:
                contact_vals['email'] = email

            self.env['res.partner'].create(contact_vals)

    def _create_or_update_bank_account(self, partner, data):
        """Crea o actualiza la cuenta bancaria del contacto."""
        try:
            # Obtener datos bancarios del Excel - convertir a string y limpiar
            id_banco = str(data.get('ID_Banco', '') or '').strip()
            id_sucursal = str(data.get('ID_Sucursal', '') or '').strip()
            digito_control = str(data.get('Digito_Control', '') or '').strip()
            numero_cuenta = str(data.get('Numero_Cuenta', '') or '').strip()
            iban_pais = str(data.get('IBAN_Pais', '') or 'ES').strip()
            iban_dc = str(data.get('IBAN_DC', '') or '').strip()

            _logger.debug(f"Datos bancarios para {partner.name}: Banco={id_banco}, Sucursal={id_sucursal}, DC={digito_control}, Cuenta={numero_cuenta}, IBAN_DC={iban_dc}")

            # Si no hay datos bancarios significativos, no crear cuenta
            if not numero_cuenta or numero_cuenta == '0' or numero_cuenta == '0000000000':
                _logger.debug(f"Sin datos bancarios válidos para {partner.name}")
                return

            # Construir número de cuenta bancaria
            # Formato antiguo español: BANCO-SUCURSAL-DC-CUENTA
            acc_number_parts = []
            if id_banco and id_banco != '0':
                acc_number_parts.append(id_banco.zfill(4))
            if id_sucursal and id_sucursal != '0':
                acc_number_parts.append(id_sucursal.zfill(4))
            if digito_control and digito_control != '0':
                acc_number_parts.append(digito_control.zfill(2))
            if numero_cuenta and numero_cuenta != '0':
                acc_number_parts.append(numero_cuenta.zfill(10))

            # Construir IBAN si tenemos los datos necesarios
            acc_number = None
            if len(acc_number_parts) == 4:
                # Formato CCC (Código Cuenta Cliente) español
                ccc = ''.join(acc_number_parts)
                # Construir IBAN: ES + DC + CCC
                if iban_dc and iban_dc != '0':
                    acc_number = f"{iban_pais}{iban_dc.zfill(2)}{ccc}"
                    _logger.debug(f"IBAN construido para {partner.name}: {acc_number}")
                else:
                    # Si no tenemos dígito de control del IBAN, usar el CCC directamente
                    acc_number = ccc
                    _logger.debug(f"CCC construido para {partner.name}: {acc_number}")
            elif numero_cuenta and numero_cuenta != '0':
                # Si solo tenemos número de cuenta, usar ese
                acc_number = numero_cuenta
                _logger.debug(f"Solo número cuenta para {partner.name}: {acc_number}")

            if not acc_number or acc_number == '0':
                _logger.debug(f"Número de cuenta vacío o cero para {partner.name}")
                return

            # Buscar si ya existe una cuenta bancaria para este partner
            existing_bank = self.env['res.partner.bank'].search([
                ('partner_id', '=', partner.id),
                ('acc_number', '=', acc_number),
            ], limit=1)

            if existing_bank:
                _logger.debug(f"Cuenta bancaria ya existe para {partner.name}: {acc_number}")
                # Actualizar para asegurar que allow_out_payment está activo
                if not existing_bank.allow_out_payment:
                    existing_bank.write({'allow_out_payment': True})
                    _logger.info(f"✓ Campo allow_out_payment activado para cuenta de {partner.name}")
                return
            else:
                # Crear nueva cuenta bancaria
                bank_vals = {
                    'partner_id': partner.id,
                    'acc_number': acc_number,
                    'allow_out_payment': True,  # Permitir pagos salientes
                }

                # Si es un IBAN válido (empieza con código país de 2 letras)
                if acc_number and len(acc_number) > 2 and acc_number[:2].isalpha():
                    bank_vals['acc_type'] = 'iban'

                self.env['res.partner.bank'].create(bank_vals)
                _logger.info(f"✓ Cuenta bancaria creada para {partner.name}: {acc_number} (allow_out_payment=True)")

        except Exception as e:
            # Si hay error creando la cuenta, registrar pero continuar
            _logger.warning(f"✗ Error creando cuenta bancaria para {partner.name}: {str(e)}")
    def _get_employee_and_partner(self, ref, nif, full_name):
        print("!"*100)
        print("Busqueda de empleado y contacto de trabajo")
        employee = False
        partner_work = False
        if ref:
            print("Buscando por codigo_empleado:",ref)
            employee = self.env['hr.employee'].search([('codigo_empleado', '=', ref)], limit=1)
            if employee:
                print("Empleado encontrado por codigo_empleado:",employee.name)
                partner_work = employee.work_contact_id
                if partner_work:
                    print("Contacto de trabajo encontrado por empleado:",partner_work.name)
                    return employee, partner_work
                else:
                    print("No se encontró contacto de trabajo para el empleado")
        # if not employee and nif:
        #     print("Buscando por nif:",nif)
        #     employee = self.env['hr.employee'].search([('identification_id', '=', nif)], limit=1)
        #     if employee:
        #         print("Empleado encontrado por nif:",employee.name)
        #         partner_work = employee.work_contact_id
        #         if partner_work:
        #             print("Contacto de trabajo encontrado por empleado:",partner_work.name)
        #             return employee, partner_work
        #         else:
        #             print("No se encontró contacto de trabajo para el empleado")
        # if not employee:
        #     print("Buscando por nombre completo:",full_name)
        #     employee = self.env['hr.employee'].search([('name', '=', full_name)], limit=1)
        #     if employee:
        #         print("Empleado encontrado por nombre completo:",employee.name)
        #         partner_work = employee.work_contact_id
        #         if partner_work:
        #             print("Contacto de trabajo encontrado por empleado:",partner_work.name)
        #             return employee, partner_work
        #         else:
        #             print("No se encontró contacto de trabajo para el empleado")
        return employee, partner_work
        print("Finalizada busqueda")
        print("!"*100)

    def _colaborator_mapping(self, colaborator):
        mapping = {
            1: 'PROFESOR',
            2: 'TÉCNICO',
            3: 'BECARIO AICIA',
            4: 'ADMINISTRATIVO',
            5: 'PTGAS',
        }

        if not colaborator:
            return ''

        try:
            colaborator = int(colaborator)
        except (ValueError, TypeError):
            return ''

        return mapping.get(colaborator, '')

    def _import_employees(self, file_data, province_map):
        """Importa empleados desde un archivo Excel."""
        result = {
            'created': 0,
            'updated': 0,
            'errors': 0,
            'error_list': []
        }

        try:
            # Decodificar y cargar el archivo Excel
            file_content = b64decode(file_data)
            workbook = openpyxl.load_workbook(BytesIO(file_content))
            sheet = workbook.active

            # Obtener los encabezados de las columnas
            headers = {}
            for col_idx, cell in enumerate(sheet[1], start=1):
                if cell.value:
                    headers[cell.value.strip()] = col_idx

            _logger.info(f">>> Columnas encontradas: {list(headers.keys())}")

            # Procesar las filas de datos (desde la fila 2)
            total_rows = sheet.max_row - 1
            _logger.info(f">>> Total de filas a procesar: {total_rows}")

            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                try:
                    # Mostrar progreso cada 10 registros
                    if (row_idx - 1) % 10 == 0:
                        _logger.info(f">>> Procesando empleado {row_idx - 1}/{total_rows}")

                    # Mapear los datos de la fila
                    data = dict(zip(headers.keys(), row))

                    # Obtener valores de las celdas
                    codigo = str(data.get('ID_Personal', '')).strip() if data.get('ID_Personal') else ''
                    nombre = str(data.get('Nombre', '')).strip() if data.get('Nombre') else ''
                    nif = str(data.get('NIF', '')).strip() if data.get('NIF') else ''
                    direccion = str(data.get('Direccion', '')).strip() if data.get('Direccion') else ''
                    cod_postal = str(data.get('Cod_Postal', '')).strip() if data.get('Cod_Postal') else ''
                    poblacion = str(data.get('Población', '')).strip() if data.get('Población') else ''
                    telefono = str(data.get('Teléfono', '')).strip() if data.get('Teléfono') else ''
                    movil = str(data.get('TelefonoMovil', '')).strip() if data.get('TelefonoMovil') else ''
                    email = str(data.get('Correo_Electronico', '')).strip() if data.get('Correo_Electronico') else ''
                    nss = str(data.get('NSS', '')).strip() if data.get('NSS') else ''
                    fecha_antiguedad = data.get('Fecha Antiguedad', '')
                    cuenta_bancaria = str(data.get('Cuenta Bancaria', '')).strip() if data.get('Cuenta Bancaria') else ''
                    tipo_contrato = str(data.get('Tipo de contrato', '')).strip() if data.get('Tipo de contrato') else ''
                    titulacion = str(data.get('Titulacion', '')).strip() if data.get('Titulacion') else ''
                    apply_retention = data.get('Aplica_Retencion', False)
                    permision_to_desplace = data.get('Permiso_Desplazamiento', False)
                    observaciones = str(data.get('Observaciones', '')).strip() if data.get('Observaciones') else ''
                    departamento = str(data.get('ID_Departamento', '')).strip() if data.get('ID_Departamento') else ''
                    colaborador = str(data.get('Colaborador', '')).strip() if data.get('Colaborador') else ''

                    # Validaciones básicas
                    if not nombre:
                        _logger.warning(f"Fila {row_idx}: Sin nombre ni apellido, saltando...")
                        continue

                    # Construir nombre completo
                    full_name = nombre
                    ref = False
                    if codigo is not None:
                        ref = f"E{codigo}"
                    # Buscar empleado existente por codigo de empleado , nif o nombre completo
                    employee, partner_work = self._get_employee_and_partner(ref, nif, full_name)
                    if email is None:
                        print("!*"*50)
                        print("Email encontrado:",email)
                        print("No hay email, se asignará uno genérico")
                        print("!*" * 50)
                        email =f"{ref}@aicia.es"

                    partner_vals = {
                        'name': full_name,
                        'ref': ref,
                        'vat': nif if nif else False,
                        'street': direccion if direccion else False,
                        'zip': cod_postal if cod_postal else False,
                        'city': poblacion if poblacion else False,
                        'email': email if email else False,
                        'country_id': self.env.ref('base.es').id,  # España
                        'type': 'contact',
                    }
                    # Teléfonos - Concatenar teléfono fijo y móvil si ambos existen (igual que proveedores/clientes)
                    if telefono and movil:
                        partner_vals['phone'] = f"{telefono} / {movil}"
                    elif telefono:
                        partner_vals['phone'] = telefono
                    elif movil:
                        partner_vals['phone'] = movil

                    # Obtener estado (provincia) desde código postal usando el mismo método que proveedores/clientes
                    if province_map and cod_postal and len(str(cod_postal)) >= 2:
                        try:
                            zip_str = str(cod_postal).strip()
                            if len(zip_str) >= 2:
                                provincia_codigo = zip_str[:2]
                                # Eliminar ceros a la izquierda para códigos como "01", "02", etc.
                                provincia_codigo = str(int(provincia_codigo))

                                if provincia_codigo in province_map:
                                    partner_vals['state_id'] = province_map[provincia_codigo]
                                    _logger.debug(f"✓ Provincia asignada desde CP {cod_postal}: código {provincia_codigo} -> state_id {province_map[provincia_codigo]}")
                                else:
                                    _logger.warning(f"✗ Código de provincia no encontrado: '{provincia_codigo}' extraído del CP: {cod_postal}")
                            else:
                                _logger.warning(f"✗ Código postal demasiado corto para extraer provincia: '{cod_postal}'")
                        except Exception as e:
                            _logger.warning(f"✗ Error al extraer provincia del código postal '{cod_postal}': {str(e)}")
                        # Crear o actualizar el contacto de trabajo
                    if partner_work:
                        if self.update_existing:
                            print("/")
                            print("partner_vals a escribir:",partner_vals)
                            partner_work.with_context(import_file=True,check_vies=False).write(partner_vals)
                    else:
                        print("//")
                        partner_work = self.env['res.partner'].with_context(import_file=True,check_vies=False).create(partner_vals)

                    # movil = None

                    if movil:
                        movil = re.sub(r"[^\d]", "", movil)

                    elif telefono:
                        tel_limpio = re.sub(r"[^\d]", "", telefono)
                        if tel_limpio and tel_limpio[0] in "67":
                            movil = tel_limpio

                    if movil:
                        if movil.startswith("34"):
                            movil = movil[2:]

                        if len(movil) != 9:
                            movil = False
                        else:
                            movil = f"+34 {movil[:3]} {movil[3:5]} {movil[5:7]} {movil[7:]}"

                    #BUscamos del departamento
                    department_id = False
                    if departamento is not None:
                        dep_code = str(departamento).zfill(2)  # asegura 2 dígitos: 1 -> "01"
                        department = self.env['hr.department'].search([
                            ('name', 'ilike', f'{dep_code}-')
                        ], limit=1)

                        if department:
                            department_id = department.id
                        else:
                            _logger.warning(
                                f"Departamento no encontrado: '{dep_code}-*' para empleado {full_name}"
                            )



                    # Preparar valores para el empleado
                    employee_vals = {
                        'name': full_name,
                        'work_contact_id': partner_work.id,
                        'identification_id': nif if nif else False,
                        'codigo_empleado': ref if ref else False,
                        'ssnid': nss if nss else False,  # Número de Seguridad Social
                        'work_phone': telefono if telefono else False,
                        'mobile_phone': movil if movil else False,
                        'work_email': email if email else False,
                        'job_title': titulacion if titulacion else False,
                        'permission_to_desplace': permision_to_desplace if permision_to_desplace else False,
                        'apply_retention': apply_retention if apply_retention else False,
                        'additional_note': observaciones if observaciones else False,
                        # Dirección privada del empleado
                        'private_street': direccion if direccion else False,
                        'private_city': poblacion if poblacion else False,
                        'private_zip': cod_postal if cod_postal else False,
                        'private_country_id': self.env.ref('base.es').id,  # España
                        'department_id': department_id,
                    }
                    if colaborador:
                        print("/*"*50)
                        print("Valor de colaborador:",colaborador)

                        colaborator_value = self._colaborator_mapping(colaborador)
                        print("Valor mapeado de colaborador:",colaborator_value)
                        print("/*" * 50)
                        if colaborator_value:
                            colaborator_job = self.env['hr.job'].search([('name', '=', colaborator_value)], limit=1)
                            if colaborator_job:
                                employee_vals['job_id'] = colaborator_job.id
                        else:
                            _logger.warning(
                                f"Valor de colaborador no reconocido: '{colaborador}' para empleado {full_name}"
                            )
                    # Guardar el email original antes de cualquier procesamiento
                    portal_email = email if email else False

                    # Añadir provincia privada si existe
                    if province_map and cod_postal and len(str(cod_postal)) >= 2:
                        try:
                            zip_str = str(cod_postal).strip()
                            if len(zip_str) >= 2:
                                provincia_codigo = zip_str[:2]
                                provincia_codigo = str(int(provincia_codigo))
                                if provincia_codigo in province_map:
                                    employee_vals['private_state_id'] = province_map[provincia_codigo]
                        except Exception as e:
                            _logger.warning(f"✗ Error al extraer provincia para empleado {full_name}: {str(e)}")

                    # Crear o actualizar empleado
                    if employee:
                        if self.update_existing:
                            employee.write(employee_vals)
                            result['updated'] += 1
                            _logger.info(f"✓ Empleado actualizado: {full_name}")
                        else:
                            _logger.debug(f"◷ Empleado ya existe (no actualizar): {full_name}")
                    else:
                        employee = self.env['hr.employee'].create(employee_vals)
                        result['created'] += 1
                        _logger.info(f"✓ Empleado creado: {full_name}")

                    # Verificar si necesita crear usuario portal (DESPUÉS de crear/actualizar el empleado)
                    # para asegurar que employee.work_contact_id existe
                    if not portal_email and ref:
                        # Generar email genérico basado en el código de empleado
                        portal_email = f"{ref}@aicia.es"
                        _logger.info(f">>> Generando email genérico para {full_name}: {portal_email}")
                    # SIEMPRE llamar al método para crear O actualizar el usuario portal
                    if portal_email:
                        _logger.info(f">>> Llamando a _create_portal_user_for_employee para {full_name} con email {portal_email}")
                        self._create_portal_user_for_employee(employee, portal_email, full_name, result)
                    else:
                        _logger.warning(f"✗ No se puede crear usuario portal para {full_name}: sin email ni código de empleado")

                    # Crear cuenta bancaria si existe
                    if cuenta_bancaria and cuenta_bancaria != '0':
                        self._create_employee_bank_account(employee, cuenta_bancaria)

                    # Crear o actualizar contrato si existe tipo de contrato
                    if tipo_contrato:
                        self._create_or_update_contract(employee, tipo_contrato, fecha_antiguedad)
                except Exception as e:
                    result['errors'] += 1
                    # Intentar obtener información del empleado para el error
                    employee_name = ''
                    try:
                        data = dict(zip(headers.keys(), row))
                        codigo = data.get('Código Personal', '')
                        nombre = data.get('Nombre', '')
                        apellido1 = data.get('Apellido1', '')
                        apellido2 = data.get('Apellido2', '')

                        # Construir nombre
                        name_parts = [nombre, apellido1, apellido2]
                        employee_name = ' '.join([str(p).strip() for p in name_parts if p]).strip()

                        if codigo:
                            employee_name = f"{employee_name} (Código: {codigo})" if employee_name else f"(Código: {codigo})"
                    except:
                        pass

                    # Construir mensaje de error detallado
                    error_base = str(e)

                    # Intentar detectar qué columna causó el error
                    import traceback
                    tb_str = traceback.format_exc()

                    column_hint = ''
                    if headers:
                        for header in headers.keys():
                            if f"'{header}'" in error_base or f'"{header}"' in tb_str or f"data.get('{header}'" in tb_str:
                                column_hint = f" [Columna: {header}]"
                                break

                    # Construir el mensaje final
                    if employee_name:
                        error_msg = f"Fila {row_idx} - {employee_name}{column_hint}: {error_base}"
                    else:
                        error_msg = f"Fila {row_idx}{column_hint}: {error_base}"

                    result['error_list'].append(error_msg)
                    _logger.error(f"✗ {error_msg}")
                    _logger.debug(f"Stack trace: {tb_str}")


                except Exception as e:
                    result['errors'] += 1
                    error_msg = f"Fila {row_idx}: Error procesando empleado: {str(e)}"
                    result['error_list'].append(error_msg)
                    _logger.error(error_msg)
                    continue
        except Exception as e:
            error_msg = f"Error al procesar el archivo: {str(e)}"
            result['errors'] += 1
            result['error_list'].append(error_msg)
            _logger.error(f"✗ {error_msg}")

        return result

    def _create_employee_bank_account(self, employee, cuenta_bancaria):
        """Crea una cuenta bancaria para el empleado."""
        try:
            if not employee.work_contact_id:
                _logger.warning(f"El empleado {employee.name} no tiene contacto de trabajo asociado")
                return

            # Limpiar y formatear el número de cuenta
            acc_number = str(cuenta_bancaria).strip().replace(' ', '')

            if not acc_number or acc_number == '0':
                return

            # Buscar si ya existe una cuenta bancaria
            existing_bank = self.env['res.partner.bank'].search([
                ('partner_id', '=', employee.work_contact_id.id),
                ('acc_number', '=', acc_number),
            ], limit=1)

            if existing_bank:
                _logger.debug(f"Cuenta bancaria ya existe para {employee.name}")
                return

            # Crear nueva cuenta bancaria
            bank_vals = {
                'partner_id': employee.work_contact_id.id,
                'acc_number': acc_number,
            }

            # Si es un IBAN válido
            if acc_number and len(acc_number) > 2 and acc_number[:2].isalpha():
                bank_vals['acc_type'] = 'iban'

            self.env['res.partner.bank'].create(bank_vals)
            _logger.info(f"✓ Cuenta bancaria creada para empleado {employee.name}: {acc_number}")

        except Exception as e:
            _logger.warning(f"✗ Error creando cuenta bancaria para empleado {employee.name}: {str(e)}")

    def _create_or_update_contract(self, employee, tipo_contrato, fecha_antiguedad):
        """Crea o actualiza el contrato del empleado."""
        try:
            # Verificar si el módulo hr_contract está instalado
            if 'hr.contract' not in self.env:
                _logger.debug(f"Módulo hr_contract no instalado, saltando creación de contrato para {employee.name}")
                return

            # Buscar si ya existe un contrato activo para este empleado
            existing_contract = self.env['hr.contract'].search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'open'),
            ], limit=1)

            contract_vals = {
                'name': f"Contrato - {employee.name}",
                'employee_id': employee.id,
            }

            # Añadir fecha de inicio si existe fecha de antigüedad
            if fecha_antiguedad:
                try:
                    # Intentar convertir la fecha
                    from datetime import datetime
                    if isinstance(fecha_antiguedad, str):
                        # Probar diferentes formatos de fecha
                        for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
                            try:
                                date_obj = datetime.strptime(fecha_antiguedad, fmt)
                                contract_vals['date_start'] = date_obj.date()
                                break
                            except ValueError:
                                continue
                    elif hasattr(fecha_antiguedad, 'date'):
                        # Es un objeto datetime
                        contract_vals['date_start'] = fecha_antiguedad.date()
                    else:
                        contract_vals['date_start'] = fecha_antiguedad
                except Exception as e:
                    _logger.warning(f"No se pudo convertir la fecha de antigüedad para {employee.name}: {str(e)}")

            # Buscar o crear el tipo de contrato
            if tipo_contrato:
                if 'hr.contract.type' in self.env:
                    contract_type = self.env['hr.contract.type'].search([
                        ('name', '=ilike', tipo_contrato)
                    ], limit=1)

                    if not contract_type:
                        contract_type = self.env['hr.contract.type'].create({
                            'name': tipo_contrato
                        })
                        _logger.info(f"✓ Tipo de contrato creado: {tipo_contrato}")

                    contract_vals['contract_type_id'] = contract_type.id

            if existing_contract:
                if self.update_existing:
                    existing_contract.write(contract_vals)
                    _logger.info(f"✓ Contrato actualizado para {employee.name}")
            else:
                # Añadir el estado del contrato al crear uno nuevo
                contract_vals['state'] = 'open'
                self.env['hr.contract'].create(contract_vals)
                _logger.info(f"✓ Contrato creado para {employee.name}")

        except Exception as e:
            _logger.warning(f"✗ Error creando/actualizando contrato para {employee.name}: {str(e)}")

    def _create_portal_user_for_employee(self, employee, email, full_name, result):
        """
        Crea un usuario tipo portal para el empleado usando el wizard estándar de Odoo.
        Los errores se agregan al diccionario result para mostrarse en el resumen del wizard.
        """
        try:
            _logger.info(f">>> Iniciando creación de usuario portal para: {full_name} ({email})")

            # Validar que el email sea válido
            if not email or '@' not in email:
                error_msg = f"Usuario portal - {full_name}: email inválido o vacío"
                result['error_list'].append(error_msg)
                _logger.warning(f"✗ {error_msg}")
                return

            # Verificar que el empleado tenga un partner asociado
            if not employee.work_contact_id:
                error_msg = f"Usuario portal - {full_name}: no tiene contacto de trabajo asociado"
                result['error_list'].append(error_msg)
                _logger.warning(f"✗ {error_msg}")
                return

            partner = employee.work_contact_id
            _logger.info(f">>> Partner encontrado: {partner.name} (ID: {partner.id})")

            # Verificar si el partner ya tiene un usuario asociado
            if partner.user_ids:
                existing_user = partner.user_ids[0]
                _logger.info(f">>> Partner ya tiene usuario asociado: {existing_user.login}")

                # Actualizar datos del usuario existente
                user_vals_to_update = {}
                partner_vals_to_update = {}
                login_changed = False

                # Actualizar email y login si cambió
                new_login = email.lower()
                _logger.info(f">>> Comparando login actual '{existing_user.login}' con nuevo '{new_login}'")
                _logger.info(f">>> Comparando email actual '{existing_user.email}' con nuevo '{email}'")
                if existing_user.login != new_login or existing_user.email != email:
                    user_vals_to_update['login'] = new_login
                    user_vals_to_update['email'] = email
                    partner_vals_to_update['email'] = email
                    login_changed = True
                    _logger.info(f">>> ACTUALIZANDO login de '{existing_user.login}' a '{new_login}' y email a '{email}'")

                # Actualizar nombre del partner si cambió
                if partner.name != full_name:
                    partner_vals_to_update['name'] = full_name
                    _logger.info(f">>> Actualizando nombre de partner de '{partner.name}' a '{full_name}'")

                # Asegurar que el idioma sea español
                if existing_user.lang != 'es_ES':
                    user_vals_to_update['lang'] = 'es_ES'
                    _logger.info(f">>> Actualizando idioma a español")

                # Aplicar actualizaciones si hay cambios
                if user_vals_to_update:
                    try:
                        existing_user.sudo().write(user_vals_to_update)
                        _logger.info(f"✓ Usuario actualizado correctamente con write() - login: {new_login}, email: {email}")
                    except Exception as e:
                        # Si falla el write(), intentar actualizar el login y email directamente con SQL
                        if login_changed:
                            _logger.warning(f"Write falló, usando SQL para actualizar login y email: {str(e)}")
                            self.env.cr.execute(
                                "UPDATE res_users SET login = %s, email = %s WHERE id = %s",
                                (new_login, email, existing_user.id)
                            )
                            # Actualizar otros campos sin login ni email
                            user_vals_without_login_email = {k: v for k, v in user_vals_to_update.items() if k not in ['login', 'email']}
                            if user_vals_without_login_email:
                                existing_user.sudo().write(user_vals_without_login_email)
                            _logger.info(f"✓ Usuario actualizado con SQL - login: {new_login}, email: {email}")
                        else:
                            raise

                if partner_vals_to_update:
                    partner.sudo().write(partner_vals_to_update)
                    _logger.info(f"✓ Partner actualizado: {full_name}")

                # Asociar al empleado si no lo estaba
                if not employee.user_id or employee.user_id.id != existing_user.id:
                    employee.write({'user_id': existing_user.id})
                    _logger.info(f"✓ Usuario existente '{email}' asociado al empleado {full_name}")

                if user_vals_to_update or partner_vals_to_update:
                    _logger.info(f"✓ Usuario portal actualizado para {full_name} (login: {new_login}, email: {email})")
                else:
                    _logger.info(f"✓ Usuario portal ya estaba correcto para {full_name} (login: {existing_user.login}, email: {existing_user.email})")

                return

            # Verificar si ya existe otro usuario con ese email (pero no asociado al partner)
            existing_user_by_email = self.env['res.users'].sudo().search([
                ('login', '=', email.lower())
            ], limit=1)

            if existing_user_by_email:
                # Añadir un "2" al final del email
                original_email = email
                email_parts = email.split('@')
                if len(email_parts) == 2:
                    email_base = email_parts[0]
                    email_domain = email_parts[1]
                    email = f"{email_base}2@{email_domain}"
                    _logger.info(f">>> Email {original_email} ya existe, usando {email} en su lugar")
                else:
                    error_msg = f"Usuario portal - {full_name}: formato de email inválido {email}"
                    result['error_list'].append(error_msg)
                    _logger.warning(f"✗ {error_msg}")
                    return

            # Asegurarnos de que el partner tiene el email correcto
            if partner.email != email:
                _logger.info(f">>> Actualizando email del partner de '{partner.email}' a '{email}'")
                partner.write({'email': email})

            # Crear el wizard de portal usando el contexto estándar de Odoo
            _logger.info(f">>> Creando wizard de portal para {partner.name}")
            portal_wizard = self.env['portal.wizard'].sudo().with_context(
                active_ids=[partner.id],
                lang='es_ES'
            ).create({})

            # Verificar que se creó el user en el wizard
            if not portal_wizard.user_ids:
                error_msg = f"Usuario portal - {full_name}: no se pudo crear el wizard de portal"
                result['error_list'].append(error_msg)
                _logger.warning(f"✗ {error_msg}")
                return

            portal_user = portal_wizard.user_ids[0]
            _logger.info(f">>> Portal wizard user creado")

            # Asegurarnos de que el email está configurado correctamente
            if portal_user.email != email:
                portal_user.email = email

            # Otorgar acceso al portal usando el método estándar de Odoo (envía invitación)
            _logger.info(f">>> Otorgando acceso al portal y enviando invitación")
            portal_user.sudo().action_grant_access()

            # Obtener el usuario creado y asociarlo al empleado
            if partner.user_ids:
                new_user = partner.user_ids[0]
                # Establecer el idioma español al usuario
                new_user.sudo().write({'lang': 'es_ES'})
                employee.write({'user_id': new_user.id})
                _logger.info(f"✓ Usuario portal creado con idioma español y asociado al empleado {full_name} (login: {email})")
            else:
                error_msg = f"Usuario portal - {full_name}: no se pudo obtener el usuario creado"
                result['error_list'].append(error_msg)
                _logger.warning(f"✗ {error_msg}")

        except Exception as e:
            error_msg = f"Usuario portal - {full_name}: {str(e)}"
            result['error_list'].append(error_msg)
            _logger.error(f"✗✗✗ ERROR creando usuario portal para {full_name}: {str(e)}")
            import traceback
            _logger.error(f"Stack trace completo:\n{traceback.format_exc()}")


    def _import_projects(self, file_data):
        # """Importa proyectos (cuentas analíticas) desde un archivo Excel."""
        result = {
            'created': 0,
            'updated': 0,
            'errors': 0,
            'error_list': []
        }
        #
        cliente_not_found_count = 0
        try:
            # Decodificar y cargar el archivo Excel
            file_content = b64decode(file_data)
            workbook = openpyxl.load_workbook(BytesIO(file_content))
            sheet = workbook.active

            # Obtener los encabezados de las columnas
            headers = {}
            for col_idx, cell in enumerate(sheet[1], start=1):
                if cell.value:
                    headers[cell.value.strip()] = col_idx

            _logger.info(f">>> Columnas encontradas: {list(headers.keys())}")

            # Procesar las filas de datos (desde la fila 2)
            total_rows = sheet.max_row - 1
            _logger.info(f">>> Total de filas a procesar: {total_rows}")

            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                try:
                    # Mostrar progreso cada 10 registros
                    if (row_idx - 1) % 10 == 0:
                        _logger.info(f">>> Procesando proyecto {row_idx - 1}/{total_rows}")

                    # Mapear los datos de la fila
                    data = dict(zip(headers.keys(), row))

                    # Obtener valores de las celdas
                    codigo = str(data.get('Codigo', '') or data.get('ID_Proyecto', '')).strip()
                    nombre = str(data.get('Nombre', '')).strip() if data.get('Nombre') else ''
                    cliente = str(data.get('ID_Cliente', '')).strip() if data.get('ID_Cliente') else ''
                    sujeto_convenio = data.get('Sujeto_Convenio', True)
                    departamento = str(data.get('ID_Departamento', '')).strip() if data.get('ID_Departamento') else ''
                    observaciones = str(data.get('Observaciones', '')).strip() if data.get('Observaciones') else ''
                    jefe_proyecto = str(data.get('Jefe_Proyecto', '')).strip() if data.get('Jefe_Proyecto') else ''
                    presupuesto = data.get('Presupuesto', 0)

                    print("*"*50)
                    print("Datos del proyecto:", data)
                    print("Código:", codigo)
                    print("Nombre:", nombre)
                    print("Cliente:", cliente)
                    print("sujeto_convenio:", sujeto_convenio)
                    print("departamento:", departamento)
                    print("observaciones:", observaciones)
                    print("jefe_proyecto:", jefe_proyecto)
                    print("presupuesto:", presupuesto)
                    print("*"*50)

                    # Validaciones básicas
                    if not nombre:
                        _logger.warning(f"Fila {row_idx}: Sin nombre de proyecto, saltando...")
                        result['errors'] += 1
                        result['error_list'].append(f"Fila {row_idx}: Sin nombre de proyecto")
                        continue

                    # Buscar cliente
                    partner_id = False
                    if cliente:
                        cliente = f"C{cliente}"
                        partner = self.env['res.partner'].search([
                            ('codigo_cliente', '=', cliente)
                        ], limit=1)
                        if partner:
                            partner_id = partner.id
                            print("Cliente encontrado por codigo_cliente:", partner.name)
                        else:
                            print("No se encontró cliente con codigo_cliente:", cliente)
                            cliente_not_found_count += 1
                    else:
                        print("No se proporcionó cliente para este proyecto")
                        cliente_not_found_count += 1

                    # Buscar departamento
                    department_id = False
                    if departamento is not None and departamento != '':
                        dep_code = str(departamento).zfill(2)
                        department = self.env['hr.department'].search([
                            ('name', 'ilike', f'{dep_code}-')
                        ], limit=1)
                        if department:
                            department_id = department.id
                            print("Departamento encontrado:", department.name)
                        else:
                            print("Departamento no encontrado:", departamento)

                    # Buscar empleado responsable por jefe_proyecto
                    responsible_user_id = False
                    if jefe_proyecto:
                        # Añadir "E" delante del código
                        codigo_empleado = f"E{jefe_proyecto}"
                        print(f"Buscando empleado con código: {codigo_empleado}")

                        # Buscar el empleado por codigo_empleado
                        employee = self.env['hr.employee'].search([
                            ('codigo_empleado', '=', codigo_empleado)
                        ], limit=1)

                        if employee:
                            print(f"Empleado encontrado: {employee.name}")
                            # Verificar si el empleado tiene usuario asociado
                            if employee.user_id:
                                responsible_user_id = employee.user_id.id
                                print(f"Usuario responsable asignado: {employee.user_id.name}")
                            else:
                                print(f"El empleado {employee.name} no tiene usuario asociado")
                                _logger.warning(f"El empleado {employee.name} (código {codigo_empleado}) no tiene usuario asociado para el proyecto {nombre}")
                        else:
                            print(f"No se encontró empleado con código: {codigo_empleado}")
                            _logger.warning(f"No se encontró empleado con código {codigo_empleado} para el proyecto {nombre}")

                    # Preparar valores para el proyecto (cuenta analítica)
                    project_vals = {
                        'name': nombre,
                        'sujeto_convenio': sujeto_convenio if sujeto_convenio is not None else False,
                        'plan_id': 1,  # Account Analytic Plan
                    }

                    if presupuesto:
                        try:
                            project_vals['presupuesto'] = float(presupuesto)
                        except ValueError:
                            _logger.warning(f"Presupuesto no válido para el proyecto {nombre}: '{presupuesto}'")


                    # Añadir código si existe
                    if codigo:
                        project_vals['code'] = codigo

                    # Añadir partner si se encontró
                    if partner_id:
                        project_vals['partner_id'] = partner_id

                    # Añadir observaciones si existen
                    if observaciones:
                        project_vals['observaciones'] = observaciones

                    # Añadir responsable si se encontró
                    if responsible_user_id:
                        project_vals['responsible_id'] = responsible_user_id

                    # Buscar proyecto existente por código o nombre
                    existing_project = None
                    if codigo:
                        existing_project = self.env['account.analytic.account'].search([
                            ('code', '=', codigo)
                        ], limit=1)


                    if not existing_project:
                        existing_project = self.env['account.analytic.account'].search([
                            ('name', '=', nombre)
                        ], limit=1)

                    # Crear o actualizar proyecto
                    if existing_project:
                        if self.update_existing:
                            existing_project.write(project_vals)
                            result['updated'] += 1
                            _logger.info(f"✓ Proyecto actualizado: {nombre}")
                        else:
                            _logger.debug(f"◷ Proyecto ya existe (no actualizado): {nombre}")
                    else:
                        self.env['account.analytic.account'].create(project_vals)
                        result['created'] += 1
                        _logger.info(f"✓ Proyecto creado: {nombre}")
                except Exception as e:
                    result['errors'] += 1
                    error_msg = f"Fila {row_idx}: {str(e)}"
                    result['error_list'].append(error_msg)
                    _logger.error(f"✗ Error procesando fila {row_idx}: {str(e)}")

        except Exception as e:
            result['errors'] += 1
            error_msg = f"Error general al procesar archivo: {str(e)}"
            result['error_list'].append(error_msg)
            _logger.error(f"✗ {error_msg}")

        print("/"*50)
        print("cliente_not_found_count:", cliente_not_found_count)
        print("/"*50)

        return result

    def _import_project_assignments(self, file_data):
        """Importa la relación entre proyectos y empleados desde un archivo Excel."""
        result = {
            'created': 0,
            'updated': 0,
            'errors': 0,
            'error_list': []
        }

        try:
            # Decodificar y cargar el archivo Excel
            file_content = b64decode(file_data)
            workbook = openpyxl.load_workbook(BytesIO(file_content))
            sheet = workbook.active

            # Obtener los encabezados de las columnas
            headers = {}
            for col_idx, cell in enumerate(sheet[1], start=1):
                if cell.value:
                    headers[cell.value.strip()] = col_idx

            _logger.info(f">>> Columnas encontradas: {list(headers.keys())}")

            # Validar que existen las columnas requeridas
            required_columns = ['ID_Proyecto', 'ID_Personal']
            missing_columns = [col for col in required_columns if col not in headers]
            if missing_columns:
                error_msg = f"Faltan columnas requeridas: {', '.join(missing_columns)}"
                result['errors'] += 1
                result['error_list'].append(error_msg)
                _logger.error(f"✗ {error_msg}")
                return result

            # Procesar las filas de datos (desde la fila 2)
            total_rows = sheet.max_row - 1
            _logger.info(f">>> Total de filas a procesar: {total_rows}")

            # Diccionario para agrupar empleados por proyecto
            project_employees = {}

            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                try:
                    # Mostrar progreso cada 10 registros
                    if (row_idx - 1) % 10 == 0:
                        _logger.info(f">>> Procesando asignación {row_idx - 1}/{total_rows}")

                    # Mapear los datos de la fila
                    data = dict(zip(headers.keys(), row))

                    # Obtener valores — float->int->str para evitar "123.0", preservando ceros a la izquierda si ya es str
                    def _to_str(v):
                        if v in (None, '', False):
                            return ''
                        if isinstance(v, float):
                            return str(int(v)).strip()
                        return str(v).strip()

                    id_proyecto = _to_str(data.get('ID_Proyecto'))
                    id_personal = _to_str(data.get('ID_Personal'))
                    id_departamento = _to_str(data.get('ID_Departamento'))
                    jefe_proyecto = _to_str(data.get('Jefe_Proyecto'))

                    _logger.info(f">>> Fila {row_idx}: ID_Proyecto={repr(data.get('ID_Proyecto'))} -> '{id_proyecto}' | ID_Personal={repr(data.get('ID_Personal'))} -> '{id_personal}' | Jefe_Proyecto={repr(data.get('Jefe_Proyecto'))} -> '{jefe_proyecto}'")

                    # Validaciones básicas
                    if not id_proyecto:
                        _logger.warning(f"Fila {row_idx}: Sin ID de proyecto, saltando...")
                        continue

                    if not id_personal:
                        _logger.warning(f"Fila {row_idx}: Sin ID de personal, saltando...")
                        continue

                    # Buscar el proyecto por código
                    project = self.env['account.analytic.account'].search([
                        ('code', '=', id_proyecto)
                    ], limit=1)

                    if not project:
                        error_msg = f"Fila {row_idx}: Proyecto con código '{id_proyecto}' no encontrado"
                        result['error_list'].append(error_msg)
                        _logger.warning(f"✗ {error_msg}")
                        continue

                    # Buscar el empleado por código (añadiendo "E" delante)
                    codigo_empleado = f"E{id_personal}"
                    employee = self.env['hr.employee'].search([
                        ('codigo_empleado', '=', codigo_empleado)
                    ], limit=1)

                    if not employee:
                        error_msg = f"Fila {row_idx}: Empleado con código '{codigo_empleado}' no encontrado"
                        result['error_list'].append(error_msg)
                        _logger.warning(f"✗ {error_msg}")
                        continue

                    # Agrupar proyectos con su jefe
                    if project.id not in project_employees:
                        project_employees[project.id] = {
                            'project': project,
                            'jefe_proyecto': None
                        }

                    # Jefe_Proyecto es un FLAG (0/1): si es '1', este ID_Personal es el jefe del proyecto
                    if jefe_proyecto == '1':
                        project_employees[project.id]['jefe_proyecto'] = id_personal
                        _logger.info(f">>> Fila {row_idx}: Empleado '{id_personal}' marcado como jefe del proyecto '{id_proyecto}'")

                    result['created'] += 1

                except Exception as e:
                    result['errors'] += 1
                    error_msg = f"Fila {row_idx}: Error procesando asignación: {str(e)}"
                    result['error_list'].append(error_msg)
                    _logger.error(f"✗ {error_msg}")

            # Ahora actualizar los proyectos con el responsable (jefe)
            for project_id, data in project_employees.items():
                try:
                    project = data['project']
                    jefe_proyecto = data.get('jefe_proyecto')

                    # Buscar y asignar el jefe de proyecto como responsable
                    if jefe_proyecto:
                        # Añadir "E" delante del código del jefe
                        codigo_jefe = f"E{jefe_proyecto}"
                        _logger.info(f">>> Buscando jefe de proyecto con código: {codigo_jefe}")

                        # Buscar el empleado jefe
                        jefe_employee = self.env['hr.employee'].search([
                            ('codigo_empleado', '=', codigo_jefe)
                        ], limit=1)

                        if jefe_employee:
                            # Verificar si el empleado tiene usuario asociado
                            if jefe_employee.user_id:
                                project.write({
                                    'responsible_id': jefe_employee.user_id.id
                                })

                                # Añadir el usuario al grupo "Jefe de Proyecto"
                                try:
                                    _logger.info(f">>> Intentando añadir usuario '{jefe_employee.user_id.name}' (ID: {jefe_employee.user_id.id}) al grupo 'Jefe de Proyecto'")

                                    group_project_boss = self.env.ref('aicia_portal_requests.group_project_boss', raise_if_not_found=False)

                                    if not group_project_boss:
                                        _logger.error(f"✗ No se encontró el grupo 'aicia_portal_requests.group_project_boss'")
                                    else:
                                        _logger.info(f">>> Grupo encontrado: {group_project_boss.name} (ID: {group_project_boss.id})")
                                        _logger.info(f">>> Grupos actuales del usuario: {jefe_employee.user_id.group_ids.mapped('name')}")

                                        if group_project_boss.id not in jefe_employee.user_id.group_ids.ids:
                                            _logger.info(f">>> El usuario NO tiene el grupo, añadiendo...")
                                            # Usar sudo() para asegurar permisos de escritura
                                            jefe_employee.user_id.sudo().write({
                                                'group_ids': [(4, group_project_boss.id)]
                                            })
                                            _logger.info(f"✓ Usuario '{jefe_employee.user_id.name}' añadido al grupo 'Jefe de Proyecto'")
                                            _logger.info(f">>> Grupos después de añadir: {jefe_employee.user_id.group_ids.mapped('name')}")
                                        else:
                                            _logger.info(f">>> El usuario YA tiene el grupo 'Jefe de Proyecto', no es necesario añadirlo")

                                        # Añadir SIEMPRE al grupo "Jefe de Equipo" (group_equip_boss)
                                        # El comando (4, id) no duplica de forma nativa en Odoo
                                        group_equip_boss = self.env.ref('aicia_portal_requests.group_equip_boss', raise_if_not_found=False)
                                        if not group_equip_boss:
                                            _logger.error(f"✗ No se encontró el grupo 'aicia_portal_requests.group_equip_boss'")
                                        else:
                                            jefe_employee.user_id.sudo().write({
                                                'group_ids': [(4, group_equip_boss.id)]
                                            })
                                            _logger.info(f"✓ Usuario '{jefe_employee.user_id.name}' asignado al grupo 'Jefe de Equipo'")

                                except Exception as e:
                                    _logger.error(f"✗ Error al añadir usuario '{jefe_employee.user_id.name}' al grupo 'Jefe de Proyecto': {str(e)}")
                                    import traceback
                                    _logger.error(f"Stack trace: {traceback.format_exc()}")

                                result['updated'] += 1
                                _logger.info(f"✓ Proyecto '{project.name}': Jefe '{jefe_employee.name}' asignado como responsable (usuario: {jefe_employee.user_id.name})")
                            else:
                                _logger.warning(f"⚠ Proyecto '{project.name}': El empleado jefe '{jefe_employee.name}' (código {codigo_jefe}) no tiene usuario asociado")
                        else:
                            _logger.warning(f"⚠ Proyecto '{project.name}': No se encontró empleado jefe con código {codigo_jefe}")

                except Exception as e:
                    result['errors'] += 1
                    project_name = data['project'].name if 'project' in data and data['project'] else 'Desconocido'
                    error_msg = f"Error actualizando proyecto {project_name}: {str(e)}"
                    result['error_list'].append(error_msg)
                    _logger.error(f"✗ {error_msg}")

        except Exception as e:
            result['errors'] += 1
            error_msg = f"Error general al procesar archivo: {str(e)}"
            result['error_list'].append(error_msg)
            _logger.error(f"✗ {error_msg}")
            import traceback
            _logger.error(f"Stack trace: {traceback.format_exc()}")

        return result

    def action_update_work_groups(self):
        """
        Recorre todos los empleados activos, toma el nombre de su departamento
        (quitando el '0' inicial si lo tuviera), busca el portal.work.group con
        ese nombre exacto y añade el user_id del empleado al campo user_ids del grupo.
        Muestra un resumen detallado en el log del wizard.
        """
        self.ensure_one()

        _logger.info("=" * 80)
        _logger.info("INICIO DE ACTUALIZACIÓN DE GRUPOS DE TRABAJO")
        _logger.info("=" * 80)

        employees = self.env['hr.employee'].search([('active', '=', True)])

        # Contadores por grupo: {group_name: [employee_names]}
        groups_updated = {}
        # Errores: lista de (employee_name, motivo)
        not_processed = []

        for employee in employees:
            emp_name = employee.name or ''

            # 1. Verificar que tiene departamento
            if not employee.department_id:
                motivo = "sin departamento asignado"
                not_processed.append((emp_name, motivo))
                _logger.warning(f"✗ {emp_name}: {motivo}")
                continue

            # 2. Normalizar nombre del departamento quitando '0' inicial
            dept_name = employee.department_id.name or ''
            search_name = dept_name.lstrip('0') if dept_name.startswith('0') else dept_name

            # 3. Buscar el grupo de trabajo con ese nombre exacto
            group = self.env['portal.work.group'].search([('name', '=', search_name)], limit=1)
            if not group:
                motivo = f"grupo no encontrado para departamento '{dept_name}'"
                not_processed.append((emp_name, motivo))
                _logger.warning(f"✗ {emp_name}: {motivo}")
                continue

            # 4. Verificar que el empleado tiene usuario en Odoo
            if not employee.user_id:
                motivo = f"empleado sin usuario Odoo (departamento: '{dept_name}')"
                not_processed.append((emp_name, motivo))
                _logger.warning(f"✗ {emp_name}: {motivo}")
                continue

            # 5. Añadir el usuario al grupo (el comando (4, id) no duplica)
            group.write({'user_ids': [(4, employee.user_id.id)]})
            if group.name not in groups_updated:
                groups_updated[group.name] = []
            groups_updated[group.name].append(emp_name)
            _logger.info(f"✓ {emp_name} → grupo '{group.name}'")

        # Construir el log HTML con el resumen
        lines = []
        lines.append("<h3>✅ Grupos actualizados</h3>")
        if groups_updated:
            for gname, emp_list in sorted(groups_updated.items()):
                lines.append(f"<b>{gname}</b> — {len(emp_list)} empleado(s) añadido(s):")
                lines.append("<ul>")
                for e in emp_list:
                    lines.append(f"<li>{e}</li>")
                lines.append("</ul>")
        else:
            lines.append("<p>Ningún empleado fue añadido a ningún grupo.</p>")

        lines.append("<h3>❌ No procesados</h3>")
        if not_processed:
            lines.append("<ul>")
            for emp_name, motivo in not_processed:
                lines.append(f"<li><b>{emp_name}</b>: {motivo}</li>")
            lines.append("</ul>")
        else:
            lines.append("<p>Todos los empleados han sido procesados correctamente.</p>")

        total_added = sum(len(v) for v in groups_updated.values())
        lines.append(
            f"<hr/><p><b>Resumen:</b> {total_added} empleado(s) añadido(s) a "
            f"{len(groups_updated)} grupo(s). {len(not_processed)} no procesado(s).</p>"
        )

        self.write({
            'import_log': '\n'.join(lines),
            'state': 'done',
        })
        _logger.info("FIN DE ACTUALIZACIÓN DE GRUPOS DE TRABAJO")
        _logger.info("=" * 80)

    def action_update_project_bosses(self):
        """
        Recorre todos los proyectos (account.analytic.account) con responsible_id
        y añade ese usuario al grupo 'Jefe de Equipo' (aicia_portal_requests.group_equip_boss).
        Muestra un resumen detallado en el log del wizard.
        """
        self.ensure_one()

        _logger.info("=" * 80)
        _logger.info("INICIO DE ACTUALIZACIÓN DE JEFES DE EQUIPO POR PROYECTO")
        _logger.info("=" * 80)

        # Obtener el grupo "Jefe de Equipo"
        group_equip_boss = self.env.ref('aicia_portal_requests.group_equip_boss', raise_if_not_found=False)
        if not group_equip_boss:
            self.write({
                'import_log': '<p style="color:red;">❌ No se encontró el grupo '
                              '<b>aicia_portal_requests.group_equip_boss</b>. '
                              'Verifica que el módulo portal_requests está instalado correctamente.</p>',
                'state': 'done',
            })
            return

        # Buscar todos los proyectos con responsible_id asignado
        projects = self.env['account.analytic.account'].search([
            ('responsible_id', '!=', False)
        ])

        _logger.info(f">>> Proyectos con responsable encontrados: {len(projects)}")

        updated = []        # [(project_name, user_name)] — usuarios nuevos en el grupo
        already_had = []    # [(project_name, user_name)] — ya tenían el grupo
        no_group = []       # [(project_name, user_name, motivo)] — sin grupo de trabajo
        group_assigned = [] # [(project_name, user_name, group_name)] — equip_boss asignado

        for project in projects:
            user = project.responsible_id
            # Comprobar si ya tenía el grupo (solo para el informe)
            already = group_equip_boss.id in user.group_ids.ids
            # Asignar siempre — el comando (4, id) no duplica de forma nativa en Odoo
            user.sudo().write({'group_ids': [(4, group_equip_boss.id)]})
            if already:
                already_had.append((project.name, user.name))
                _logger.info(f"→ Proyecto '{project.name}': '{user.name}' ya tenía el grupo")
            else:
                updated.append((project.name, user.name))
                _logger.info(f"✓ Proyecto '{project.name}': '{user.name}' añadido al grupo 'Jefe de Equipo'")

            # Buscar el empleado ligado a este usuario para obtener su departamento
            employee = self.env['hr.employee'].search([
                ('user_id', '=', user.id),
                ('active', '=', True),
            ], limit=1)

            if not employee or not employee.department_id:
                no_group.append((project.name, user.name, "empleado sin departamento o no encontrado"))
                _logger.warning(f"⚠ Proyecto '{project.name}': '{user.name}' sin departamento, no se asigna equip_boss")
                continue

            # Normalizar nombre del departamento quitando '0' inicial
            dept_name = employee.department_id.name or ''
            search_name = dept_name.lstrip('0') if dept_name.startswith('0') else dept_name

            # Buscar el grupo de trabajo por nombre exacto
            work_group = self.env['portal.work.group'].search([('name', '=', search_name)], limit=1)
            if not work_group:
                no_group.append((project.name, user.name, f"grupo de trabajo '{search_name}' no encontrado"))
                _logger.warning(f"⚠ Proyecto '{project.name}': grupo '{search_name}' no encontrado")
                continue

            # Asignar como equip_boss del grupo
            work_group.write({'equip_boss': user.id})
            group_assigned.append((project.name, user.name, work_group.name))
            _logger.info(f"✓ Proyecto '{project.name}': '{user.name}' asignado como equip_boss en grupo '{work_group.name}'")

        # Construir el log HTML con el resumen
        lines = []
        lines.append("<h3>✅ Usuarios añadidos al grupo 'Jefe de Equipo'</h3>")
        if updated:
            lines.append("<ul>")
            for pname, uname in updated:
                lines.append(f"<li><b>{pname}</b> → {uname}</li>")
            lines.append("</ul>")
        else:
            lines.append("<p>Ningún usuario nuevo fue añadido al grupo.</p>")

        if already_had:
            lines.append("<h3>ℹ️ Ya tenían el grupo</h3>")
            lines.append("<ul>")
            for pname, uname in already_had:
                lines.append(f"<li><b>{pname}</b> → {uname}</li>")
            lines.append("</ul>")

        if no_group:
            lines.append("<h3>⚠️ Sin asignación de equip_boss</h3>")
            lines.append("<ul>")
            for pname, uname, motivo in no_group:
                lines.append(f"<li><b>{pname}</b> → {uname}: {motivo}</li>")
            lines.append("</ul>")

        if group_assigned:
            lines.append("<h3>👑 Asignados como equip_boss en su grupo de trabajo</h3>")
            lines.append("<ul>")
            for pname, uname, gname in group_assigned:
                lines.append(f"<li><b>{pname}</b> → {uname} → grupo <b>{gname}</b></li>")
            lines.append("</ul>")

        lines.append(
            f"<hr/><p><b>Resumen:</b> {len(updated)} usuario(s) añadido(s) al grupo Jefe de Equipo, "
            f"{len(already_had)} ya lo tenían, {len(group_assigned)} asignado(s) como equip_boss, "
            f"{len(no_group)} sin asignación de grupo. Total proyectos: {len(projects)}.</p>"
        )

        self.write({
            'import_log': '\n'.join(lines),
            'state': 'done',
        })
        _logger.info("FIN DE ACTUALIZACIÓN DE JEFES DE EQUIPO POR PROYECTO")
        _logger.info("=" * 80)

    def action_assign_project_work_groups(self):
        """
        Recorre todos los proyectos (account.analytic.account) que tienen
        responsible_id asignado pero NO tienen work_group_id establecido.
        Para cada uno busca el empleado vinculado al usuario responsable,
        toma su departamento (quitando el '0' inicial si lo tuviera),
        busca el portal.work.group con ese nombre exacto y escribe
        work_group_id en la cuenta analítica.
        Muestra un resumen detallado en el log del wizard.
        """
        self.ensure_one()

        _logger.info("=" * 80)
        _logger.info("INICIO DE ASIGNACIÓN DE GRUPOS DE TRABAJO A PROYECTOS")
        _logger.info("=" * 80)

        # Solo proyectos con responsable y SIN grupo de trabajo asignado
        projects = self.env['account.analytic.account'].search([
            ('responsible_id', '!=', False),
            ('work_group_id', '=', False),
        ])

        _logger.info(f">>> Proyectos con responsable y sin grupo encontrados: {len(projects)}")

        assigned = []       # [(project_name, user_name, group_name)]
        no_employee = []    # [(project_name, user_name)]
        no_department = []  # [(project_name, user_name)]
        no_group = []       # [(project_name, user_name, dept_name)]

        for project in projects:
            user = project.responsible_id
            pname = project.name or ''
            uname = user.name or ''

            # 1. Buscar el empleado activo vinculado al usuario responsable
            employee = self.env['hr.employee'].search([
                ('user_id', '=', user.id),
                ('active', '=', True),
            ], limit=1)

            if not employee:
                no_employee.append((pname, uname))
                _logger.warning(
                    f"✗ Proyecto '{pname}': responsable '{uname}' "
                    f"no tiene empleado activo asociado"
                )
                continue

            # 2. Verificar que el empleado tiene departamento
            if not employee.department_id:
                no_department.append((pname, uname))
                _logger.warning(
                    f"✗ Proyecto '{pname}': empleado '{employee.name}' "
                    f"sin departamento asignado"
                )
                continue

            # 3. Normalizar nombre del departamento quitando '0' inicial
            dept_name = employee.department_id.name or ''
            search_name = dept_name.lstrip('0') if dept_name.startswith('0') else dept_name

            # 4. Buscar el grupo de trabajo por nombre exacto
            work_group = self.env['portal.work.group'].search([
                ('name', '=', search_name)
            ], limit=1)

            if not work_group:
                no_group.append((pname, uname, dept_name))
                _logger.warning(
                    f"✗ Proyecto '{pname}': grupo de trabajo '{search_name}' "
                    f"(departamento '{dept_name}') no encontrado"
                )
                continue

            # 5. Asignar el grupo al proyecto
            project.write({'work_group_id': work_group.id})
            assigned.append((pname, uname, work_group.name))
            _logger.info(
                f"✓ Proyecto '{pname}': responsable '{uname}' → "
                f"grupo '{work_group.name}' asignado"
            )

        # Construir el log HTML con el resumen
        lines = []
        lines.append("<h3>✅ Proyectos con grupo asignado</h3>")
        if assigned:
            lines.append("<ul>")
            for pname, uname, gname in assigned:
                lines.append(
                    f"<li><b>{pname}</b> → responsable: {uname} "
                    f"→ grupo: <b>{gname}</b></li>"
                )
            lines.append("</ul>")
        else:
            lines.append("<p>Ningún proyecto fue actualizado.</p>")

        if no_employee:
            lines.append("<h3>⚠️ Sin empleado asociado al responsable</h3>")
            lines.append("<ul>")
            for pname, uname in no_employee:
                lines.append(f"<li><b>{pname}</b> → responsable: {uname}</li>")
            lines.append("</ul>")

        if no_department:
            lines.append("<h3>⚠️ Empleado sin departamento</h3>")
            lines.append("<ul>")
            for pname, uname in no_department:
                lines.append(f"<li><b>{pname}</b> → responsable: {uname}</li>")
            lines.append("</ul>")

        if no_group:
            lines.append("<h3>⚠️ Grupo de trabajo no encontrado</h3>")
            lines.append("<ul>")
            for pname, uname, dname in no_group:
                lines.append(
                    f"<li><b>{pname}</b> → responsable: {uname} "
                    f"→ departamento: {dname}</li>"
                )
            lines.append("</ul>")

        lines.append(
            f"<hr/><p><b>Resumen:</b> {len(assigned)} proyecto(s) con grupo asignado. "
            f"{len(no_employee)} sin empleado, {len(no_department)} sin departamento, "
            f"{len(no_group)} sin grupo encontrado. "
            f"Total proyectos procesados: {len(projects)}.</p>"
        )

        self.write({
            'import_log': '\n'.join(lines),
            'state': 'done',
        })
        _logger.info(
            f"FIN DE ASIGNACIÓN DE GRUPOS A PROYECTOS — "
            f"{len(assigned)} asignados, {len(no_employee) + len(no_department) + len(no_group)} sin asignar"
        )
        _logger.info("=" * 80)

