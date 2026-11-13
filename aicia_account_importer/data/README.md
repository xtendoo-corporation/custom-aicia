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
| 6        | Importe_Total      | Entero (céntimos) | `121000`         | No es el total: solo se compara con la suma de las líneas y se anota en el log si difiere |
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
| 2        | Cuenta_Contable  | Texto (9 dígitos) | `"610003495"` | 5 primeros + 0 = cuenta, 4 últimos = contacto |
| 3        | ID_Departamento  | Entero            | `0`           | No se importa                               |
| 4        | ID_Proyecto      | Entero            | `0`           | No se importa                               |
| 5        | Descripcion      | Texto             | `"Cliente A"` | `name` de la línea del asiento              |
| 6        | Importe          | Entero (céntimos) | `21982`       | Se divide entre 100 → `219,82 €`            |
| 7        | Tipo_Contable    | Texto `D` o `H`   | `"D"`         | `D`=Debe (debit) / `H`=Haber (credit)       |

- Filas totales aprox.: **47.606**

---

## Cuenta y contacto de cada línea

Los códigos de cuenta tienen **9 dígitos** en el sistema legado y se dividen así:

| Dígitos              | Significado                               | Ejemplo `610003495`          |
|----------------------|-------------------------------------------|------------------------------|
| 5 primeros + un `0`  | Cuenta contable de Odoo                   | cuenta `610000`              |
| 4 últimos            | **Código AICIA** del contacto de la línea | contacto con el código `3495`|

- No hay cuentas colectivas, ni redirección de grupos, ni búsqueda por prefijo:
  si no existe la cuenta de 6 dígitos, el asiento da error y el código se añade
  al **Mapeo de cuentas** (sin destino) para poder asignarle una cuenta.
- El código se define en el contacto, pestaña **Códigos AICIA**. Un contacto
  puede tener varios códigos. El código es **único por tipo de tercero**:
  el `495` de un empleado y el `495` de un proveedor son contactos distintos.
  Los ceros a la izquierda no cuentan (`0495` = `495`).
- El tipo se deduce del grupo de la cuenta (3 primeros dígitos):

  | Tipo      | Grupos de cuenta         |
  |-----------|--------------------------|
  | Personal  | 460, 465, 610, 611, 616, 618 |
  | Proveedor | 400, 401, 410            |
  | Cliente   | 430, 431, 436            |

  Se cambia en `PARTNER_TYPE_BY_ACCOUNT_GROUP` (`wizard/aicia_account_importer_wizard.py`).
  Las líneas de cualquier otro grupo (bancos 572, gastos, ingresos…) no llevan contacto.
- **Cuentas sin socio.** Por criterio contable algunas cuentas de los grupos de tercero
  no llevan contacto. Se definen en *Importación contable → Cuentas sin socio* (cuenta de
  9 dígitos o prefijo). Para esas líneas no se busca contacto ni se avisa. Por defecto hay
  11 reglas (pendientes de confirmar con el contable):
  - 7 cuentas generales con código 0, importadas con 6 dígitos: `430000000`, `401000000`,
    `400000000`, `436000000`, `616000000`, `610000000`, `465000000`.
  - 4 cuentas especiales que **no son un tercero**, importadas con los **9 dígitos** como
    cuenta de Odoo (se crean si no existen): `618000200`, `401000200`, `401000300`,
    `401000400`. Sin esta regla tomarían el contacto que casualmente tiene el código 200,
    300 o 400.
- Si no existe ningún contacto con ese código y tipo, la línea se importa sin
  contacto, el asiento queda en **borrador** y se lista en el log. No se crean contactos.
- El **Mapeo de cuentas** es opcional y está vacío por defecto: sirve para forzar
  que un código legado (exacto o por prefijo) vaya a otra cuenta de Odoo.

## Totales

El total de un asiento es **la suma de sus líneas**, calculada en céntimos
enteros (un céntimo de diferencia entre Debe y Haber ya es un descuadre).
`Importe_Total` de la cabecera no se usa como total: si no coincide con la suma
de las líneas, el asiento se importa igual (con la suma de sus líneas) y la
diferencia solo se anota en el apartado informativo "Total de cabecera distinto
de la suma de líneas" del log. El resumen muestra además el total Debe y Haber
importados.

## Uso del wizard

1. Ve a **Contabilidad → AICIA - Importación → Importar Apuntes Contables**.
2. Selecciona el diario contable destino.
3. Sube `Apuntes2025.xlsx` en el primer campo y `Lineas_Apunte2025.xlsx` en el segundo.
4. Elige si los asientos se crean en borrador o se confirman directamente.
5. Activa "Omitir asientos anulados" si lo deseas.
6. Pulsa **Importar**.

Antes de importar, carga los códigos AICIA (con su tipo) en los contactos.

El log HTML al final resume: asientos creados ✅, omitidos ⚠️, avisos (borrador) y errores ❌, con los totales Debe/Haber.
