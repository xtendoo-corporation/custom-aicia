# AICIA - Importador de Clientes, Proveedores, Empleados y Proyectos

## Descripción

Este módulo permite importar proveedores, clientes, empleados y proyectos a Odoo 19.0 desde archivos Excel (.xlsx).

## Características

- Importación masiva de proveedores, clientes, empleados y proyectos desde archivos Excel
- Opción para actualizar contactos/proyectos existentes
- Importación de datos de contacto (teléfono, email, dirección)
- Creación de personas de contacto asociadas
- Validación de NIF/CIF con código de país
- Registro detallado de resultados de importación
- Importación de proyectos (cuentas analíticas) con asociación a clientes

## Instalación

### Requisitos

Este módulo requiere la librería Python `openpyxl`. Para instalarla:

```bash
pip install openpyxl
```

### Instalación del módulo

1. Copiar el módulo en el directorio de addons de Odoo
2. Actualizar la lista de módulos
3. Instalar el módulo "AICIA - Importador de Proveedores"

## Uso

### Importar Proveedores
1. Ir al menú: **Compras > AICIA > Importar Proveedores**
2. Seleccionar el archivo Excel (.xlsx) de proveedores
3. Marcar la opción "Actualizar existentes" si desea actualizar contactos que ya existen
4. Hacer clic en "Importar"

### Importar Clientes
1. Ir al menú: **Ventas > AICIA > Importar Clientes**
2. Seleccionar el archivo Excel (.xlsx) de clientes
3. Marcar la opción "Actualizar existentes" si desea actualizar contactos que ya existen
4. Hacer clic en "Importar"

### Importar Personal
1. Ir al menú: **Empleados > AICIA > Importar Personal**
2. Seleccionar el archivo Excel (.xlsx) de personal
3. Marcar la opción "Actualizar existentes" si desea actualizar empleados que ya existen
4. Hacer clic en "Importar"

### Importar Proyectos
1. Ir al menú: **Contabilidad > AICIA > Importar Proyectos**
2. Seleccionar el archivo Excel (.xlsx) de proyectos
3. Marcar la opción "Actualizar existentes" si desea actualizar proyectos que ya existen
4. Hacer clic en "Importar"

## Formato del archivo Excel

Los archivos deben tener la siguiente estructura:

### Archivo de Proveedores

#### Primera fila: Encabezados

- **ID_Proveedor**: Referencia interna del proveedor
- **Nombre**: Nombre del proveedor (obligatorio)
- **Nombre2**: Segundo nombre o razón social adicional
- **CIF**: NIF/CIF del proveedor
- **Telefono**: Teléfono principal
- **TelefonoMovil**: Teléfono móvil
- **Fax**: Número de fax
- **Direccion**: Dirección principal
- **Direccion2**: Dirección adicional
- **Localidad**: Ciudad
- **Cod_Postal**: Código postal
- **ID_Pais**: ID del país (no utilizado, se asume España por defecto)
- **Correo_Electronico**: Email
- **Persona_Contacto**: Nombre de la persona de contacto
- **Observaciones**: Comentarios
- **Observaciones2**: Comentarios adicionales

### Filas siguientes: Datos de proveedores

Cada fila representa un proveedor a importar.

### Archivo de Clientes

El formato es similar al de proveedores, pero usa **ID_Cliente** en lugar de **ID_Proveedor**:

- **ID_Cliente**: Referencia interna del cliente
- **Nombre**: Nombre del cliente (obligatorio)
- **Nombre2**: Segundo nombre o razón social adicional
- **CIF**: NIF/CIF del cliente
- Y todos los demás campos como en proveedores...

### Archivo de Proyectos

#### Primera fila: Encabezados

- **Codigo** (o **ID_Proyecto**): Código único del proyecto (opcional)
- **Nombre**: Nombre del proyecto (obligatorio)
- **Cliente**: Nombre o referencia del cliente asociado (opcional)
- **Activo**: TRUE/FALSE o 1/0 para indicar si el proyecto está activo (opcional, por defecto TRUE)

#### Filas siguientes: Datos de proyectos

Cada fila representa un proyecto a importar.

**Nota:** Los proyectos se almacenan internamente como cuentas analíticas en Odoo, pero se muestran como "Proyectos" en la interfaz.

## Lógica de importación

- Si el contacto ya existe (por referencia o CIF), se actualiza solo si la opción "Actualizar existentes" está marcada
- Si no existe, se crea un nuevo contacto
- Los proveedores se marcan automáticamente como "Es un proveedor"
- Los clientes se marcan automáticamente como "Es un cliente"
- Si hay persona de contacto, se crea como contacto hijo
- El NIF/CIF se ajusta automáticamente con el prefijo "ES" si no tiene código de país
- Los teléfonos fijo y móvil se concatenan en un solo campo si ambos existen

## Autor

Xtendoo - https://www.xtendoo.es/

## Licencia

AGPL-3

