# Guía de creación de usuarios — Portal de Solicitudes AICIA

> Esta guía explica, paso a paso, **cómo crear cada tipo de credencial** del
> portal AICIA, con especial atención a los **usuarios de portal (que NO
> consumen licencia)** y al perfil **Gestor**.
>
> Conceptos clave antes de empezar:
> - **Tipo base del usuario** (estándar de Odoo): *Interno* (consume licencia),
>   *Portal* (no consume) o *Público*.
> - **Perfil funcional** del módulo, en la categoría **"Tipo de usuario"**: el rol
>   AICIA que se asigna encima del tipo base (Gestor, Jefe de Equipo, Director
>   Gerente, etc.).

---

## Índice

1. [Regla de oro: interno vs portal (licencias)](#1-regla-de-oro-interno-vs-portal-licencias)
2. [Crear un usuario de PORTAL sin licencia (recomendado para Gestor)](#2-crear-un-usuario-de-portal-sin-licencia)
3. [Asignar el perfil "Gestor" a un usuario de portal](#3-asignar-el-perfil-gestor)
4. [Crear un usuario INTERNO con perfil AICIA](#4-crear-un-usuario-interno-con-perfil-aicia)
5. [Corregir un usuario creado por error como interno](#5-corregir-un-usuario-creado-por-error-como-interno)
6. [Asignar usuarios a un equipo de trabajo](#6-asignar-usuarios-a-un-equipo-de-trabajo)
7. [Tabla resumen: qué tipo base usar por perfil](#7-tabla-resumen)
8. [Comprobaciones finales](#8-comprobaciones-finales)

---

## 1. Regla de oro: interno vs portal (licencias)

- Cuando creas un usuario desde **Ajustes → Usuarios y compañías → Usuarios →
  Nuevo**, Odoo lo crea como **Interno** por defecto → **consume licencia**.
- Para crear un usuario que **NO consuma licencia**, debes crearlo como
  **usuario de Portal**, y la forma correcta es hacerlo **desde el Contacto** con
  la opción **"Conceder acceso al portal"** (no desde el alta manual de usuario).

> **Importante:** el perfil **Gestor** está pensado para ser **usuario de
> portal**. De hecho, al asignar el grupo "Gestor" el usuario queda como portal
> automáticamente. Aun así, para no consumir licencia, **créalo primero como
> usuario de portal** siguiendo la sección 2.

---

## 2. Crear un usuario de PORTAL sin licencia

Este es el procedimiento recomendado para **Gestores** y, en general, para
cualquier usuario externo (investigadores, jefes de equipo externos) que no deba
consumir licencia.

**Pasos:**

1. Ve a **Contactos** (menú principal de Odoo).
2. **Crea o abre** el contacto de la persona:
   - Si es nuevo: **Nuevo** → escribe **Nombre** y **Email** (el email es
     obligatorio para el acceso). Guarda.
3. Con el contacto abierto, pulsa el botón de **Acción** (engranaje / ⚙ menú
   superior) y selecciona **"Conceder acceso al portal"**
   *(Grant portal access)*.
4. En la ventana emergente:
   - Verifica el **email**.
   - Marca la casilla del contacto.
   - Pulsa **Conceder acceso**.
5. El sistema envía al usuario un **correo de invitación** para que establezca su
   contraseña.

**Resultado:** se ha creado un **usuario de Portal** (no consume licencia)
vinculado a ese contacto.

> Para comprobarlo: **Ajustes → Usuarios**, abre el usuario y verifica que en
> **"Tipo de usuario"** figura **Portal** (no *Usuario interno*).

---

## 3. Asignar el perfil "Gestor"

Una vez el usuario existe como **usuario de portal** (sección 2), asígnale el
perfil funcional **Gestor**:

**Pasos:**

1. Ve a **Ajustes → Usuarios y compañías → Usuarios**.
2. Abre el usuario de portal recién creado.
3. Localiza la sección de permisos, categoría **"Tipo de usuario"**
   *(privilegio de AICIA)*.
4. En el desplegable de **"Tipo de usuario"**, selecciona **Gestor**.
5. **Guarda**.

**Qué habilita el perfil Gestor:**
- Puede **crear y enviar solicitudes** de **su(s) equipo(s) de trabajo**.
- **Solo ve las solicitudes de su propio equipo** (documentos, facturas, gastos,
  solicitudes de proyecto).
- Acceso **solo lectura** a las cuentas analíticas de su equipo.
- **No** ve saldos, balances ni históricos económicos.

> No olvides **asignarlo a un equipo de trabajo** (sección 6); si no, no verá ni
> podrá enviar solicitudes de ningún equipo.

---

## 4. Crear un usuario INTERNO con perfil AICIA

Para el personal de AICIA que sí trabaja en el backend (dirección,
administración, responsables, jefes de equipo internos).

**Pasos:**

1. Ve a **Ajustes → Usuarios y compañías → Usuarios → Nuevo**.
2. Escribe **Nombre**, **Email/Login**.
3. En **"Tipo de usuario"** (parte superior de permisos), deja **Usuario
   interno**.
4. En la categoría **"Tipo de usuario"** (privilegio de AICIA), selecciona el
   perfil correspondiente:
   - **Jefe de Equipo**
   - **Jefe de Proyecto**
   - **Director I+D**
   - **Director Gerente**
   - **Director Financiero**
   - **Responsable de Personal y Compras**
   - **Responsable de Clientes y Becarios**
   - **Secretaría de Dirección**
5. **Guarda**. Odoo enviará (o podrás enviar) la invitación para fijar
   contraseña.

> **Consumo de licencia:** los usuarios internos **consumen licencia**. Usa este
> tipo solo para el personal que realmente necesita el backend.

---

## 5. Corregir un usuario creado por error como interno

Si diste de alta a alguien como **interno** cuando debía ser **portal** (y está
consumiendo licencia indebidamente):

**Pasos:**

1. Ve a **Ajustes → Usuarios**, abre el usuario mal creado.
2. **Archívalo** (Acción → Archivar), para liberar la licencia.
3. Ve a **Contactos**, abre (o crea) el contacto de esa persona.
4. Aplica **"Conceder acceso al portal"** (sección 2) para recrearlo como
   **usuario de portal**.
5. Asígnale el perfil funcional que corresponda (p. ej. **Gestor**, sección 3) y
   su **equipo de trabajo** (sección 6).

> Así se corrige el estado sin dejar duplicados activos ni consumir licencia.

---

## 6. Asignar usuarios a un equipo de trabajo

Los perfiles basados en equipo (**Gestor**, **Jefe de Equipo**) necesitan estar
vinculados a un **equipo de trabajo** para ver y enviar solicitudes.

**Pasos:**

1. Ve al menú de **Solicitudes del Portal → Equipos de trabajo**
   *(portal.work.group)*.
2. Abre el equipo correspondiente (o crea uno: necesita **Nombre** y **Código**).
3. Añade el usuario en la lista de **usuarios del equipo**.
4. Si procede, indica el **Jefe de Equipo** del grupo.
5. **Guarda**.

**Resultado:** el usuario (Gestor o Jefe de Equipo) ya verá y podrá gestionar las
solicitudes de ese equipo.

---

## 7. Tabla resumen

| Perfil funcional | Tipo base recomendado | ¿Consume licencia? | Necesita equipo |
|---|---|---|---|
| **Gestor** | **Portal** | ❌ No | ✅ Sí |
| **Jefe de Equipo** | Interno | ✅ Sí | ✅ Sí |
| **Jefe de Proyecto** | Interno o Portal | Según tipo base | Recomendado |
| **Director I+D** | Interno | ✅ Sí | No |
| **Director Gerente** | Interno | ✅ Sí | No |
| **Director Financiero** | Interno | ✅ Sí | No |
| **Responsable de Personal y Compras** | Interno | ✅ Sí | No |
| **Responsable de Clientes y Becarios** | Interno | ✅ Sí | No |
| **Secretaría de Dirección** | Interno | ✅ Sí | No |

> Perfiles **no disponibles** (retirados): *Responsable de Becarios* y
> *Responsable de Compras* — fusionados en los actuales "Responsable de Clientes
> y Becarios" y "Responsable de Personal y Compras".

---

## 8. Comprobaciones finales

Tras crear un usuario, verifica:

1. **Tipo base correcto:** Ajustes → Usuarios → abrir usuario → "Tipo de usuario"
   = *Portal* o *Interno*, según lo previsto (clave para la licencia).
2. **Perfil AICIA asignado:** categoría "Tipo de usuario" muestra el rol correcto.
3. **Equipo de trabajo** asignado si el perfil lo requiere (Gestor / Jefe de
   Equipo).
4. **Acceso real:** pide al usuario que inicie sesión en `URL_BASE/my` y confirme
   que:
   - ve las secciones esperadas del portal;
   - (si es Gestor) **no** ve información económica ni solicitudes de otros
     equipos.
5. **Licencia:** revisa el contador de usuarios internos para confirmar que los
   usuarios de portal **no** lo incrementan.

---

*Ante cualquier duda sobre permisos o visibilidad, consulta el
`MANUAL_USUARIO.md` (perfiles y restricciones) o contacta con soporte.*
