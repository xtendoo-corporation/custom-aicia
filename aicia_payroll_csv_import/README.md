# AICIA Payroll CSV Import

## Descripción funcional

Este módulo permite importar mensualmente el CSV de nóminas que envía la gestoría de AICIA y generar automáticamente un asiento contable de tipo entrada en Odoo.

El asiento siempre se crea en borrador. El módulo no publica asientos, no crea facturas y no registra pagos.

## Formato CSV esperado

- Codificación cp1252 o latin1.
- Separador punto y coma ;.
- Puede incluir líneas informativas antes de la cabecera real.
- La cabecera real se detecta cuando el primer campo es exactamente FECHA PAGO.
- Los importes deben venir en formato español.
- Las celdas vacías se interpretan como 0.
- Las líneas vacías finales se ignoran.
- La fecha debe venir como dd/mm/yyyy.

## Columnas admitidas

- FECHA PAGO
- LIQUIDO
- CONT
- NIF
- Nombre
- IRPF
- SS_TRABAJ
- SS_EMPRES
- DIETA
- KM
- GRATIFICAC
- DEDUCCION
- COST GEST
- COST CT
- COST DESP
- ANTICIPOS

## Ejemplo de asiento

Debe:

- Sueldos y salarios
- Seguridad Social empresa
- Dietas, kilometraje y gratificaciones cuando existan
- Costes auxiliares configurados cuando estén activados

Haber:

- Líquido nóminas
- IRPF
- Seguridad Social acreedora
- Anticipos y otras deducciones cuando existan
- Acreedores auxiliares configurados cuando estén activados

## Advertencia contable

Las cuentas propuestas por defecto son solo una sugerencia basada en códigos habituales del PGC español. Deben revisarse con el asesor contable antes de usar el módulo en producción.

## Instrucciones de uso

1. Configurar el diario y las cuentas contables.
2. Crear una importación de nóminas.
3. Subir el fichero CSV recibido de la gestoría.
4. Pulsar Parsear CSV.
5. Revisar totales, advertencias y líneas importadas.
6. Pulsar Crear asiento contable.
7. Revisar el asiento generado y publicarlo manualmente cuando proceda.
