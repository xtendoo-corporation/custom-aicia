# Pruebas funcionales en navegador — Portal de Solicitudes AICIA

> **Para quién:** este documento está redactado como una secuencia de
> **instrucciones directas para un agente que controla un navegador** (por
> ejemplo, Claude con navegación web). Cada prueba es autónoma: incluye
> **precondiciones**, **pasos** (acciones concretas: navegar, escribir, hacer
> clic, subir archivo) y **resultado esperado** (qué comprobar).
>
> **Cómo usarlo:** ejecuta las pruebas en orden. Si una precondición no se
> cumple, prepárala primero o marca la prueba como *bloqueada* e indica el
> motivo. Al terminar cada prueba, anota **PASA** o **FALLA** con una captura y
> una frase describiendo lo observado.

---

## 0. Configuración inicial (rellena antes de empezar)

> Los nombres, logins y contraseñas concretos de cada usuario de prueba, junto
> con los pasos exactos para crearlos desde el navegador, están en
> [`USUARIOS_PRUEBA.md`](./USUARIOS_PRUEBA.md). Copia sus valores en la tabla
> siguiente.

Sustituye estos valores por los reales del entorno antes de ejecutar:

| Variable | Valor a usar | Ejemplo |
|---|---|---|
| `URL_BASE` | URL del portal | `https://pre.aicia.es` |
| `USER_GESTOR` / `PASS_GESTOR` | Usuario de portal con rol **Gestor** | |
| `USER_JEFE_EQUIPO` / `PASS_JEFE_EQUIPO` | Usuario **Jefe de Equipo** | |
| `USER_SOLICITANTE` / `PASS_SOLICITANTE` | Usuario que crea solicitudes | |
| `USER_DIRECTOR_ID` / `PASS_DIRECTOR_ID` | **Director I+D** (backend) | |
| `USER_RESP_COMPRAS` / `PASS_RESP_COMPRAS` | **Responsable de Personal y Compras** | |
| `USER_RESP_CLIENTES` / `PASS_RESP_CLIENTES` | **Responsable de Clientes y Becarios** | |
| `USER_DG` / `PASS_DG` | **Director Gerente** | |
| `PROYECTO_PRUEBA` | Nombre de un proyecto/analítica de prueba | |
| `EQUIPO_PRUEBA` | Equipo de trabajo (`portal.work.group`) al que pertenece `USER_SOLICITANTE` | |
| `EMPLEADO_INACTIVO` | Un `hr.employee` archivado, para probar altas (I3/J3) | |
| `EMPLEADO_ACTIVO` | Un `hr.employee` activo, para probar bajas (I4/J4) | |
| `USER_SIN_EMPLEADO` / `PASS_SIN_EMPLEADO` | Usuario de portal **sin** `hr.employee` vinculado (L1) | |
| `USER_CON_EMPLEADO` / `PASS_CON_EMPLEADO` | Usuario con `hr.employee` vinculado, para nóminas (L2-L5) | |
| `ATTACHMENT_ID_NOMINA_AJENA` | Id de un adjunto `nomina_*` de **otro** empleado (visible en backend → Adjuntos), para la prueba de seguridad L5 | |
| `PROVEEDOR_PRUEBA` | Un `res.partner` proveedor, para la orden de compra (G1) | |
| `EMAIL_BANDEJA` | Cómo revisar correos (buzón real o Odoo → Ajustes → Técnico → Correos electrónicos) | |

**Archivos de prueba que necesitarás preparar en el equipo:**
- `documento_valido.pdf` — un PDF real y válido.
- `documento_falso.txt` — un archivo de texto renombrado o no PDF.
- `falso.pdf` — un archivo con extensión `.pdf` pero contenido que **no** es PDF
  (por ejemplo, un `.txt` renombrado a `.pdf`).
- `nomina_enero_2025.pdf` — copia de `documento_valido.pdf` renombrada con el
  patrón `nomina_<concepto>_<año>.pdf`, para las pruebas del Bloque L.

> **Cómo verificar correos:** siempre que una prueba diga "comprueba que se envía
> un correo", revísalo en `EMAIL_BANDEJA`. En Odoo backend:
> **Ajustes → Técnico → Correo electrónico → Correos electrónicos** y filtra por
> destinatario/asunto.

---

## Bloque A — Acceso y perfiles de usuario

### A1. Acceso de un usuario de portal (Gestor)
**Precondiciones:** existe `USER_GESTOR`.
**Pasos:**
1. Navega a `URL_BASE/web/login`.
2. Escribe `USER_GESTOR` en el campo de email/usuario y `PASS_GESTOR` en
   contraseña. Haz clic en **Iniciar sesión**.
3. Navega a `URL_BASE/my`.
**Resultado esperado:** el usuario entra en el portal (`/my`) y ve el menú de
"Mi cuenta". **No** debe tener acceso al backend completo de Odoo (no aparece el
menú de aplicaciones interno).

### A2. El Gestor NO ve información económica
**Precondiciones:** sesión iniciada como `USER_GESTOR` (prueba A1).
**Pasos:**
1. Navega a `URL_BASE/my/expenses`.
2. Abre una solicitud de gasto de su equipo (si existe) o navega a
   `URL_BASE/my/analytic_projects`.
**Resultado esperado:** el Gestor puede ver las solicitudes **de su equipo**,
pero **no** aparecen saldos de proyecto/grupo, balances ni históricos económicos.

### A3. El Gestor solo ve solicitudes de su equipo
**Precondiciones:** existen solicitudes de al menos dos equipos distintos.
**Pasos:**
1. Como `USER_GESTOR`, navega a `URL_BASE/my/documents` y luego a
   `URL_BASE/my/invoices` y `URL_BASE/my/expenses`.
