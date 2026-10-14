# Migración contable AICIAWIN → Odoo: procedimiento repetible

Sirve para el ejercicio 2025 y para cualquier otro (p. ej. 2026): solo cambian el
`General.mdb` y los Excel del ejercicio. Todo lo que genera `aicia_migracion.py` sale de
los datos de origen, así que se puede repetir las veces que haga falta.

## Qué necesitas

| Fichero | De dónde sale |
|---|---|
| `General.mdb` | Base general de AICIAWIN (proveedores, clientes, facturas). |
| `Apuntes.xlsx` y `Lineas_Apunte.xlsx` | Exportación del ejercicio (base anual). Deben incluir todo el año. |
| `Personal.xlsx` | Personal del ejercicio (para los códigos de personal). |

Herramientas: `mdbtools` (`mdb-export`) y `openpyxl`. Si no tienes mdbtools, exporta las
tablas del mdb a CSV y usa `--csv-dir carpeta` en lugar de `--mdb`.

## Pasos

1. **Terceros** (el importador de terceros ya es idempotente: los existentes se actualizan):
   ```bash
   python3 aicia_migracion.py terceros --mdb General.mdb --out salida/
   ```
   En Odoo: *Compras/Ventas → AICIA → Importar* con `Proveedores.xlsx` y `Clientes.xlsx` y
   **"Actualizar existentes" activado**. Crea los terceros nuevos y actualiza los datos
   (incluida la cuenta contable de AICIAWIN). El NIF se guarda sin el correlativo " n" (el correlativo no se conserva; cada código sigue siendo un contacto distinto).

2. **Códigos de personal** (si hay altas): *Importación contable → Códigos AICIA* con el
   `Personal.xlsx` (simular antes). Lo que no empareje se asigna a mano.

3. **Códigos de proveedor y cliente**: botón *Cargar códigos de proveedor y cliente* (solo añade).
   El importador de terceros ya añade el código de cada alta nueva; este botón sirve para las
   bases cargadas antes de los códigos.

   **Un contacto por NIF** (solo para dejar el estado inicial; con copia de seguridad, porque
   es irreversible). Desde un shell de Odoo:
   ```python
   env['aicia.partner.code'].merge_partners_by_nif(dry_run=True)    # cuenta grupos y contactos
   env['aicia.partner.code'].merge_partners_by_nif(dry_run=False, commit_every=20)
   env.cr.commit()
   ```
   Confirma cada 20 grupos: si se corta, se repite y continúa donde se quedó. Se salta los NIF
   de relleno, los extranjeros y los grupos con empleados o usuarios. Los 765 grupos de 2025
   tardaron unos 17 minutos.

4. **Socio por asiento** (a partir de las facturas del ejercicio):
   ```bash
   python3 aicia_migracion.py asiento-socio --mdb General.mdb \
       --apuntes Apuntes.xlsx --year 2025 --out asiento_socio.xlsx
   ```
   Comprueba el resumen: la fecha de la factura debe coincidir con la del apunte en casi todas
   (si no, el `Apuntes.xlsx` no es del mismo ejercicio que las facturas).

5. **Importar los asientos**: *Importación contable → Importador de apuntes* con
   `Apuntes.xlsx`, `Lineas_Apunte.xlsx` y `asiento_socio.xlsx` en el campo opcional. Si ya
   había asientos importados y quieres rehacerlos, usa antes *Eliminar asientos importados*
   (los existentes se omiten, no se actualizan). La importación es **una sola transacción**
   (unos 70 minutos para ~10.800 asientos): no reinicies el contenedor mientras corre.

6. **Conciliación**: exporta las líneas importadas (`odoo_lines.sql` es la consulta; devuelve,
   por línea, todos los códigos AICIA de su contacto) y genera el informe.
   ```bash
   docker compose exec -T db psql -U odoo -d <base> \
       -c "\copy ($(tr '\n' ' ' < odoo_lines.sql)) to stdout csv header" > odoo_lines.csv
   python3 aicia_migracion.py conciliacion --mdb General.mdb \
       --apuntes Apuntes.xlsx --lineas Lineas_Apunte.xlsx \
       --odoo-lines odoo_lines.csv --asiento-socio asiento_socio.xlsx --out conciliacion.xlsx
   ```
   Sin docker: `psql -U odoo -d <base> -c "\copy (...) to stdout csv header" > odoo_lines.csv`.

## Criterio de aceptación

El informe debe decir: mismos asientos y líneas que AICIAWIN, Debe = Haber, **0 cuentas con
diferencia de saldo**, 0 líneas con socio distinto del esperado, 0 líneas que faltan o sobran.
Las líneas *inferidas* (cuentas compartidas sin factura, cuentas antiguas) no se pueden
confirmar con los datos de origen y se enseñan al contable. Resultado de 2025: 10.813
asientos, 47.726 líneas, Debe = Haber = 91.907.353,30 €, 463 líneas inferidas.

## Decisiones ya tomadas (ver también `data/README.md`)

- Cuenta de Odoo = 5 primeros dígitos de la cuenta legada + "0"; los 4 últimos son el código AICIA del contacto.
- Un contacto por NIF, con todos los códigos AICIA de la entidad (cada uno con su denominación y dirección).
- Cuentas compartidas por varios socios: el asiento con factura va al socio exacto de la
  factura; sin factura, al titular de la cuenta (el código que coincide con el número).
- Cuentas "sin socio" (14 reglas, incluidas la 430000000 y los anticipos de personal a cero).
- Las facturas **no se importan**: solo sirven para saber a qué socio va cada asiento.
- Si un código de personal de la apertura no existe, se crea el contacto desde la ficha de alta
  (como se hizo con el 157) o se deja sin socio si la cuenta está a cero.

## Tests

`python3 -m unittest test_aicia_migracion -v` (sin Odoo). Los del módulo, en una base de
pruebas vacía: `odoo -d <base> --test-enable --test-tags /aicia_account_importer`.
