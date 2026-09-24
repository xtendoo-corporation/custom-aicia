# Manual de usuario — Portal de Solicitudes AICIA (`portal_requests`)

> Módulo: **Aicia portal requests** · Versión **19.0.1.0.0** (Odoo 19 Community)
>
> Este manual describe, desde el punto de vista del usuario, toda la
> funcionalidad del portal de solicitudes: los **perfiles de usuario**, los
> **tipos de solicitud** y sus **flujos de aprobación**, las **notificaciones**
> automáticas por correo y las **restricciones** aplicadas (formato PDF, número
> de archivos, visibilidad de información económica).

---

## Índice

1. [Introducción y acceso](#1-introducción-y-acceso)
2. [Perfiles de usuario](#2-perfiles-de-usuario)
3. [Visión general del portal](#3-visión-general-del-portal)
4. [Tipos de solicitud y flujos](#4-tipos-de-solicitud-y-flujos)
   - 4.1 [Firma de documentos](#41-firma-de-documentos)
   - 4.2 [Apertura y cierre de proyecto](#42-apertura-y-cierre-de-proyecto)
   - 4.3 [Solicitudes de personal (empleado y becario)](#43-solicitudes-de-personal-empleado-y-becario)
   - 4.4 [Emisión de factura](#44-emisión-de-factura)
   - 4.5 [Pago de factura / orden de compra](#45-pago-de-factura--orden-de-compra)
   - 4.6 [Solicitudes de gasto](#46-solicitudes-de-gasto)
5. [Notificaciones por correo](#5-notificaciones-por-correo)
6. [Restricciones](#6-restricciones)
7. [Trazabilidad de rechazos y nuevas versiones](#7-trazabilidad-de-rechazos-y-nuevas-versiones)
8. [Firma electrónica y archivos firmados](#8-firma-electrónica-y-archivos-firmados)
9. [Preguntas frecuentes](#9-preguntas-frecuentes)

---

## 1. Introducción y acceso

El **Portal de Solicitudes** permite a los usuarios de AICIA (investigadores,
jefes de equipo, gestores, dirección y personal de administración) crear y hacer
seguimiento de solicitudes internas —firma de documentos, apertura de proyectos,
altas/bajas de personal, facturación, pagos y gastos— sin necesidad de acceder
al backend completo de Odoo.

### Cómo se accede

- El acceso se realiza a través del **portal web** (`/my`), con usuario y
  contraseña.
- Los usuarios externos (investigadores, jefes de equipo, gestores) son
  **usuarios de portal**: no consumen licencia interna y solo ven las secciones
  del portal a las que tienen derecho.
- El personal interno (dirección, administración) accede además al **backend**
  para revisar y aprobar solicitudes.

> **Importante (creación de usuarios externos):** para dar de alta a un usuario
> externo que **no** consuma licencia, hay que usar la opción **"Conceder acceso
> al portal"** desde la ficha de Contacto, no crear el usuario a mano (Odoo lo
> crearía como interno por defecto). Si un usuario se creó por error como
> interno, se archiva y se recrea como usuario de portal.

---

## 2. Perfiles de usuario

El módulo define una categoría de seguridad **"Tipo de usuario"** con los
siguientes perfiles. Cada perfil determina **qué solicitudes puede iniciar**,
**qué puede aprobar** y **qué información económica puede ver**.

| Perfil (grupo) | Descripción | Rol típico |
|---|---|---|
| **Gestor** | Usuario de **portal restringido**. Puede enviar solicitudes de su equipo de trabajo y recibir confirmaciones, **sin** acceso a históricos, saldos ni información económica confidencial. | Personal administrativo que apoya a los jefes de equipo. |
| **Jefe de Equipo** | Responsable de un grupo de trabajo. Aprueba en primera instancia las solicitudes de su equipo y ve los saldos de su grupo/proyectos. | Investigador responsable de grupo. |
| **Jefe de Proyecto** | Responsable de un proyecto concreto. Ve y gestiona lo relativo a sus proyectos. | Investigador principal. |
| **Director I+D** | Aprueba/gestiona la firma de documentos y tiene acceso completo a las cuentas analíticas. | Dirección técnica. |
| **Director Gerente (DG)** | Máxima aprobación. Interviene en pagos/gastos **solo cuando el importe supera los 10.000 €**. Acceso completo a información económica. | Dirección general. |
| **Director Financiero** | Perfil económico-financiero. | Dirección financiera. |
| **Responsable de Personal y Compras** | Segundo aprobador de gastos y pagos (`personal@aicia.es`). | Administración de compras/personal. |
| **Responsable de Clientes y Becarios** | Segundo aprobador de facturación y gratificaciones (`clientes@aicia.es`). | Administración de clientes. |
| **Secretaría de Dirección** | Apoyo a dirección. | Secretaría. |

### El perfil "Gestor" en detalle

El perfil **Gestor** se creó para el personal administrativo que apoya a los
jefes de equipo, que suelen estar muy ocupados. Sus características:

- Es un **usuario de portal** (no consume licencia interna).
- Puede **crear y enviar solicitudes** asociadas a **su(s) equipo(s) de
  trabajo**.
- **Solo ve las solicitudes de su propio equipo** (documentos, facturas, gastos
  y solicitudes de proyecto), gracias a reglas de registro por equipo.
- Sobre las cuentas analíticas de su equipo tiene acceso **solo de lectura**.
- **No** tiene acceso a balances económicos ni a información confidencial de
  otros equipos.

---

## 3. Visión general del portal

Desde **"Mi cuenta" (`/my`)**, el usuario dispone de las siguientes secciones
(según su perfil):

| Sección del portal | Ruta | Contenido |
|---|---|---|
| Documentos | `/my/documents` | Solicitudes de firma de documentos y su estado. |
| Solicitudes de proyecto | `/my/project_requests` | Aperturas/cierres de proyecto. |
| Facturas | `/my/invoices` | Solicitudes de emisión de factura. |
| Gastos | `/my/expenses` | Solicitudes de gasto (compras, inventariable, liquidación, gratificación). |
| Pagos | `/my/payments` | Solicitudes de pago / órdenes de compra. |
| Proyectos | `/my/analytic_projects` | Consulta de proyectos analíticos accesibles. |
| Nóminas | `/my/nomina` | Consulta de nóminas. |

Cada listado muestra la **fecha de creación** y un **distintivo de estado**
(badge) para localizar rápidamente las solicitudes antiguas y nuevas y saber en
qué punto del flujo se encuentran. Las solicitudes **no desaparecen** del portal
tras ser aprobadas: permanecen visibles para su seguimiento.

---

## 4. Tipos de solicitud y flujos

Cada tipo de solicitud sigue un **flujo de aprobación por estados**. En cada
cambio de estado el **solicitante recibe un correo** informándole (ver
[Notificaciones](#5-notificaciones-por-correo)).

### 4.1 Firma de documentos

**Formulario:** `/portal/approval_request` · **Listado:** `/my/documents`

Permite solicitar la firma/aprobación de un documento. Tipos disponibles:

- Solicitud de firma **NDA**
- Solicitud de firma de **contrato con empresa**
- Solicitud de **autorización de salida a empresas**
- Solicitud de **salida de viaje**

> El proceso **"Solicitud de colaboración PAS" ha sido retirado** del portal a
> petición del cliente y ya no aparece como opción.

**Estados del documento:**

`Aprobación del Director I+D` → `Aprobación del Director Gerente` →
`Esperando firma de empresa` → `Revisión final` → `Aprobada`
(o `Rechazada` en cualquier punto).

**Flujo resumido:**

1. El solicitante rellena el formulario, elige el tipo y **adjunta el documento
   en PDF**.
2. Se notifica al **Director I+D** para su revisión.
3. Tras las aprobaciones, el documento pasa a **firma** (empresa / Director
   Gerente).
4. El solicitante **conserva la visibilidad** del documento durante todo el
   proceso, incluso cuando pasa a otra persona para firmar.
5. Al finalizar, el documento firmado se guarda con el sufijo **`_firmado`**
   (ver [sección 8](#8-firma-electrónica-y-archivos-firmados)).

### 4.2 Apertura y cierre de proyecto

**Apertura:** `/portal/project_request` · **Cierre:** `/portal/project_end_request`
· **Listado:** `/my/project_requests`

Permite solicitar la **apertura de un nuevo proyecto** o la **finalización** de
uno existente (tipos `Nuevo Proyecto` / `Finalizar Proyecto`).

- En la apertura se pueden **adjuntar el contrato firmado y el presupuesto**
  (en PDF).
- La **gestión de investigadores** del proyecto se realiza desde la propia vista
  de proyecto: se pueden **ver y editar los participantes** y su **porcentaje de
  dedicación**, así como la **fecha de inicio** de la relación
  trabajador‑proyecto. Para docentes sin nómina puede dejarse el porcentaje al
  **0 %** para no alterar los cálculos analíticos.

### 4.3 Solicitudes de personal (empleado y becario)

**Empleado:** `/portal/hr_employee_request` ·
**Becario:** `/portal/hr_employee_intern_request`

Permiten gestionar altas y bajas de personal, con tipos `Nuevo`, `Alta` y
`Baja`. En el alta pueden adjuntarse documentos (vida laboral, CV, anexo PRL)
**en PDF**.

- Las solicitudes notifican al **Responsable de Clientes y Becarios**
  (responsable de socios internos).

### 4.4 Emisión de factura

**Formulario:** `/portal/invoice_request` · **Listado:** `/my/invoices`

Permite solicitar la emisión de una **factura de cliente** (o abono). Incluye:

- **Campo de comentarios/concepto**, para indicar por ejemplo direcciones de
  envío u observaciones.
- La notificación al **Responsable de Clientes** (`clientes@aicia.es`) incluye
  el **código del proyecto**, la **referencia interna** y los **comentarios**
  introducidos, y el cliente aparece correctamente **identificado como cliente**.

**Estados:** `Volver a revisar` → `Aprobación del Jefe de Equipo` →
`Aprobación del Responsable de clientes` → `Aprobada` (o `Rechazada`).

### 4.5 Pago de factura / orden de compra

**Formulario (orden de compra):** `/portal/purchase_order_request` ·
**Pagos:** `/my/payments`

Permite solicitar el **pago de facturas** u **órdenes de compra**.

- La notificación de pago se envía al **Responsable de Proveedores**
  (`personal@aicia.es`).
- El **Director Gerente** recibe notificación **únicamente cuando el importe
  supera los 10.000 €**; por debajo de ese umbral **no** se le molesta.
- Se pueden adjuntar los documentos justificativos (en PDF).

### 4.6 Solicitudes de gasto

**Formulario:** `/portal/hr_expensive_request` · **Listado:** `/my/expenses`

Un único formulario cubre cuatro tipologías:

| Tipo | Archivos permitidos | Segundo aprobador |
|---|---|---|
| **Compra de bienes o servicios** | Varios PDF | Responsable de Personal y Compras (`personal@aicia.es`) |
| **Pago de material inventariable** | Varios PDF (+ archivo de inventario) | Responsable de Personal y Compras |
| **Liquidación de gastos** | **Varios** PDF | Responsable de Personal y Compras |
| **Solicitud de gratificación** | **Un solo** PDF (el formulario) | Responsable de Clientes y Becarios (`clientes@aicia.es`) |

**Estados:** `Aprobación del Jefe de Equipo` →
`Aprobación del Responsable de proveedores` →
`Aprobación del Director Gerente` *(solo si > 10.000 €)* → `Aprobada`
(o `Rechazada`, o `Volver a revisar`).

**Flujo resumido:**

1. El solicitante elige el **tipo**, el **proyecto** y adjunta los documentos
   (en PDF).
2. **Aprueba el Jefe de Equipo** de su grupo de trabajo → se notifica al
   **segundo aprobador** (Personal y Compras, o Clientes y Becarios en el caso de
   gratificación).
3. El **segundo aprobador** aprueba:
   - Si el importe **supera 10.000 €** → se escala al **Director Gerente** y se le
     notifica.
   - Si **no** lo supera → la solicitud queda **aprobada** directamente (se genera
     la factura borrador) sin intervención del DG.
4. Si el DG interviene, su aprobación cierra la solicitud.

> Si el propio **Jefe de Equipo** es quien solicita el gasto, su solicitud pasa
> directamente al segundo aprobador (no se auto-aprueba).

---

## 5. Notificaciones por correo

El sistema envía **notificaciones automáticas por correo** en los momentos
clave. Hay dos mecanismos complementarios:

### a) Notificación al solicitante en **cada cambio de estado**

Siempre que una solicitud **cambia de estado**, el **solicitante** recibe un
correo con el **nuevo estado** y un **enlace** a la solicitud en su portal.
Aplica a documentos, facturas, gastos y solicitudes de proyecto. Esto garantiza
que el usuario recibe confirmación incluso cuando el cambio lo provoca otra
persona (por ejemplo, la aprobación final).

- No se envía correo si el estado **no cambia** realmente.
- No se envía si el solicitante **no tiene email** configurado.

### b) Notificación a los **aprobadores/responsables** en cada paso

Además, en cada paso del flujo se avisa a quien debe actuar:

| Evento | Destinatario |
|---|---|
| Nueva solicitud de firma de documento | **Director I+D** |
| Nueva solicitud de empleado / becario | **Responsable de Clientes y Becarios** |
| Gasto aprobado por el Jefe de Equipo | **Responsable de Personal y Compras** (o **Clientes y Becarios** si es gratificación) |
| Gasto/pago **> 10.000 €** aprobado por el 2.º aprobador | **Director Gerente** |
| Solicitud de pago / orden de compra | **Responsable de Proveedores** (`personal@aicia.es`) |
| Solicitud de emisión de factura | **Responsable de Clientes** (`clientes@aicia.es`), con código de proyecto, referencia interna y comentarios |
| Solicitud **rechazada** | **Solicitante**, con enlace para aportar una nueva versión |

> **Umbral de 10.000 €:** el Director Gerente **solo** recibe notificaciones de
> pagos/gastos que superen los 10.000 €. Por debajo del umbral, la aprobación la
> cierra el responsable correspondiente.

---

## 6. Restricciones

### 6.1 Formato PDF obligatorio

**Todos los documentos que se suban desde el portal deben ser PDF.** La
validación se hace en el servidor comprobando **la extensión `.pdf` y la
cabecera real del archivo** (`%PDF`). Esto:

- Garantiza la **previsualización** de los documentos.
- Evita la subida de archivos manipulables o no visualizables (por ejemplo,
  Word).

Si se intenta subir un archivo que **no es un PDF válido** (por extensión o por
contenido), la solicitud **no se completa** y el sistema muestra un aviso
indicando el archivo rechazado. No se guarda ningún adjunto ni se crea la
solicitud hasta que todos los archivos sean PDF.

### 6.2 Número de archivos permitidos

| Solicitud | Archivos |
|---|---|
| Solicitud de **gratificación** | **Un único** archivo (el formulario) |
| **Liquidación de gastos** | **Múltiples** archivos |
| Compra de bienes/servicios, material inventariable | Múltiples archivos |

### 6.3 Visibilidad de información económica

- El perfil **Gestor** **no** puede ver saldos, balances ni históricos: solo
  gestiona solicitudes de su equipo.
- Los **saldos de proyecto y de grupo** solo son visibles para Director Gerente,
  Responsable de Personal y Compras, el **Jefe de Equipo** correspondiente y el
  **responsable del proyecto**.
- Cada usuario **solo ve las solicitudes de su ámbito** (las propias o las de su
  equipo, según el perfil).

---

## 7. Trazabilidad de rechazos y nuevas versiones

Cuando una solicitud (por ejemplo, un documento) es **rechazada**, el flujo **no
se cierra**: se conserva todo el histórico y se permite **aportar una nueva
versión** dentro del mismo expediente.

**Cómo funciona:**

1. Al rechazar, la solicitud queda en estado **`Rechazada`** y se registra una
   nota en el histórico.
2. El **solicitante recibe un correo** con un **enlace** para acceder a la
   solicitud y **subir una nueva versión** del documento.
3. Al reenviar, la solicitud **vuelve al inicio del circuito** de aprobación
   **conservando el histórico completo** (no se empieza de cero). Si había una
   firma pendiente previa, se cancela automáticamente.

Esto permite corregir y reintentar sin perder la trazabilidad de las versiones
anteriores.

---

## 8. Firma electrónica y archivos firmados

- Cuando un documento se firma, el archivo resultante se guarda con el sufijo
  **`_firmado`** en el nombre, para **distinguirlo claramente del original** sin
  firma dentro del repositorio de documentos.
- El **listado de documentos** del portal muestra el **estado de la firma**
  mediante un distintivo (badge).
- El solicitante **mantiene la visibilidad** del documento durante todo el
  proceso de firma, aunque el documento pase a otra persona (por ejemplo, al
  Director Gerente) para firmarlo.

> **Nota sobre el entorno de pruebas (PRE):** la disponibilidad de la firma
> electrónica depende de que el **certificado de firma** esté instalado en el
> entorno. En entornos de preproducción puede no estar disponible.

---

## 9. Preguntas frecuentes

**¿Por qué no puedo subir un documento Word?**
Por seguridad y para asegurar la previsualización, el portal **solo admite
PDF**. Convierta el documento a PDF antes de subirlo.

**He rechazado/me han rechazado una solicitud, ¿tengo que empezar de nuevo?**
No. Use el **enlace del correo de rechazo** para subir una **nueva versión**
dentro del mismo expediente; se conserva todo el histórico.

**Aprobé una solicitud y ha desaparecido de mi portal.**
No debería: las solicitudes **permanecen visibles** tras aprobarse para su
seguimiento. Si no la ve, revise los filtros del listado.

**Soy Director Gerente y recibo correos de pagos pequeños.**
El sistema está configurado para avisar al DG **solo** cuando el importe supera
los **10.000 €**. Si recibe avisos de importes menores, comuníquelo a soporte.

**Creé un usuario y ha consumido licencia.**
Se creó como **usuario interno**. Para usuarios externos use **"Conceder acceso
al portal"** desde el Contacto; el usuario interno erróneo debe archivarse y
recrearse como usuario de portal.

**¿Qué diferencia hay entre "Gestor" y "Jefe de Equipo"?**
El **Gestor** es personal de apoyo que **envía solicitudes** de su equipo pero
**no ve información económica** ni aprueba. El **Jefe de Equipo** **aprueba** en
primera instancia y **sí ve** los saldos de su grupo/proyectos.

---

*Documento de referencia funcional del módulo `portal_requests`. Ante cualquier
discrepancia entre este manual y el comportamiento del sistema, contacte con
soporte para su revisión.*