2. Revisa los listados.
**Resultado esperado:** solo aparecen solicitudes asociadas al/los equipo(s) del
Gestor. No debe ver solicitudes de otros equipos.

---

## Bloque B — Restricción de formato PDF

### B1. Rechazo de archivo que no es PDF
**Objetivo:** el portal debe rechazar cualquier archivo que no sea PDF.
**Precondiciones:** sesión como `USER_SOLICITANTE`. Tener `documento_falso.txt`.
**Pasos:**
1. Navega a `URL_BASE/portal/approval_request`.
2. En **Tipo**, selecciona **"Solicitud firma NDA"**.
3. Escribe una descripción de prueba, por ejemplo `Prueba PDF no válido`.
4. Selecciona un grupo de trabajo si el formulario lo pide.
5. En el campo de archivo, sube `documento_falso.txt`.
6. Haz clic en **Enviar**.
**Resultado esperado:** la solicitud **NO** se completa. Aparece un aviso
indicando que solo se admiten archivos PDF (menciona el archivo rechazado). **No**
se llega a la página de agradecimiento y **no** se crea la solicitud.

### B2. Rechazo de archivo con extensión .pdf pero contenido falso
**Precondiciones:** sesión como `USER_SOLICITANTE`. Tener `falso.pdf` (contenido
no PDF).
**Pasos:**
1. Navega a `URL_BASE/portal/approval_request`.
2. Selecciona **"Solicitud firma NDA"**, escribe una descripción y sube
   `falso.pdf`.
3. Haz clic en **Enviar**.
**Resultado esperado:** la solicitud se **rechaza igualmente** (la validación
comprueba el contenido real, no solo la extensión). No se crea la solicitud.

### B3. Aceptación de un PDF válido
**Precondiciones:** sesión como `USER_SOLICITANTE`. Tener `documento_valido.pdf`.
**Pasos:**
1. Navega a `URL_BASE/portal/approval_request`.
2. Selecciona **"Solicitud firma NDA"**, escribe `Prueba PDF válido` y sube
   `documento_valido.pdf`.
3. Haz clic en **Enviar**.
**Resultado esperado:** la solicitud se **crea correctamente** y el navegador
llega a la página de **agradecimiento** (`/my/documents/thank-you`). La solicitud
aparece luego en `URL_BASE/my/documents`.

---

## Bloque C — Firma de documentos y trazabilidad

### C1. Listado de documentos muestra fecha y estado
**Precondiciones:** existe al menos una solicitud de documento (prueba B3).
**Pasos:**
1. Como `USER_SOLICITANTE`, navega a `URL_BASE/my/documents`.
**Resultado esperado:** cada fila muestra la **fecha de creación** y un
**distintivo de estado** (badge). Las solicitudes aprobadas **siguen visibles**
(no desaparecen).

### C2. El tipo "Solicitud colaboración PAS" ya NO aparece
**Precondiciones:** sesión como `USER_SOLICITANTE`.
**Pasos:**
1. Navega a `URL_BASE/portal/approval_request`.
2. Despliega el selector **Tipo**.
**Resultado esperado:** las opciones disponibles son **NDA**, **contrato con
empresa**, **autorización de salida** y **salida de viaje**. **No** debe aparecer
"Solicitud colaboración PAS".

### C3. Rechazo de un documento y reenvío de nueva versión (histórico)
**Objetivo:** al rechazar, el flujo no se cierra y se puede aportar nueva versión.
**Precondiciones:** existe una solicitud de documento pendiente (B3). Acceso al
backend como `USER_DIRECTOR_ID` (o el rol que rechaza).
**Pasos:**
1. Inicia sesión como `USER_DIRECTOR_ID` en `URL_BASE/web`.
2. Abre la solicitud de documento de la prueba B3 (Solicitudes del Portal →
   Documentos).
3. Pulsa **Rechazar**.
4. Cierra sesión y revisa `EMAIL_BANDEJA`: el **solicitante** debe haber recibido
   un correo de rechazo **con un enlace** a la solicitud.
5. Inicia sesión como `USER_SOLICITANTE`, abre el enlace del correo (o navega a
   `URL_BASE/my/documents` y abre la solicitud rechazada).
6. Sube una **nueva versión** en PDF (`documento_valido.pdf`) y reenvía.
**Resultado esperado:**
- Tras el rechazo, el estado es **"Rechazada"** y el flujo **no** se cierra.
- El solicitante recibe correo con enlace.
- Al reenviar, la solicitud vuelve al inicio del circuito y **conserva el
  histórico** (las notas anteriores siguen visibles en el hilo/chatter).

### C4. El solicitante conserva la visibilidad durante la firma
**Precondiciones:** una solicitud de documento que pase a estado de firma.
**Pasos:**
1. Haz avanzar la solicitud hasta **"Esperando firma de empresa"** (aprobándola
   con los roles correspondientes en backend).
2. Inicia sesión como `USER_SOLICITANTE` y navega a `URL_BASE/my/documents`;
   abre la solicitud.
**Resultado esperado:** el solicitante **sigue viendo** el documento y su estado
aunque haya pasado a otra persona para firmar.

### C5. El archivo firmado se distingue con sufijo `_firmado`
**Precondiciones:** un documento ya firmado en el sistema.
**Pasos:**
1. En backend, abre el documento firmado y revisa sus adjuntos (o el repositorio
   de documentos).
**Resultado esperado:** el archivo firmado incluye el sufijo **`_firmado`** en su
nombre, diferenciándose del original sin firma.

---

## Bloque D — Notificaciones automáticas de estado

