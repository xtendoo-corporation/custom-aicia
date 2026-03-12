# aicia_account_payment_split

## Descripción

Módulo Odoo 19 Enterprise que automatiza el reparto de cobros mediante plantillas
configurables. Al postear un pago que tenga una plantilla de reparto seleccionada, se
genera un asiento contable adicional (tipo `entry`) que distribuye un porcentaje del
importe cobrado según las líneas de la plantilla.

**La factura queda pagada al 100%**: el módulo NO altera importes ni conciliación del
asiento del pago ni de la factura. Además, cuando el pago proviene de facturas con
`analytic_distribution`, esa distribución se propaga al asiento del pago y se usa como
fallback en el asiento adicional de reparto.

## Instalación

1. Copiar la carpeta `aicia_account_payment_split` en el directorio de addons custom.
2. Actualizar la lista de módulos: **Aplicaciones → Actualizar lista de módulos**.
3. Buscar **"Payment Split"** o **"Reparto"** e instalar.

### Dependencias

- `account` (Contabilidad)
- `account_accountant` (Contabilidad - Enterprise)
- `analytic` (Analítica)

## Configuración

### 1. Crear una Plantilla de Reparto

Menú: **Contabilidad → Configuración → Reparto de Cobros → Plantillas de Reparto**

1. Click en **Crear**.
2. Rellenar:
   - **Nombre**: nombre descriptivo (ej: "Reparto 10% por proyecto").
   - **Diario de Reparto**: un diario de tipo **Miscelánea/General** donde se crearán
     los asientos.
   - **Cuenta Origen (Debe)**: la cuenta de clearing/origen (ej: 57200000).
   - **Porcentaje Base**: el % del cobro que se reparte (ej: 10 = 10%).
   - **Modo de Cálculo**:
     - **Líneas suman 100%**: las líneas definen cómo se reparte el total. Ejemplo:
       Base=10%, Línea A=60%, Línea B=40% → De 1000€, se reparten 100€ (60€+40€).
     - **Líneas suman el % base**: las líneas indican directamente su porcentaje sobre
       el pago. Ejemplo: Base=10%, Línea A=4%, Línea B=3%, Línea C=3% → De 1000€, se
       reparten 100€.

3. Añadir **Líneas de Reparto** con:
   - Descripción
   - Cuenta destino (Haber)
   - Porcentaje
   - (Opcional) Cuenta analítica / Distribución analítica

4. **Guardar**.

### 2. Configurar Sugerencia Automática (Opcional)

Si deseas que la plantilla se sugiera automáticamente al pagar facturas de un proyecto
concreto:

1. En la plantilla, campo **Cuenta Analítica por Defecto**: seleccionar la cuenta
   analítica del proyecto.
2. **Prioridad**: si hay varias plantillas para la misma analítica, la de mayor
   prioridad gana.

## Uso Funcional

### Flujo Normal

1. **Crear/Abrir un pago** de cliente (Contabilidad → Clientes → Pagos).
2. En el formulario del pago (en estado borrador):
   - El campo **Plantilla de Reparto** aparece en el grupo derecho.
   - Si hay facturas asociadas con analítica que coincide con una plantilla, se sugiere
     automáticamente.
   - El usuario puede cambiar la plantilla o vaciar el campo.
3. **Postear** el pago (botón **Confirmar**).
4. Si hay plantilla seleccionada:
   - Se crea un asiento contable de reparto en el diario configurado.
   - El asiento se publica automáticamente.
    - Si las líneas de la plantilla no traen analítica explícita, heredarán la
      `analytic_distribution` de la factura pagada.
   - Aparece un **botón inteligente** "Asiento Reparto" en el pago.
5. En la **factura**, aparece un botón "Repartos" que muestra los logs de reparto.

### Cancelación

Al cancelar un pago que tiene asiento de reparto:

- Se genera automáticamente un **asiento inverso** del reparto.
- El log de auditoría se marca como "Revertido".

### Multi-Currency

Si el pago es en una moneda distinta a la de la compañía:

- Las líneas del asiento llevan `amount_currency` en la moneda del pago.
- El `balance` se calcula en moneda de la compañía por conversión a fecha del pago.
- Se ajusta la última línea para evitar errores de redondeo.

### Logs de Auditoría

Menú: **Contabilidad → Configuración → Reparto de Cobros → Logs de Reparto**

Los logs registran:

- Pago, plantilla, asiento generado
- Importes en moneda del pago y moneda de la compañía
- Facturas afectadas
- Estado (Publicado / Revertido)

## Estructura del Módulo

```
aicia_account_payment_split/
├── __init__.py
├── __manifest__.py
├── DESIGN.md
├── README.md
├── models/
│   ├── __init__.py
│   ├── account_move.py
│   ├── account_payment.py
│   ├── account_payment_split_log.py
│   ├── account_payment_split_template.py
│   └── account_payment_split_template_line.py
├── security/
│   ├── account_payment_split_security.xml
│   └── ir.model.access.csv
├── tests/
│   ├── __init__.py
│   └── test_payment_split.py
└── views/
    ├── account_move_views.xml
    ├── account_payment_split_log_views.xml
    ├── account_payment_split_template_views.xml
    ├── account_payment_views.xml
    └── menus.xml
```
