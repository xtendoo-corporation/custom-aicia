# Diseño Final — aicia_account_payment_split

## 1. Decisiones Clave

### 1.1 Estrategia de Reparto: UN SOLO asiento por pago

Se genera **un único asiento contable de reparto** por cada pago, calculado sobre el
importe total del pago (`payment.amount`). Si el pago reconcilia varias facturas, el
reparto aplica al total reconciliado (no se genera uno por factura).

**Justificación**: Simplifica la contabilidad, la auditoría y la navegación entre
documentos. Evita problemas de correspondencia cuando un pago parcial se aplica a
múltiples facturas.

### 1.2 Trigger: `action_post` del pago

El reparto se ejecuta al postear el pago. En Odoo 19 Enterprise, la reconciliación con
facturas ocurre dentro del flujo de posteo (cuando se crea desde el wizard de registro
de pagos). El asiento de reparto se crea y se publica automáticamente tras el posteo
exitoso.

### 1.3 Sugerencia Automática de Plantilla

- **Fuente**: analítica "principal" de las facturas asociadas al pago.
- **Detección de analítica principal**:
  1. Si la factura tiene `analytic_distribution` en cabecera (campo JSON), se toma la
     clave con mayor porcentaje.
  2. Si no, se analizan las `invoice_line_ids`: se agregan pesos de
     `analytic_distribution` por `analytic_account_id` y se selecciona la de mayor peso
     total.
- **Reglas de sugerencia**:
  - Si todas las facturas comparten la misma analítica principal → se busca plantilla
    con `default_for_analytic_account_id` = esa analítica, ordenada por `priority desc`.
  - Si hay analíticas distintas entre facturas → **NO se sugiere** (se deja vacío para
    que el usuario elija manualmente).
  - Si no se puede determinar analítica → **NO se sugiere**.
- **El usuario siempre puede cambiar** la plantilla manualmente antes de postear.

### 1.4 Cancelación → Asiento Inverso Automático

Al cancelar un pago que tiene asiento de reparto publicado, se genera automáticamente un
**asiento inverso** (reversal) usando el mecanismo estándar de Odoo
(`account.move.reversal`). El log se marca como "Revertido".

### 1.5 Prevención de Duplicados

- **Campo `split_move_id`**: si ya existe un asiento de reparto, no se crea otro.
- **Constraint SQL**: `UNIQUE(payment_id, template_id)` en la tabla de logs.
- **Verificación previa**: antes de crear, se comprueba `not payment.split_move_id`.

### 1.6 Multi-Currency

Si la moneda del pago difiere de la de la compañía:

- Las líneas del asiento llevan `amount_currency` en la moneda del pago.
- El `balance` se calcula en moneda de la compañía mediante conversión a fecha del pago.
- Se ajusta la última línea para cuadrar redondeos en ambas monedas.

## 2. Modos de Cálculo

### Modo A: `lines_sum_to_100`

Las líneas suman 100%. El importe repartido es `split_base_percentage%` del pago.

```
Ejemplo: pago = 1000€, base = 10%, Línea A = 60%, Línea B = 40%
→ Total repartido = 100€ (10% de 1000)
→ Línea A = 60€ (60% de 100)
→ Línea B = 40€ (40% de 100)
```

### Modo B: `lines_sum_to_base`

Las líneas suman directamente `split_base_percentage`.

```
Ejemplo: pago = 1000€, base = 10%, Línea A = 4%, Línea B = 3%, Línea C = 3%
→ Total repartido = 100€ (4+3+3 = 10% de 1000)
→ Línea A = 40€ (4% de 1000)
→ Línea B = 30€ (3% de 1000)
→ Línea C = 30€ (3% de 1000)
```

## 3. Estructura del Asiento de Reparto

```
┌─────────────────────────────────────────────────────┐
│ Diario: template.journal_id (tipo General)          │
│ Fecha:  payment.date                                │
│ Ref:    "Reparto cobro PAY/001 (Plantilla XYZ)"     │
├──────────────────────┬──────────┬───────────────────┤
│ Cuenta               │  DEBE    │  HABER            │
├──────────────────────┼──────────┼───────────────────┤
│ debit_account_id     │  100.00  │                   │
│ credit_account_1     │          │   60.00           │
│ credit_account_2     │          │   40.00           │
└──────────────────────┴──────────┴───────────────────┘
```

## 4. Edge Cases

| Caso                              | Comportamiento                                       |
| --------------------------------- | ---------------------------------------------------- |
| Pago sin plantilla                | No se genera reparto (campo vacío = skip)            |
| Pago parcial                      | Reparto sobre el importe del pago (no el de factura) |
| Pago a múltiples facturas         | Un solo asiento sobre el total del pago              |
| Factura sin analítica             | No se sugiere plantilla automáticamente              |
| Facturas con analíticas distintas | No se sugiere plantilla (usuario debe elegir)        |
| Redondeos en multi-currency       | Última línea ajustada para cuadrar                   |
| Cancelación de pago con reparto   | Asiento inverso automático + log a "Revertido"       |
| Re-posteo tras borrador           | Se permite crear nuevo reparto si no existe          |
| Pago importe = 0                  | No se genera reparto                                 |
| Template sin líneas               | No se genera reparto (skip silencioso)               |
| Doble clic en postear             | Protegido por check `not split_move_id`              |

## 5. Modelos

| Modelo                                | Descripción                    |
| ------------------------------------- | ------------------------------ |
| `account.payment.split.template`      | Plantilla de reparto           |
| `account.payment.split.template.line` | Líneas de plantilla            |
| `account.payment.split.log`           | Log de auditoría               |
| `account.payment` (inherit)           | Campos y lógica de reparto     |
| `account.move` (inherit)              | Smart button para ver repartos |

## 6. Seguridad

- **Plantillas/Líneas**: CRUD para `group_account_manager`, lectura para
  `group_account_user`.
- **Logs**: CRUD para `group_account_manager`, lectura para `group_account_user`.
- **Multi-company**: reglas `ir.rule` con `company_ids` en los tres modelos nuevos.
- **Campo `split_template_id`**: editable solo en estado `draft`.