### D1. El solicitante recibe correo en cada cambio de estado
**Objetivo:** verificar que cada transición notifica al solicitante.
**Precondiciones:** una solicitud (documento o gasto) con solicitante que tenga
email.
**Pasos:**
1. Anota el estado actual de una solicitud del `USER_SOLICITANTE`.
2. En backend, con el rol adecuado, haz avanzar la solicitud **un** paso de
   estado (aprobar/rechazar).
3. Revisa `EMAIL_BANDEJA` del solicitante.
**Resultado esperado:** el solicitante recibe **un** correo indicando el **nuevo
estado**, con un **enlace** a la solicitud en el portal.

### D2. No se notifica si el estado no cambia
**Precondiciones:** una solicitud existente.
**Pasos:**
1. En backend, guarda la solicitud **sin** cambiar su estado (edita otro campo
   irrelevante o simplemente guarda).
2. Revisa `EMAIL_BANDEJA`.
**Resultado esperado:** **no** se genera correo de cambio de estado.

### D3. Notificación al aprobador correspondiente
**Precondiciones:** crear una solicitud nueva de cada tipo.
**Pasos:**
1. Crea una **solicitud de firma de documento** (B3) → revisa que se notifica al
   **Director I+D**.
2. Crea una **solicitud de emisión de factura** (Bloque E) → revisa que se
   notifica al **Responsable de Clientes** (`clientes@aicia.es`).
3. Crea una **solicitud de pago / orden de compra** → revisa que se notifica al
   **Responsable de Proveedores** (`personal@aicia.es`).
**Resultado esperado:** cada nueva solicitud genera correo **al responsable
correcto** de ese flujo.

---

## Bloque E — Emisión de factura

### E1. Campo de comentarios y datos en la notificación
**Precondiciones:** sesión como `USER_SOLICITANTE`; existe `PROYECTO_PRUEBA` con
cliente asociado.
**Pasos:**
1. Navega a `URL_BASE/portal/invoice_request`.
2. Selecciona el proyecto `PROYECTO_PRUEBA` y el cliente.
3. Rellena el **campo de comentarios/concepto** con un texto reconocible, por
   ejemplo `Enviar a dirección X - prueba`.
4. Adjunta `documento_valido.pdf` si el formulario lo permite y **Envía**.
5. Revisa `EMAIL_BANDEJA` del **Responsable de Clientes**.
**Resultado esperado:** existe un **campo de comentarios** en el formulario. El
correo al Responsable de Clientes incluye el **código del proyecto**, la
**referencia interna** y el **comentario** introducido. El cliente aparece
identificado como **cliente** (no como proveedor).

---

## Bloque F — Solicitudes de gasto y umbral de 10.000 €

### F1. Gratificación: solo permite un archivo
**Precondiciones:** sesión como `USER_SOLICITANTE`; dos PDF válidos.
**Pasos:**
1. Navega a `URL_BASE/portal/hr_expensive_request`.
2. En **Tipo**, selecciona **"Solicitud de gratificación"**.
3. Selecciona `PROYECTO_PRUEBA`.
4. Intenta adjuntar **dos** archivos PDF.
5. **Envía**.
**Resultado esperado:** solo se registra **un** archivo (el primero); la
gratificación admite un único documento. La solicitud se crea correctamente.

### F2. Liquidación de gastos: permite múltiples archivos
**Precondiciones:** sesión como `USER_SOLICITANTE`; varios PDF válidos.
**Pasos:**
1. Navega a `URL_BASE/portal/hr_expensive_request`.
2. Selecciona **"Liquidación de gastos"** y `PROYECTO_PRUEBA`.
3. Adjunta **varios** PDF y **Envía**.
**Resultado esperado:** la solicitud se crea con **todos** los archivos
adjuntos.

### F2b. Pago de material inventariable: archivo de inventario con prefijo
**Precondiciones:** sesión como `USER_SOLICITANTE`; dos PDF válidos.
**Pasos:**
1. Navega a `URL_BASE/portal/hr_expensive_request`.
2. Selecciona **"Pago de material inventariable"** y `PROYECTO_PRUEBA`.
3. Adjunta un PDF como justificante y otro en el campo específico de
   **archivo de inventario**.
4. **Envía**.
**Resultado esperado:** la solicitud se crea con ambos adjuntos; el archivo de
inventario se guarda con el nombre prefijado **`inventario_<nombre original>`**
para distinguirlo del resto de justificantes.

### F3. Gasto por debajo de 10.000 € — el DG NO es notificado
**Objetivo:** verificar el umbral.
**Precondiciones:** poder aprobar como `USER_JEFE_EQUIPO` y `USER_RESP_COMPRAS`.
**Pasos:**
1. Como `USER_SOLICITANTE`, crea una **Compra de bienes o servicios** en
   `PROYECTO_PRUEBA` con importe **inferior a 10.000 €** (deja la casilla de
   ">10.000 €" **sin** marcar) y adjunta `documento_valido.pdf`. **Envía**.
2. Como `USER_JEFE_EQUIPO`, aprueba la solicitud en backend.
3. Como `USER_RESP_COMPRAS`, aprueba la solicitud.
4. Revisa `EMAIL_BANDEJA` del **Director Gerente**.
**Resultado esperado:** tras la aprobación del Responsable de Compras, la
solicitud queda **"Aprobada"** directamente. El **Director Gerente NO** recibe
ninguna notificación.

### F4. Gasto por encima de 10.000 € — el DG SÍ es notificado
**Precondiciones:** igual que F3.
**Pasos:**
1. Como `USER_SOLICITANTE`, crea una **Compra de bienes o servicios** con importe
   **superior a 10.000 €** (marca la opción ">10.000 €" si el formulario la
   ofrece). Adjunta PDF y **Envía**.
2. Aprueba como `USER_JEFE_EQUIPO` y después como `USER_RESP_COMPRAS`.
3. Revisa `EMAIL_BANDEJA` del **Director Gerente**.
**Resultado esperado:** la solicitud pasa a **"Aprobación del Director Gerente"**
y el **DG recibe** un correo de notificación. La solicitud no se cierra hasta que
el DG la aprueba.

