# Usuarios de prueba — Portal de Solicitudes AICIA

> Datos de prueba listos para crear en el navegador y ejecutar
> [`PRUEBAS_FUNCIONALES_NAVEGADOR.md`](./PRUEBAS_FUNCIONALES_NAVEGADOR.md). Los
> pasos de creación (tipo de usuario, portal vs interno, asignación de grupo y
> equipo) están detallados en
> [`GUIA_CREACION_USUARIOS.md`](./GUIA_CREACION_USUARIOS.md); este documento solo
> aporta los **valores concretos** (nombre, login, contraseña, grupo, equipo) a
> introducir en cada campo.

> ⚠️ **Uso exclusivo en entorno de pruebas/preproducción.** Las contraseñas son
> deliberadamente simples de teclear para agilizar la ejecución manual/por
> agente de las pruebas. **No reutilices estos valores en producción** y borra
> o desactiva estos usuarios cuando termines las pruebas.
>
> 🔑 **Todos los usuarios comparten la misma contraseña: `Gestor2026!`**

---

## 0. Antes de crear usuarios: el equipo de trabajo

Varias pruebas dependen de que **Gestor**, **Jefe de Equipo** y **Solicitante**
compartan el mismo equipo. Créalo primero:

| Campo | Valor |
|---|---|
| Menú | Solicitudes del Portal → Equipos de trabajo (`portal.work.group`) |
| Nombre | `Equipo Prueba QA` |
| Código | `QA01` |
| Jefe de Equipo (`equip_boss`) | se asigna **después** de crear `jefe.equipo.qa` (paso 3) |

También crea (o reutiliza) un **proyecto analítico** de prueba y vincúlalo a
este equipo:

| Campo | Valor |
|---|---|
| Menú | Contabilidad → Configuración → Cuentas analíticas (o desde el proyecto) |
| Nombre | `Proyecto Prueba QA` |
| Grupo de trabajo (`work_group_id`) | `Equipo Prueba QA` |
| Responsable (`responsible_id`) | `jefe.equipo.qa@aicia-qa.local` (paso 3) |

Este es el `PROYECTO_PRUEBA` / `EQUIPO_PRUEBA` referenciado en el documento de
pruebas.

---

## 1. Usuarios de PORTAL (no consumen licencia)

Créalos desde **Contactos → Nuevo → Conceder acceso al portal** (sección 2 de
la guía), **no** desde Ajustes → Usuarios directamente.

| # | Nombre completo | Email / login | Contraseña | Grupo funcional a asignar | Equipo de trabajo | Variable en las pruebas |
|---|---|---|---|---|---|---|
| 1 | Gestor Prueba QA | `gestor.qa@aicia-qa.local` | `Gestor2026!` | **Gestor** | `Equipo Prueba QA` (como miembro) | `USER_GESTOR` / `PASS_GESTOR` |
| 2 | Solicitante Prueba QA | `solicitante.qa@aicia-qa.local` | `Gestor2026!` | *(ninguno — portal base)* | `Equipo Prueba QA` (como miembro) | `USER_SOLICITANTE` / `PASS_SOLICITANTE` |
| 3 | Sin Empleado Prueba QA | `sinempleado.qa@aicia-qa.local` | `Gestor2026!` | *(ninguno — portal base)* | — | `USER_SIN_EMPLEADO` / `PASS_SIN_EMPLEADO` (Bloque L1: **no** vincular a ningún `hr.employee`) |

**Pasos de creación (repite por cada fila):**
1. Contactos → Nuevo → escribe **Nombre** y **Email** (usa el valor de la
   columna "Email / login"). Guarda.
2. Acción (⚙) → **Conceder acceso al portal** → marca la casilla → **Conceder
   acceso**.
3. Se envía invitación al correo; para fijar la contraseña exacta de la tabla
   en un entorno de pruebas sin acceso al buzón real, entra como
   administrador en Ajustes → Usuarios → abre el usuario → pestaña
   **Cuenta** → botón **Cambiar contraseña** → introduce la contraseña
   indicada.
4. Ajustes → Usuarios → abre el usuario → categoría **"Tipo de usuario"** →
   selecciona el grupo funcional indicado (deja en blanco si la fila dice
   *ninguno*).
5. Si corresponde, ve a **Solicitudes del Portal → Equipos de trabajo →
   Equipo Prueba QA** y añade el usuario en **usuarios del equipo**.

