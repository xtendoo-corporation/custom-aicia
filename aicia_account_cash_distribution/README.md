## aicia_account_cash_distribution

Motor de distribución contable por criterio de caja para Odoo 19.0. Genera asientos de redistribución (IVA e ingresos/contrapartidas) en el momento de conciliar cobros de facturas de cliente, con trazabilidad por pago, conciliación, proyecto y plan aplicado.

### Qué aporta
- Disparo en cada `account.partial.reconcile` (conciliación total o parcial) de cobros de clientes.
- Selección del plan: primero el indicado en el pago, si no el de la cuenta analítica origen (cabecera o líneas de factura; soporta `analytic_distribution`).
- Líneas de plan flexibles: redistribución automática de IVA (misma 477, analítica cruzada) y porcentajes sobre base cobrada con cuentas debit/crédito y lados analíticos configurables.
- Asiento único de distribución por conciliación, con `account.move` marcado (`is_cash_distribution_move`) y vínculo al pago y conciliación; se revierte al deshacer la conciliación.
- Trazabilidad: planes aplicados, analíticas origen, smart button en pagos y cuentas analíticas.

### Modelos clave
- `aicia.distribution.plan`: cabecera de plan (secuencia, compañía, analítica receptora opcional) con relación inversa a las analíticas que lo usan.
- `aicia.distribution.plan.line`: líneas de reparto. Campos clave: `is_vat_line`, `percentage`, cuentas debe/haber y lado analítico (origen/receptor). Valida que las líneas de IVA usen la misma cuenta y lados opuestos.
- `account.partial.reconcile`: crea el asiento de distribución y lo enlaza (`distribution_move_id`); lo elimina si se elimina la conciliación.
- `account.move` extensión: flags y relaciones para trazar origen (pago, conciliación, analíticas, planes).
- `account.payment` y `account.payment.register`: campo `distribution_plan_id`, smart button y autocompletado desde las facturas seleccionadas.
- `res.company`/`res.config.settings`: activación, diario de distribución y analítica receptora por defecto.
- `account.analytic.account`: asignación del plan y contador de distribuciones asociadas.

### Configuración
1) Ajustes ▸ Contabilidad ▸ Activar “Distribución de Cobros”, definir diario general y analítica receptora por defecto.
2) Revisar/crear planes en Contabilidad ▸ Configuración ▸ Planes de distribución. Cada plan define todas las líneas a ejecutar.
3) Asignar el plan a las cuentas analíticas de los proyectos (campo “Plan de Distribución”).
4) Opcional: en el pago (o asistente de registro de pagos) se puede forzar un plan concreto; tiene prioridad sobre el de la analítica.

### Flujo de uso
1) Registrar cobro de factura de cliente desde el asistente de pago; el plan se autocompleta si todas las facturas usan el mismo.
2) Al conciliar el pago con la(s) factura(s), se calcula la parte cobrada (ratio) y, por cada analítica origen detectada, se generan las líneas del plan:
   - Líneas IVA: 100% del IVA cobrado proporcional, misma 477, analíticas cruzadas origen/receptor.
   - Líneas base: porcentaje sobre base cobrada, con cuentas y lado analítico configurables.
3) Se crea y publica un único asiento de distribución enlazado al pago/conciliación. Al deshacer la conciliación, el asiento se revierte (draft) y se elimina.

### Datos por defecto
- Se instala un plan “Distribución AICIA por defecto” (noupdate) y en post-init se completa de forma idempotente:
  - Línea IVA 100% usando la primera 477 encontrada; Debe analítica origen / Haber analítica receptora.
  - Línea base 10% usando la primera cuenta de ingreso/gasto encontrada; lados analíticos origen→debe, receptor→haber.
  - Si no existe analítica receptora, se crea “AICIA - Receptora Distribución”.

### Consideraciones contables
- Base de cálculo: importe cobrado proporcional (ratio sobre total factura). IVA cobrado proporcional se calcula a partir de las líneas fiscales de la factura.
- Las líneas de IVA usan siempre la misma cuenta y lados analíticos opuestos; las líneas de porcentaje usan la base cobrada y el porcentaje configurado.
- Los apuntes se crean balanceados y con `partner_id` de la factura.

### Pruebas
Ejecutar tests del módulo en un contenedor doodba (ajusta la base de datos temporal si lo prefieres):
```bash
docker compose run --rm odoo odoo \
  -d aicia_19 \
  -i aicia_account_cash_distribution \
  --test-enable \
  --stop-after-init
```

### Limitaciones conocidas
- Solo aplica a facturas de cliente (`out_invoice`).
- Requiere que la analítica origen tenga un plan activo o que el pago lo fuerce explícitamente.
- Si faltan cuentas (ej. 477000) el plan por defecto intenta buscar alternativas; revisa las líneas resultantes tras la instalación.

### Mantenimiento
- Eliminar relaciones huérfanas de distribuciones legacy se gestiona en `_register_hook` de `account.move`.
- Las líneas legacy de IVA se normalizan en `_register_hook` de `aicia.distribution.plan.line`.