### F5. Gratificación se dirige al Responsable de Clientes y Becarios
**Precondiciones:** una gratificación creada (F1).
**Pasos:**
1. Como `USER_JEFE_EQUIPO`, aprueba la gratificación.
2. Revisa `EMAIL_BANDEJA` del **Responsable de Clientes y Becarios**.
**Resultado esperado:** el segundo aprobador notificado para la **gratificación**
es el **Responsable de Clientes y Becarios** (`clientes@aicia.es`), no el de
Compras.

---

## Bloque G — Pagos / órdenes de compra

> **Nota de código (verificar con negocio):** el controlador de
> `/portal/purchase_order_request` notifica actualmente a los usuarios del
> grupo técnico **"Ajustes → Usuarios y compañías"** (`base.group_system`,
> administradores del sistema), **no** al grupo funcional "Responsable de
> Personal y Compras" (`personal@aicia.es`) que describe el manual de usuario.
> La prueba G1 debe ejecutarse comprobando **ambos** buzones para confirmar
> cuál es el comportamiento real y si coincide con lo esperado por negocio.

### G1. Notificación al crear una orden de compra
**Precondiciones:** sesión como `USER_SOLICITANTE`; existe un proveedor
(`res.partner`) de prueba.
**Pasos:**
1. Navega a `URL_BASE/portal/purchase_order_request`.
2. Selecciona el **proveedor**, escribe un **concepto** reconocible (p. ej.
   `Concepto prueba G1`) y **Envía**.
3. Revisa `EMAIL_BANDEJA` de los **administradores del sistema** (`base.group_system`)
   y, por comparación, la del **Responsable de Personal y Compras**.
**Resultado esperado:** se crea una `purchase.order` en borrador con una línea
de nota (sin producto ni importe) con el concepto introducido. Se envía un
correo con el nombre del proveedor, la referencia de la orden y el concepto.
Anota **a quién llega realmente** el correo (para contrastar con el manual).

### G2. Redirección tras enviar la orden de compra
**Precondiciones:** igual que G1.
**Pasos:**
1. Repite el envío de G1.
2. Observa la URL final del navegador tras pulsar **Enviar**.
**Resultado esperado:** *(caso a confirmar)* la redirección actual es a
`/contactus-thank-you` (página genérica de contacto), no a una página de
agradecimiento propia del flujo de pagos/compras como ocurre en documentos,
facturas o gastos. Confirma si esto es intencionado o una inconsistencia a
corregir.

### G3. Visualización/descarga de adjuntos en solicitudes pendientes
**Precondiciones:** una solicitud (proyecto o pago) con adjuntos, en estado
pendiente.
**Pasos:**
1. Como el usuario correspondiente, abre la solicitud en el portal.
2. Intenta **previsualizar** y **descargar** el adjunto.
**Resultado esperado:** el adjunto se **visualiza y descarga** correctamente
(prueba de regresión del error de renombrado/procesado de archivos).

### G4. Acceso al listado y detalle de pagos (`/my/payments`)
**Precondiciones:** un pago (`account.payment`) vinculado a una factura con
distribución analítica sobre un proyecto cuyo **responsable** es
`USER_SOLICITANTE` (o su Jefe de Equipo).
**Pasos:**
1. Inicia sesión como el usuario responsable del proyecto.
2. Navega a `URL_BASE/my/payments`.
3. Abre el detalle de un pago concreto.
**Resultado esperado:** el listado muestra el pago; el detalle muestra el
**importe** correctamente. Un usuario **sin relación** con el proyecto no debe
ver ese pago en su listado.

---

## Bloque H — Proyectos e investigadores

### H1. Asociar investigadores a un proyecto desde la vista de proyecto
**Precondiciones:** acceso a la vista de proyecto (backend) con el rol adecuado.
**Pasos:**
1. Abre un proyecto en backend.
2. Localiza la sección de **investigadores/participantes**.
3. **Añade** un investigador, indica su **porcentaje de dedicación** y la
   **fecha de inicio** de la relación.
4. Para un docente sin nómina, deja el porcentaje al **0 %**.
5. Guarda.
**Resultado esperado:** se pueden **ver y editar** los participantes desde la
vista de proyecto; se guardan el porcentaje y la fecha de inicio; el 0 % no
provoca errores de cálculo.

---

## Bloque I — Solicitudes de personal: Empleado

**Formulario:** `URL_BASE/portal/hr_employee_request` · **Modelo:**
`portal.hr.employee.request` · **Tipos:** `new` (nuevo), `alta`, `baja`.

> **Nota de código (verificar con negocio):** en el controlador, el correo de
> notificación al **Responsable de Clientes y Becarios** para el tipo `new`
> solo se envía **dentro del bloque que procesa el archivo `prl_annex`**. Si el
> solicitante no adjunta el anexo PRL, la solicitud se crea igualmente pero **no
> se envía ningún correo**. Además, el tipo `alta` **no envía correo en ningún
> caso** (solo `new` y `baja` lo hacen). Las pruebas I2 e I3 verifican
> explícitamente estos dos casos.

### I1. Alta de nuevo empleado con todos los documentos
**Precondiciones:** sesión como `USER_SOLICITANTE`; tres PDF válidos
(`documento_valido.pdf` sirve para los tres).
**Pasos:**
1. Navega a `URL_BASE/portal/hr_employee_request`.
2. Selecciona **Tipo: Nuevo**, rellena nombre, identificación, teléfono,
   email de trabajo, salario, número de pagas, calendario de recursos y cuenta
   bancaria.