---

## 2. Usuarios INTERNOS (consumen licencia — backend)

Créalos desde **Ajustes → Usuarios y compañías → Usuarios → Nuevo** (sección 4
de la guía).

| # | Nombre completo | Email / login | Contraseña | Grupo funcional (Tipo de usuario) | Notas | Variable en las pruebas |
|---|---|---|---|---|---|---|
| 4 | Jefe Equipo Prueba QA | `jefe.equipo.qa@aicia-qa.local` | `Gestor2026!` | **Jefe de Equipo** | Asignar como `equip_boss` de `Equipo Prueba QA` una vez creado | `USER_JEFE_EQUIPO` / `PASS_JEFE_EQUIPO` |
| 5 | Director ID Prueba QA | `director.id.qa@aicia-qa.local` | `Gestor2026!` | **Director I+D** | — | `USER_DIRECTOR_ID` / `PASS_DIRECTOR_ID` |
| 6 | Director Gerente Prueba QA | `dg.qa@aicia-qa.local` | `Gestor2026!` | **Director Gerente** | — | `USER_DG` / `PASS_DG` |
| 7 | Resp Compras Prueba QA | `resp.compras.qa@aicia-qa.local` | `Gestor2026!` | **Responsable de Personal y compras** | — | `USER_RESP_COMPRAS` / `PASS_RESP_COMPRAS` |
| 8 | Resp Clientes Prueba QA | `resp.clientes.qa@aicia-qa.local` | `Gestor2026!` | **Responsable de Clientes y Becarios** | — | `USER_RESP_CLIENTES` / `PASS_RESP_CLIENTES` |
| 9 | Con Empleado Prueba QA | `conempleado.qa@aicia-qa.local` | `Gestor2026!` | *(ninguno, o el que quieras probar)* | Vincular a un `hr.employee` de prueba tras crearlo (ver sección 3) | `USER_CON_EMPLEADO` / `PASS_CON_EMPLEADO` (Bloque L2-L5) |

**Opcionales**, solo si vas a ejecutar H1 con estos roles concretos o quieres
cobertura extra de perfiles definidos en el módulo:

| # | Nombre completo | Email / login | Contraseña | Grupo funcional | Variable |
|---|---|---|---|---|---|
| 10 | Jefe Proyecto Prueba QA | `jefe.proyecto.qa@aicia-qa.local` | `Gestor2026!` | **Jefe de Proyecto** | *(no referenciada por variable, úsala libremente en H1)* |
| 11 | Director Financiero Prueba QA | `dir.financiero.qa@aicia-qa.local` | `Gestor2026!` | **Director Financiero** | *(sin flujo activo probado actualmente en el módulo)* |
| 12 | Secretaría Dirección Prueba QA | `secretaria.qa@aicia-qa.local` | `Gestor2026!` | **Secretaría de dirección** | *(sin flujo activo probado actualmente en el módulo)* |

**Pasos de creación (repite por cada fila obligatoria 4-9):**
1. Ajustes → Usuarios y compañías → Usuarios → **Nuevo**.
2. Escribe **Nombre** y **Email/Login** con los valores de la tabla.
3. Deja **"Tipo de usuario"** (arriba, permisos base) en **Usuario interno**.
4. En la categoría **"Tipo de usuario"** (privilegio AICIA), selecciona el
   grupo funcional indicado.
5. Guarda. Para fijar la contraseña exacta: pestaña **Cuenta** → **Cambiar
   contraseña** → introduce el valor de la tabla.

**Tras crear la fila 4 (Jefe de Equipo):** ve a **Solicitudes del Portal →
Equipos de trabajo → Equipo Prueba QA** y asigna `jefe.equipo.qa@aicia-qa.local`
como **Jefe de Equipo** (`equip_boss`) del equipo.

---

## 3. Datos que NO son usuarios (empleados, adjuntos, proveedor)

Estos registros los necesitan los Bloques I, J, L y G, pero no son usuarios de
Odoo sino registros auxiliares.

