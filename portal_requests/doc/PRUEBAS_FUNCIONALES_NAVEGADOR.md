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
| `EMAIL_BANDEJA` | Cómo revisar correos (buzón real o Odoo → Ajustes → Técnico → Correos electrónicos) | |

**Archivos de prueba que necesitarás preparar en el equipo:**
- `documento_valido.pdf` — un PDF real y válido.
- `documento_falso.txt` — un archivo de texto renombrado o no PDF.
- `falso.pdf` — un archivo con extensión `.pdf` pero contenido que **no** es PDF
  (por ejemplo, un `.txt` renombrado a `.pdf`).

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

### G1. Notificación al Responsable de Proveedores
**Precondiciones:** sesión como `USER_SOLICITANTE`.
**Pasos:**
1. Navega a `URL_BASE/portal/purchase_order_request` (o crea una solicitud de
   pago desde `URL_BASE/my/payments`).
2. Completa los datos, adjunta `documento_valido.pdf` y **Envía**.
3. Revisa `EMAIL_BANDEJA` del **Responsable de Proveedores** (`personal@aicia.es`).
**Resultado esperado:** el Responsable de Proveedores recibe la notificación de
pago. El adjunto que llega es correcto y legible (no un archivo "RAW" sin
sentido).

### G2. Visualización/descarga de adjuntos en solicitudes pendientes
**Precondiciones:** una solicitud (proyecto o pago) con adjuntos, en estado
pendiente.
**Pasos:**
1. Como el usuario correspondiente, abre la solicitud en el portal.
2. Intenta **previsualizar** y **descargar** el adjunto.
**Resultado esperado:** el adjunto se **visualiza y descarga** correctamente
(prueba de regresión del error de renombrado/procesado de archivos).

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
| H1 | | | |

> **Al terminar:** entrega un resumen con el número de pruebas PASA/FALLA/
> BLOQUEADA y, para cada FALLA, los pasos exactos para reproducirla.
