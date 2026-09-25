# Carpeta de datos – aicia_account_importer

Esta carpeta contiene los ficheros Excel del sistema legado que se importan
mediante el módulo `aicia_account_importer`.

> **Nota:** Los archivos `.xlsx`, `.xls` y `.csv` están excluidos del repositorio
> (ver `.gitignore`). Cópialos manualmente antes de usarlos.

---

## Archivo 1 – `Apuntes2025.xlsx`

Contiene las **cabeceras** de los asientos contables.

| Posición | Columna            | Tipo              | Ejemplo          | Notas                           |
|----------|--------------------|-------------------|------------------|---------------------------------|
| 0        | ID_Apunte          | Entero            | `12345`          | Clave de unión con Lineas       |
| 1        | Numero_Apunte      | Entero            | `100`            | Usado como `ref` en Odoo        |
| 2        | Fecha_Contable     | Entero YYYYMMDD   | `20250103`       | Se convierte a `date`           |
| 3        | Fecha_Introduccion | Entero YYYYMMDD   | `20250104`       | No se importa                   |
| 4        | Descripcion        | Texto             | `"Venta enero"`  | `narration` del asiento         |
| 5        | Numero_Documento   | Texto             | `"DOC-001"`      | Campo informativo                |
| 6        | Importe_Total      | Entero (céntimos) | `121000`         | Solo referencial, no se importa |
| 7        | Validado           | Booleano          | `True`           | Solo se importan los `True`     |
| 8        | Anulado            | Booleano          | `False`          | Se omiten los `True` si activo  |
| 9        | Clase_Apunte       | Texto             | `"R"`            | No se importa                   |

- Filas totales aprox.: **10.779**
- Solo se procesan las filas con `Validado=True` (y `Anulado=False` si el
  check `skip_anulados` está activado en el wizard).

---

## Archivo 2 – `Lineas_Apunte2025.xlsx`

Contiene las **líneas** de cada asiento contable.

| Posición | Columna          | Tipo              | Ejemplo       | Notas                                       |
|----------|------------------|-------------------|---------------|---------------------------------------------|
| 0        | ID_Apunte        | Entero            | `12345`       | Clave de unión con Apuntes                  |
| 1        | ID_Linea         | Entero            | `1`           | No se importa                               |
| 2        | Cuenta_Contable  | Texto (9 dígitos) | `"430003604"` | Ver reglas de normalización abajo           |
| 3        | ID_Departamento  | Entero            | `0`           | No se importa                               |
| 4        | ID_Proyecto      | Entero            | `0`           | No se importa                               |
| 5        | Descripcion      | Texto             | `"Cliente A"` | `name` de la línea del asiento              |
| 6        | Importe          | Entero (céntimos) | `21982`       | Se divide entre 100 → `219,82 €`            |
| 7        | Tipo_Contable    | Texto `D` o `H`   | `"D"`         | `D`=Debe (debit) / `H`=Haber (credit)       |

- Filas totales aprox.: **47.606**

---

## Reglas de normalización de cuentas

Los códigos de cuenta tienen **9 dígitos** en el sistema legado.
El módulo los normaliza al plan contable español (6 dígitos) así:

| Prefijo legado | Cuenta Odoo | Nombre                               | Tipo Odoo            |
|----------------|-------------|--------------------------------------|----------------------|
| `400xxxxxx`    | `400000`    | Proveedores                          | `liability_payable`  |
| `401xxxxxx`    | `400000`    | Proveedores (acreedores varios)      | `liability_payable`  |
| `430xxxxxx`    | `430000`    | Clientes                             | `asset_receivable`   |
| `431xxxxxx`    | `430000`    | Clientes (efectos)                   | `asset_receivable`   |
| `436xxxxxx`    | `430000`    | Clientes (dudoso cobro)              | `asset_receivable`   |
| `572xxxxxx`    | `572000`    | Bancos e instituciones de crédito    | `asset_cash`         |
| Otras cuentas  | Trunca a 6  | Búsqueda en `account.account`        | —                    |

> Las cuentas colectivas (400000, 430000, 572000) se crean automáticamente si
> no existen en el plan contable de la compañía activa.

---

## Uso del wizard

1. Ve a **Contabilidad → AICIA - Importación → Importar Apuntes Contables**.
2. Selecciona el diario contable destino.
3. Sube `Apuntes2025.xlsx` en el primer campo y `Lineas_Apunte2025.xlsx` en el segundo.
4. Elige si los asientos se crean en borrador o se confirman directamente.
5. Activa "Omitir asientos anulados" si lo deseas.
6. Pulsa **Importar**.

El log HTML al final resume: asientos creados ✅, omitidos ⚠️ y errores ❌.