3. Adjunta un PDF en **cada uno** de los tres campos: informe de vida laboral,
   CV y anexo PRL.
4. **Envía**.
5. Revisa `EMAIL_BANDEJA` del **Responsable de Clientes y Becarios**.
**Resultado esperado:** se crea la solicitud (`portal.hr.employee.request`,
tipo `new`) con los tres adjuntos. El Responsable de Clientes y Becarios
**recibe** un correo con el nombre del solicitante, el proyecto y un enlace a
la solicitud.

### I2. Alta de nuevo empleado SIN anexo PRL — comprobar si notifica
**Precondiciones:** igual que I1 pero sin el archivo de anexo PRL.
**Pasos:**
1. Repite I1 dejando **vacío** el campo de anexo PRL (solo sube vida laboral y
   CV).
2. **Envía**.
3. Revisa `EMAIL_BANDEJA` del Responsable de Clientes y Becarios.
**Resultado esperado:** *(caso a confirmar, ver nota de código superior)* la
solicitud se crea correctamente con los dos adjuntos aportados, pero **no**
llega correo de notificación al Responsable, porque el envío está condicionado
a la presencia del anexo PRL. Documenta si esto reproduce el comportamiento
descrito.

### I3. Reactivación de un empleado inactivo (tipo "alta") — comprobar si notifica
**Precondiciones:** existe un `hr.employee` **archivado** (inactivo) en el
sistema.
**Pasos:**
1. Navega a `URL_BASE/portal/hr_employee_request`.
2. Selecciona **Tipo: Alta**, elige el empleado inactivo y una fecha de alta.
3. **Envía**.
4. Revisa `EMAIL_BANDEJA` del Responsable de Clientes y Becarios.
**Resultado esperado:** *(caso a confirmar)* se crea la solicitud de alta, pero
**no se envía ningún correo** de notificación (el controlador no llama al envío
de correo para este tipo). Confirma si el Responsable debería ser notificado
también en este caso.

### I4. Baja de un empleado activo
**Precondiciones:** existe un `hr.employee` activo.
**Pasos:**
1. Navega a `URL_BASE/portal/hr_employee_request`.
2. Selecciona **Tipo: Baja**, elige el empleado, la fecha de baja, el motivo de
   baja y notas adicionales.
3. **Envía**.
4. Revisa `EMAIL_BANDEJA` del Responsable de Clientes y Becarios.
**Resultado esperado:** se crea la solicitud de baja y el Responsable de
Clientes y Becarios **recibe** correo de notificación.

### I5. Rechazo de archivos no PDF en la solicitud de empleado
**Precondiciones:** sesión como `USER_SOLICITANTE`; `documento_falso.txt`.
**Pasos:**
1. Repite I1 pero sube `documento_falso.txt` en el campo de CV.
2. **Envía**.
**Resultado esperado:** la solicitud **no se completa**; el sistema exige PDF
también en este formulario (informe de vida laboral, CV y anexo PRL).

### I6. Aprobación de una solicitud de empleado nuevo (backend)
**Precondiciones:** una solicitud tipo `new` creada (I1), acceso backend con
permiso sobre `portal.hr.employee.request`.
**Pasos:**
1. En backend, abre **Solicitudes del Portal → Solicitudes de Empleado**.
2. Abre la solicitud de I1 y pulsa **Aprobar**.
**Resultado esperado:** se crea un registro `hr.employee` con los datos de la
solicitud y los adjuntos se copian al nuevo empleado; la solicitud queda
marcada como **aprobada** y **revisada**; el solicitante recibe correo de
cambio de estado ("Aprobada").

---

## Bloque J — Solicitudes de personal: Becario

**Formulario:** `URL_BASE/portal/hr_employee_intern_request` · **Modelo:**
`portal.hr.employee.intern.request` · **Tipos:** `new`, `alta`, `baja`.

El formulario y la lógica son estructuralmente **idénticos** al Bloque I
(mismo patrón de controlador y modelo, aplicado a becarios). Repite las mismas
pruebas cambiando de formulario:

### J1. Alta de nuevo becario con todos los documentos
Repite I1 en `URL_BASE/portal/hr_employee_intern_request`. **Resultado
esperado:** igual que I1 (correo "Solicitud de nuevo becario" al Responsable de
Clientes y Becarios).

### J2. Alta de nuevo becario SIN anexo PRL — comprobar si notifica
Repite I2 en el formulario de becario. **Resultado esperado:** *(caso a
confirmar)* mismo comportamiento que I2: sin anexo PRL, no se envía correo.

### J3. Reactivación de un becario inactivo (tipo "alta") — comprobar si notifica
Repite I3 en el formulario de becario. **Resultado esperado:** *(caso a
confirmar)* mismo comportamiento que I3: no se envía correo para "alta".

### J4. Baja de un becario activo
Repite I4 en el formulario de becario. **Resultado esperado:** se notifica
correctamente ("Solicitud de baja de becario") al Responsable de Clientes y
Becarios.

### J5. Rechazo de archivos no PDF en la solicitud de becario
Repite I5 en el formulario de becario. **Resultado esperado:** igual que I5.

---

## Bloque K — Apertura y cierre de proyecto (dos rutas distintas)

> **Nota de código (verificar con negocio):** el módulo expone **dos** vías
> distintas para el "cierre de proyecto", con modelos y destinatarios
> **diferentes**:
> - `URL_BASE/portal/project_request` con **Tipo: Finalizar Proyecto**, que
>   crea un `portal.project.request` y notifica al **Director I+D**.
> - `URL_BASE/portal/project_end_request` (formulario independiente), que crea
>   un `portal.project.end.request` y notifica a los **administradores del
>   sistema** (`base.group_system`), no al Director I+D.
>
> Las pruebas K3 y K4 comprueban ambas rutas por separado; documenta cuál es la
> vía "oficial" y si la duplicidad es intencionada.

