# Cierre por Proyectos (AICIA)

## Descripción

Módulo Odoo 19 para automatizar el cierre contable AICIA por proyectos (cuentas analíticas).

Calcula el resultado contable de cada proyecto en un periodo determinado y genera asientos de regularización:

- **Resultado positivo** (beneficio) → Cuenta 130 (Subvenciones oficiales de capital) ↔ Cuenta 294 (Provisiones)
- **Resultado negativo** (pérdida) → Cuenta 131 (Donaciones y legados de capital) ↔ Cuenta 294 (Provisiones)

### Características

- Wizard con previsualización antes de generar asientos
- Reparto proporcional según `analytic_distribution`
- Detección de duplicados para evitar doble cierre
- Un asiento por proyecto para auditoría clara
- Trazabilidad completa con campos técnicos en `account.move`
- Soporte multi-compañía

## Dependencias

- `account` (Contabilidad estándar de Odoo)
- `analytic` (Contabilidad analítica)

## Instalación

1. Copiar la carpeta `aicia_account_project_closure` en el directorio de addons de Odoo.
2. Actualizar la lista de aplicaciones: **Configuración → Aplicaciones → Actualizar lista de aplicaciones**.
3. Buscar "Cierre por Proyectos" e instalar.

## Uso

1. Ir a **Contabilidad → Contabilidad → Closing → Cierre por Proyectos (AICIA)**.
2. Se abre el wizard en modal.
3. Configurar:
   - **Periodo**: fecha desde/hasta del ejercicio.
   - **Diario**: diario de tipo general para los asientos de cierre.
   - **Cuentas**: 130 (beneficio), 131 (pérdida), 294 (provisión) — se autorellenan si existen.
   - **Prefijos**: por defecto `6,7` (gastos e ingresos).
   - **Proyectos**: opcional; si se deja vacío, procesa todos los que tengan movimiento.
4. Pulsar **"Previsualizar"** para ver el resultado por proyecto.
5. Revisar la tabla de resultados. Los proyectos marcados como "Duplicado" se omitirán.
6. Pulsar **"Generar Asientos"** para crear y publicar los asientos de cierre.
7. Usar el botón **"Asientos"** para navegar a los asientos creados.

## Estructura de los asientos generados

Cada proyecto con resultado no-cero genera **un asiento contable** con:

| Línea | Cuenta | Debe | Haber | Analítica |
|-------|--------|------|-------|-----------|
| Resultado (beneficio) | 130 | — | Importe | Proyecto 100% |
| Provisión | 294 | Importe | — | Proyecto 100% |

O para resultado negativo:

| Línea | Cuenta | Debe | Haber | Analítica |
|-------|--------|------|-------|-----------|
| Resultado (pérdida) | 131 | Importe | — | Proyecto 100% |
| Provisión | 294 | — | Importe | Proyecto 100% |

## Campos técnicos en account.move

- `aicia_closure` (Boolean): marca los asientos generados por este proceso.
- `aicia_closure_ref` (Char): clave única `AICIA-{analytic_id}-{date_from}-{date_to}` para detección de duplicados.

## Tests

Ejecutar los tests del módulo:

```bash
odoo -d <database> --test-enable --stop-after-init -i aicia_account_project_closure
```

O ejecutar solo los tests:

```bash
odoo -d <database> --test-enable --stop-after-init --test-tags /aicia_account_project_closure
```

### Tests incluidos

| Test | Descripción |
|------|-------------|
| `test_preview_single_project_positive` | Cálculo correcto de resultado positivo |
| `test_preview_single_project_negative` | Cálculo correcto de resultado negativo |
| `test_preview_multiple_projects` | Múltiples proyectos generan líneas separadas |
| `test_preview_proportional_distribution` | Reparto proporcional 60/40 |
| `test_preview_no_analytic_ignored` | Líneas sin analítica se ignoran |
| `test_preview_filter_by_analytic` | Filtro por analíticas específicas |
| `test_preview_outside_date_range` | Movimientos fuera de rango excluidos |
| `test_generate_positive_result` | Asiento correcto para beneficio |
| `test_generate_negative_result` | Asiento correcto para pérdida |
| `test_duplicate_detection` | Bloqueo de duplicados |
| `test_back_button` | Volver limpia y regresa a borrador |
| `test_zero_result_skipped` | Resultado cero no genera asiento |
| `test_date_validation` | Fechas invertidas lanzan error |
| `test_closure_move_has_analytic_distribution` | Ambas líneas llevan analítica |
| `test_multiple_projects_generate_separate_moves` | Un asiento por proyecto |
| `test_closure_ref_format` | Formato de referencia correcto |
| `test_action_view_moves_single` | Acción view con 1 asiento |
| `test_action_view_moves_multiple` | Acción view con N asientos |

## Notas técnicas

- **Convención de signos**: `balance = debit - credit`. Ingresos (7xx) tienen balance negativo, gastos (6xx) positivo. El módulo invierte el signo para presentar income/expense como valores positivos.
- **Cierre formal 6/7**: Este módulo genera asientos de resultado analítico (130/131 ↔ 294), no cierra formalmente las cuentas 6/7. El P&L estándar de Odoo permanece intacto.
- **Multi-compañía**: Usa `with_company()` para búsqueda de cuentas por código y creación de asientos.

## Licencia

AGPL-3.0 o posterior - https://www.gnu.org/licenses/agpl