| Variable | Cómo crearlo | Valor sugerido |
|---|---|---|
| `EMPLEADO_ACTIVO` | Empleados → Nuevo empleado, **activo** | Nombre: `Empleado Activo QA` |
| `EMPLEADO_INACTIVO` | Empleados → Nuevo empleado y luego **Archivar** (queda inactivo) | Nombre: `Empleado Inactivo QA` |
| Empleado de `USER_CON_EMPLEADO` | Empleados → Nuevo empleado, y en el campo **Usuario relacionado** vincula `conempleado.qa@aicia-qa.local` | Nombre: `Empleado Con Usuario QA` |
| Nómina de prueba | Sube `nomina_enero_2025.pdf` (copia de `documento_valido.pdf` renombrada) como adjunto del empleado anterior desde el backend (chatter → Adjuntar archivo) | — |
| `ATTACHMENT_ID_NOMINA_AJENA` | Crea un segundo empleado **distinto** (`Empleado Ajeno QA`) sin relación con `USER_CON_EMPLEADO`, súbele también una nómina de prueba y anota el **id del adjunto** (Ajustes → Técnico → Adjuntos, o inspeccionando la URL de descarga en backend) | — |
| `PROVEEDOR_PRUEBA` | Contactos → Nuevo → marca **Es proveedor** | Nombre: `Proveedor Prueba QA` |

---

## 4. Tabla resumen para copiar en la sección 0 de `PRUEBAS_FUNCIONALES_NAVEGADOR.md`

| Variable | Valor |
|---|---|
| `URL_BASE` | *(URL del entorno de pruebas)* |
| `USER_GESTOR` / `PASS_GESTOR` | `gestor.qa@aicia-qa.local` / `Gestor2026!` |
| `USER_JEFE_EQUIPO` / `PASS_JEFE_EQUIPO` | `jefe.equipo.qa@aicia-qa.local` / `Gestor2026!` |
| `USER_SOLICITANTE` / `PASS_SOLICITANTE` | `solicitante.qa@aicia-qa.local` / `Gestor2026!` |
| `USER_DIRECTOR_ID` / `PASS_DIRECTOR_ID` | `director.id.qa@aicia-qa.local` / `Gestor2026!` |
| `USER_RESP_COMPRAS` / `PASS_RESP_COMPRAS` | `resp.compras.qa@aicia-qa.local` / `Gestor2026!` |
| `USER_RESP_CLIENTES` / `PASS_RESP_CLIENTES` | `resp.clientes.qa@aicia-qa.local` / `Gestor2026!` |
| `USER_DG` / `PASS_DG` | `dg.qa@aicia-qa.local` / `Gestor2026!` |
| `PROYECTO_PRUEBA` | `Proyecto Prueba QA` |
| `EQUIPO_PRUEBA` | `Equipo Prueba QA` |
| `EMPLEADO_INACTIVO` | `Empleado Inactivo QA` |
| `EMPLEADO_ACTIVO` | `Empleado Activo QA` |
| `USER_SIN_EMPLEADO` / `PASS_SIN_EMPLEADO` | `sinempleado.qa@aicia-qa.local` / `SinEmp2026!` |
| `USER_CON_EMPLEADO` / `PASS_CON_EMPLEADO` | `conempleado.qa@aicia-qa.local` / `ConEmp2026!` |
| `ATTACHMENT_ID_NOMINA_AJENA` | *(id anotado en el paso de la sección 3)* |
| `PROVEEDOR_PRUEBA` | `Proveedor Prueba QA` |
| `EMAIL_BANDEJA` | Ajustes → Técnico → Correo electrónico → Correos electrónicos, filtrando por destinatario |

---

## 5. Checklist final antes de ejecutar las pruebas

- [ ] `Equipo Prueba QA` creado con `jefe.equipo.qa` como Jefe de Equipo.
- [ ] `Proyecto Prueba QA` creado y vinculado a `Equipo Prueba QA`.
- [ ] `gestor.qa` y `solicitante.qa` añadidos como miembros de `Equipo Prueba QA`.
- [ ] Los 6 usuarios internos (filas 4-9) tienen su grupo funcional asignado.
- [ ] `Empleado Con Usuario QA` vinculado a `conempleado.qa` con una nómina de
      prueba adjunta.
- [ ] `Empleado Ajeno QA` con nómina propia y su `attachment_id` anotado.
- [ ] `sinempleado.qa` confirmado **sin** ningún `hr.employee` vinculado.
- [ ] `Proveedor Prueba QA` creado como contacto proveedor.
- [ ] Ficheros de prueba preparados: `documento_valido.pdf`, `documento_falso.txt`,
      `falso.pdf`, `nomina_enero_2025.pdf` (ver sección 0 de
      `PRUEBAS_FUNCIONALES_NAVEGADOR.md`).