### K1. Apertura de nuevo proyecto con contrato y presupuesto en PDF
**Precondiciones:** sesión como `USER_SOLICITANTE`, miembro de un equipo de
trabajo (`portal.work.group`); dos PDF válidos.
**Pasos:**
1. Navega a `URL_BASE/portal/project_request`.
2. Selecciona **Tipo: Nuevo Proyecto**, el **equipo de trabajo**, nombre del
   proyecto, cliente, fechas de inicio y fin.
3. Adjunta `documento_valido.pdf` como **contrato firmado** y como
   **presupuesto**.
4. **Envía**.
5. Revisa `EMAIL_BANDEJA` del **Director I+D**.
**Resultado esperado:** se crea el `portal.project.request` (tipo `new`) con
ambos adjuntos; el Director I+D recibe correo con el nombre del proyecto y las
fechas.

### K2. Rechazo de archivos no PDF en la apertura de proyecto
**Precondiciones:** igual que K1; `documento_falso.txt`.
**Pasos:**
1. Repite K1 subiendo `documento_falso.txt` como presupuesto.
2. **Envía**.
**Resultado esperado:** la solicitud **no se completa** (validación PDF sobre
contrato y presupuesto).

### K3. Cierre de proyecto — vía `/portal/project_request` (tipo "Finalizar Proyecto")
**Precondiciones:** existe un proyecto analítico (`account.analytic.account`)
del equipo del solicitante.
**Pasos:**
1. Navega a `URL_BASE/portal/project_request`.
2. Selecciona **Tipo: Finalizar Proyecto**, elige el **proyecto** de la lista,
   la **fecha de fin** y un **concepto**.
3. **Envía**.
4. Revisa `EMAIL_BANDEJA` del **Director I+D**.
**Resultado esperado:** se crea el `portal.project.request` (tipo `end`); el
Director I+D recibe correo "Solicitud de Finalización de proyecto".

### K4. Cierre de proyecto — vía `/portal/project_end_request` (formulario alternativo)
**Precondiciones:** sesión como `USER_SOLICITANTE`.
**Pasos:**
1. Navega a `URL_BASE/portal/project_end_request`.
2. Rellena **compañía/proyecto**, **fecha de fin** y **concepto**.
3. **Envía**.
4. Revisa `EMAIL_BANDEJA` de los **administradores del sistema**
   (`base.group_system`) y, por comparación, la del Director I+D.
**Resultado esperado:** *(caso a confirmar)* se crea un
`portal.project.end.request` independiente del anterior; el correo llega a los
administradores del sistema, **no** al Director I+D. Confirma con negocio si
ambas rutas deben coexistir o si una debe eliminarse/redirigirse a la otra.

---

## Bloque L — Nóminas (`/my/nomina`)

Las nóminas se gestionan como **adjuntos** (`ir.attachment`) sobre el
`hr.employee` vinculado al usuario, con el nombre en el patrón
`nomina_<algo>_<año>.pdf` (el año se extrae del último segmento antes de la
extensión).

**Archivo de prueba adicional necesario:** un PDF nombrado siguiendo el patrón,
por ejemplo `nomina_enero_2025.pdf` (contenido de `documento_valido.pdf`).

### L1. Usuario sin empleado vinculado
**Precondiciones:** un usuario de portal **sin** `hr.employee` asociado
(`user_id` no coincide con ningún empleado).
**Pasos:**
1. Inicia sesión con ese usuario y navega a `URL_BASE/my/nomina`.
**Resultado esperado:** se muestra una página de "sin datos" (no hay
nóminas ni errores); no se produce un error 500.

### L2. Empleado sin nóminas adjuntas
**Precondiciones:** usuario con `hr.employee` vinculado, sin adjuntos
`nomina_*`.
**Pasos:**
1. Navega a `URL_BASE/my/nomina`.
**Resultado esperado:** el listado aparece **vacío**, sin errores.

### L3. Listado y agrupación por año
**Precondiciones:** el empleado del usuario tiene adjunto
`nomina_enero_2025.pdf` (subido en backend sobre su `hr.employee`).
**Pasos:**
1. Navega a `URL_BASE/my/nomina`.
2. Cambia el agrupamiento a **"Año"**.
**Resultado esperado:** la nómina aparece listada; al agrupar por año, se
muestra bajo el grupo **"2025"**.

### L4. Descarga de la propia nómina
**Precondiciones:** igual que L3.
**Pasos:**
1. Desde `URL_BASE/my/nomina`, pulsa **descargar** sobre `nomina_enero_2025.pdf`.
**Resultado esperado:** el PDF se descarga correctamente con el nombre
original.

### L5. Intento de descarga de la nómina de OTRO empleado (control de acceso)
**Precondiciones:** un adjunto `nomina_*` perteneciente a **otro** empleado
(no el del usuario logueado); anota su `attachment_id` (visible en backend).
**Pasos:**
1. Inicia sesión como `USER_SOLICITANTE` (u otro usuario con empleado propio).
2. Navega directamente a
   `URL_BASE/my/nomina/download/<attachment_id_de_otro_empleado>`, sustituyendo
   por el id anotado.
**Resultado esperado:** el sistema **deniega** el acceso (página no encontrada
o error), **no** debe descargar el PDF de otro empleado. Esta es una prueba de
seguridad importante (control de acceso indebido/IDOR) y debe **pasar
obligatoriamente**.

---

## Bloque M — Rechazo de solicitudes con motivo (asistentes de rechazo)

Aplica a **solicitudes de gasto** (`purchase.request.reject.wizard`) y
**solicitudes de factura** (`invoice.request.reject.wizard`), ambos accesibles
solo desde backend.

### M1. Rechazo de un gasto con motivo — el solicitante no es el Jefe de Equipo
**Precondiciones:** una solicitud de gasto en estado `Aprobación del Jefe de
Equipo` o posterior, cuyo solicitante **no** sea el Jefe de Equipo del
proyecto. Acceso backend con rol que pueda rechazar (Jefe de Equipo o
Responsable de Compras, según el estado).
**Pasos:**
1. En backend, abre la solicitud de gasto.
2. Pulsa **Rechazar** (abre el asistente de rechazo).
3. Escribe una **descripción** del motivo, por ejemplo `Falta justificante`.
4. Confirma.
**Resultado esperado:** la solicitud pasa a estado **`Volver a revisar`**; se
añade una nota en el chatter con el motivo; el **solicitante** recibe un correo
de rechazo con el motivo.

### M2. Rechazo de un gasto con motivo — el solicitante SÍ es el Jefe de Equipo
**Precondiciones:** una solicitud de gasto creada por el propio Jefe de Equipo
del proyecto.
**Pasos:**
1. Repite M1 sobre esta solicitud.
**Resultado esperado:** al rechazar, la solicitud vuelve a
**`Aprobación del Jefe de Equipo`** (no a "Volver a revisar", porque el
solicitante y el jefe de equipo son la misma persona) y se notifica igualmente
con el motivo.

### M3. Rechazo de una solicitud de factura con motivo
**Precondiciones:** una solicitud de emisión de factura pendiente.
**Pasos:**
1. En backend, abre la solicitud de factura y pulsa **Rechazar**.
2. Escribe un motivo y confirma.
**Resultado esperado:** mismo comportamiento que M1/M2 aplicado a
`portal.invoice.request` (estado `to_revise` o `approved_by_boss_group` según
quién solicitó, nota en el chatter y correo al solicitante con el motivo).

---

## Bloque N — Dashboard de solicitudes por rol

**Modelo:** `portal.request.dashboard` · **Acceso:** backend, menú principal de
Solicitudes del Portal.

### N1. El Director I+D ve solo los documentos que le corresponden
**Precondiciones:** documentos en distintos estados (`approved_by_director_i_d`,
`sign_company`, `final_revision`, `approved_by_director_gerente`).
**Pasos:**
1. Inicia sesión como `USER_DIRECTOR_ID` y abre el dashboard.
2. Pulsa la tarjeta **"Documentos para revisar"**.
**Resultado esperado:** el listado solo incluye documentos en los estados
`approved_by_director_i_d`, `final_revision` y `sign_company`; **no** aparecen
los que ya están en `approved_by_director_gerente`.

### N2. El Responsable de Personal y Compras ve solo los gastos en su paso
**Precondiciones:** gastos en distintos estados.
**Pasos:**
1. Inicia sesión como `USER_RESP_COMPRAS` y abre el dashboard.
2. Pulsa **"Gastos para revisar"**.
**Resultado esperado:** solo aparecen gastos en estado
`approved_purchase_responsible`.

### N3. El Jefe de Equipo ve solo los gastos de su propio equipo
**Precondiciones:** gastos en estado `approved_by_boss_group` de distintos
equipos.
**Pasos:**
1. Inicia sesión como `USER_JEFE_EQUIPO` y abre el dashboard.
2. Pulsa **"Gastos para revisar"**.
**Resultado esperado:** solo aparecen los gastos cuyo `equip_boss` es
`USER_JEFE_EQUIPO`; no aparecen los de otros equipos.

---

## Bloque O — Firma digital (Sign)

> Requiere que el módulo `sign` (Enterprise) esté disponible y, si aplica, el
> certificado de firma instalado en el entorno (ver nota en
> [sección 8 del manual](../MANUAL_USUARIO.md#8-firma-electrónica-y-archivos-firmados)).

### O1. Enviar a firmar un documento sin adjunto — debe bloquearse
**Precondiciones:** un `document.approval` **sin** ningún adjunto PDF asociado.
**Pasos:**
1. En backend, abre el documento y pulsa **"Enviar a firmar"**
   (`action_send_to_sign`).
**Resultado esperado:** el sistema **bloquea** la acción con un aviso claro
indicando que hay que subir el PDF antes de enviar a firmar. No se crea
ninguna plantilla de firma.

### O2. Reenvío a firma cancela la solicitud de firma anterior
**Precondiciones:** un documento que ya tiene una `sign.request` **pendiente**
(no firmada) asociada (de un envío previo a firmar).
**Pasos:**
1. Pulsa de nuevo **"Enviar a firmar"** sobre el mismo documento.
**Resultado esperado:** la solicitud de firma anterior queda **cancelada** y se
genera una plantilla/solicitud de firma nueva; no quedan dos solicitudes de
firma activas simultáneamente para el mismo documento.

---

## Plantilla de resultados

Rellena una fila por prueba ejecutada:

| Prueba | Resultado (PASA/FALLA/BLOQUEADA) | Observaciones | Captura |
|---|---|---|---|
| A1 | | | |
| A2 | | | |
| A3 | | | |
| B1 | | | |
| B2 | | | |
| B3 | | | |
| C1 | | | |
| C2 | | | |
| C3 | | | |
| C4 | | | |
| C5 | | | |
| D1 | | | |
| D2 | | | |
| D3 | | | |
| E1 | | | |
| F1 | | | |
| F2 | | | |
| F3 | | | |
| F4 | | | |
| F5 | | | |
| G1 | | | |
| G2 | | | |
| G3 | | | |
| G4 | | | |
| H1 | | | |
| I1 | | | |
| I2 | | | |
| I3 | | | |
| I4 | | | |
| I5 | | | |
| I6 | | | |
| J1 | | | |
| J2 | | | |
| J3 | | | |
| J4 | | | |
| J5 | | | |
| K1 | | | |
| K2 | | | |
| K3 | | | |
| K4 | | | |
| L1 | | | |
| L2 | | | |
| L3 | | | |
| L4 | | | |
| L5 | | | |
| M1 | | | |
| M2 | | | |
| M3 | | | |
| N1 | | | |
| N2 | | | |
| N3 | | | |
| O1 | | | |
| O2 | | | |

> **Al terminar:** entrega un resumen con el número de pruebas PASA/FALLA/
> BLOQUEADA y, para cada FALLA, los pasos exactos para reproducirla. Marca con
> especial atención las pruebas de **seguridad** (L5) y las marcadas como
> *"caso a confirmar"* (I2, I3, J2, J3, G1, G2, K4), que reflejan
> comportamientos observados en el código a validar con negocio, no bugs
> confirmados.

---

## Anexo — Relación de ficheros del módulo por bloque

Para quien ejecute o revise las pruebas y necesite consultar el código fuente
que implementa cada caso de uso (ruta relativa a
`odoo/custom/src/custom-aicia/portal_requests/`):

| Bloque | Controlador(es) | Modelo(s) | Vista(s) principal(es) | Tests unitarios relacionados |
|---|---|---|---|---|
| A — Acceso y perfiles | `controllers/portal_main.py`, `controllers/portal_utils.py` | `models/res_users.py`, `models/work_group.py` | `views/portal_user_templates/*` | `tests/test_gestor_access.py` |
| B — Restricción PDF | `controllers/portal_pdf_utils.py`, `controllers/portal_approval_request_controller.py` | — | `views/portal_approval_request_template.xml` | `tests/test_pdf_utils.py`, `tests/test_pdf_restriction_http.py` |
| C — Firma y trazabilidad | `controllers/portal_approval_request_controller.py` | `models/document_approval.py`, `models/sign_request_inherit.py` | `views/portal_my_document_detail.xml`, `views/interface/aicia_approval_documents.xml` | `tests/test_document_resubmit.py`, `tests/test_signed_suffix.py` |
| D — Notificaciones de estado | `models/portal_request_notify_mixin.py` | (mixin usado por todos los modelos de solicitud) | — | `tests/test_state_change_notifications.py`, `tests/test_notification_recipients.py` |
| E — Emisión de factura | `controllers/portal_invoice_requests_controller.py` | `models/portal_inovice_requests_model.py` | `views/portal_invoice_requests_template.xml`, `views/portal_user_templates/portal_my_invoice_detail.xml` | — |
| F — Gastos y umbral 10.000 € | `controllers/portal_hr_expensive_request_controller.py` | `models/portal_hr_expensive_request_model.py` | `views/interface/portal_hr_expensive_request.xml` | `tests/test_expense_threshold.py`, `tests/test_expense_type.py` |
| G — Pagos / órdenes de compra | `controllers/portal_purchase_order_requests_controller.py`, `controllers/portal_payment_requests_controller.py` | `models/account_payment.py` | `views/portal_user_templates/portal_my_payments.xml`, `views/portal_user_templates/portal_my_payment_detail.xml`, `views/account_payment_views.xml` | `tests/test_portal_payments.py` |
| H — Proyectos e investigadores | — (vista heredada de proyecto) | `models/project_project_inherit.py`, `models/account_analytic_inherit.py` | `views/interface/account_analytic_inherit_views.xml` | — |
| I — Empleado | `controllers/portal_hr_employee_request_controller.py` | `models/portal_hr_employee_request_model.py` | `views/portal_hr_employee_requests_template.xml`, `views/interface/portal_employee_request.xml` | — |
| J — Becario | `controllers/portal_hr_employee_intern_request_controller.py` | `models/portal_hr_employee_intern_request_model.py` | `views/portal_hr_employee_intern_requests_template.xml`, `views/interface/portal_employee_intern_request.xml` | — |
| K — Apertura/cierre de proyecto | `controllers/portal_project_requests_controller.py`, `controllers/portal_project_end_request_controller.py` | `models/portal_project_requests_model.py`, `models/portal_project_end_request_model.py` | `views/portal_project_requests_template.xml`, `views/portal_project_end_request_template.xml`, `views/interface/portal_project_request.xml` | — |
| L — Nóminas | `controllers/portal_nominas_controller.py` | `hr.employee` (estándar), `ir.attachment` | `views/portal_user_templates/portal_my_nomina.xml` | — |
| M — Rechazo con motivo | `wizards/purchase_request_reject_wizard.py`, `wizards/invoice_request_reject_wizard.py` | `models/portal_hr_expensive_request_model.py`, `models/portal_inovice_requests_model.py` | `wizards/purchase_request_reject_wizard.xml`, `wizards/invoice_request_reject_wizard.xml` | — |
| N — Dashboard por rol | — | `models/portal_request_dashboard.py` | `data/dashboard.xml`, `security/dashboard_permision.xml` | — |
| O — Firma digital (Sign) | — | `models/document_approval.py`, `models/sign_request_inherit.py`, `models/sign_send_request_inherit.py` | `views/interface/aicia_approval_documents.xml` | `tests/test_signed_suffix.py` |

**Ficheros transversales** (aplican a varios bloques):
- `models/portal_request_notify_mixin.py` — notificación de cambio de estado (Bloque D, usado por C/E/F/I/J/K).
- `controllers/portal_pdf_utils.py` — validación PDF (`is_pdf`/`ensure_pdf`), usado en B/I/J/K/F.
- `models/work_group.py`, `security/ir.model.access.csv`, `data/res_group_data.xml` — grupos y visibilidad por equipo (Bloque A, base de casi todos los bloques).
- `__manifest__.py` — lista completa de vistas y datos cargados por el módulo.
