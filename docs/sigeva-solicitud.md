# SIGEVA: las pantallas de solicitud

Complemento de [`sigeva-interno.md`](sigeva-interno.md), que documenta el **Banco de
Datos**. Esto cubre el rol *Usuario presentación/solicitud* (`redirect(72)`): las
pantallas de **Trayectoria** y **Solicitud** que se completan al postular a una
convocatoria.

Relevado sobre **SIGEVA CONICET 14.11.20** en julio de 2026, durante una presentación a
Promoción CIC. Todo salió de leer el DOM y de chocarse con las validaciones; no hay
documentación oficial de la interfaz.

> Las pantallas de Trayectoria escriben en el mismo Banco de Datos que el otro rol. La
> diferencia es que acá los formularios traen validaciones extra y filtran por período.

---

## El período computable manda

Cada pantalla avisa:

> El sistema seleccionará automáticamente los registros computables del período
> 2017 - 2026 con el siguiente símbolo.

Un rubro puede figurar **"Con Datos"** y valer cero, si todos sus registros quedan fuera
de la ventana. Antes de decidir dónde poner esfuerzo, mirá los años, no la cantidad.

En una presentación real nos encontramos con esto:

| Rubro | Registros | Dentro del período |
|---|---|---|
| Desarrollos tecnológicos | 2 | 0 |
| Servicios | 1 | 0 |
| Comunicación pública | 7 | 0 |
| Evaluación | 6 | 0 |

Cuatro rubros que parecían cargados valían cero. Un `diff` que sólo compare títulos no
lo detecta: hay que comparar contra el rango de la convocatoria.

Efecto lateral útil: cuando la relación es continua (revisor de una revista, membresía),
**extender el año de fin** de un registro viejo es mucho más barato que crear uno nuevo,
y suele ser más fiel a la realidad.

---

## URL de las pantallas

Relativas a `/eva/`. Los `idMenu` cambian por convocatoria; los de abajo son de
Promoción CIC 2026 y sirven de referencia para encontrar los propios.

| Pantalla | URL |
|---|---|
| Índice de la solicitud | `index.do?idModulo=1&idGrupo=0&idMenu=0` |
| Datos académicos | `datoAcademico.do` |
| Director / codirector | `grupoInvestigacion.do` |
| Lugar de trabajo | `datoPersonalDireccion.do?tipoDir=laboral` |
| Recusación | `recusacion.do?action=inicio` |
| **Grupo de Actividades CyT** | `grupoActividadesCYT.do` |
| Aspectos éticos | `aspectoEtico.do` |
| Cargos | `cargosLista.do` |
| Formación RRHH | `formacionRRHH.do` |
| Producciones y servicios | `produccionLista.do` |
| Financiamiento | `financiamientoCyTLista.do` |
| Evaluación | `actividadEvaluacionLista.do` |
| Participación en PDTS | `actividadTecnologica.do` |
| Redes, gestión editorial y eventos | `redesLista.do` |
| Premios | `premioLista.do` |
| Fundamentos, solicitud e historial | `fundamentoAntecedenteProyeccion.do` |
| Producción y servicio más relevante | `produccionMasRelevante.do` |
| Vista preliminar en PDF | `archivoDinamico.do?tipoPdf=3` |

### Altas

| Qué | URL |
|---|---|
| Desarrollo tecnológico | `produccionDesarrollo.do?action=Nuevo&tipo=12` |
| Servicio | `produccionConvenio.do?action=Nuevo` |
| Comunicación pública | `extensionDivulgacionCyT.do?accion=Nuevo&tipoExtension=1` |
| Proyecto de I+D | `financiamientoCYTProyecto.do?tipoFinanciamientoId=5&accion=nuevo` |
| Cargo docente | `cargoNivelSuperior.do?accion=Nuevo` |
| Cargo I+D | `cargoIDOrganizacionCT.do?action=Nuevo` |
| Cargo en gestión institucional | `cargoGestion.do?accion=Nuevo` |
| Otro cargo | `cargoOtro.do?accion=Nuevo` |
| Becario | `formacionBecario.do?accion=nuevo&tipo=2` |
| Tesista | `formacionTesis.do?accion=nuevo&tipo=1` |
| Investigador formado | `formacionInvestigador.do?accion=nuevo&tipo=3` |
| Evaluación de personal / jurado | `actividadEvaluacionPersonalCyT.do?accion=Nuevo` |
| Evaluación de proyectos | `actividadEvaluacionProyecto.do?accion=Nuevo` |
| Evaluación de revistas | `actividadEvaluacionRevista.do?tipoActividadEvaluacionId=3&accion=Nuevo` |
| Otro tipo de evaluación | `actividadEvaluacionOtroTipo.do?accion=Nuevo` |
| Participación en evento | `participacionEvento.do?accion=nuevo` |
| Red temática | `cActividadRedes.do?accion=nuevo&tipoActividad=8` |
| Trabajo en evento no publicado | `produccionCongresoRedesLista.do?action=Nuevo&publicado=0` |
| Premio | `premio.do?accion=nuevo` |

---

## Tres trampas que cuestan horas

### 1. Los checkboxes se serializan por `value`, no por `checked`

`preSubmit()` arma un JSON leyendo `elemento.value`, que arranca en `"false"`. Marcar
sólo la propiedad `checked` desde JavaScript no alcanza:

```js
el.checked = true;
el.value = 'true';   // esto es lo que el backend lee
```

Sin esto, aparece el error **"la suma de los porcentajes debe ser igual a 100%"** aunque
el porcentaje diga 100: el servidor descarta la fila porque ninguna entidad quedó
marcada como ejecutora.

### 2. Las instituciones casi nunca se pueden inyectar

En el Banco de Datos, escribir los `input[type=hidden]` de la filiación funciona (ver
`sigeva-interno.md`). En las pantallas de solicitud, en general **no**: el servidor sólo
reconoce la entidad si pasó por `buscarOrganizacion.do`. Hay que hacer el ida y vuelta
real.

La excepción son las pantallas de **Formación de RRHH** (`formacionTesis.do`,
`formacionBecario.do`), donde alcanza con escribir el par de campos y guardar:

```js
f.elements['organizacionTrabajoId'].value = '21005';
f.elements['organizacionTrabajoLabel'].value = 'Universität des Saarlandes';
```

Con eso se carga un tesista en un solo `evaluate`, sin abrir el buscador. Los códigos son
los mismos que devuelve `buscarOrganizacion.do`, así que conviene anotarlos la primera vez
que los buscás a mano: son jerárquicos (`01560-01581` para la FCEFyN de la UNC) o planos
(`21005` Saarland, `23752` Politecnico di Torino, `25576` Inria, `20402` Universidad de
Chile, `12897` CONAE).

Y ojo con el catálogo: **no todas las instituciones existen**. INSA Lyon, por ejemplo, no
figura entre las francesas, así que hay que elegir la más cercana que sí esté o pedir el
alta por mail a `lugardetrabajo@conicet.gov.ar`.

Y ese ida y vuelta **borra los checkboxes y los porcentajes** del formulario. El orden
que funciona es:

1. llenar todos los campos
2. adjuntar el PDF
3. buscar y seleccionar la institución
4. **recién ahí** marcar checkboxes y porcentaje
5. guardar

### 3. "Ingresar otra" cuelga la entidad de lo último navegado

Si antes navegaste una jerarquía en el buscador y después usás **Ingresar otra**, la
entidad nueva queda anidada bajo esa jerarquía:

```
UNIVERSIDAD X / FACULTAD Y / INSTITUTE OF ELECTRICAL AND ELECTRONICS ENGINEERS (IEEE)
```

Hay que apretar **Limpiar** (`filtroOrganizacionReset`) antes de dar de alta una nueva.

---

## Otras rarezas transversales

**Los widgets de fecha pisan lo que escribís.** Los campos con datepicker
(`anioReferencia`, `anioInicio`, `fechaInicio`) se resetean al año actual cuando el
formulario vuelve del servidor con un error de validación. Hay que reescribirlos en cada
reintento y verificarlos después de guardar.

**Los errores vienen en cascada y mienten.** Cuando falta un campo obligatorio, SIGEVA
lista además errores de otros bloques que están bien. Corregí el primero y reintentá
antes de tocar el resto.

**`LockAcquisitionException` de Hibernate.** Aparece cada tanto al guardar, sobre todo en
premios y en participación en eventos:

```
java.lang.Exception: javax.persistence.PersistenceException:
org.hibernate.exception.LockAcquisitionException: could not execute statement
```

Es transitorio. **Siempre verificá la lista después de guardar**: a veces el registro
entró igual y reintentar lo duplica; a veces no entró y parece que sí.

**Dos uploaders distintos.** Publicaciones usa un `input[name="theFile"]` común.
Desarrollos y financiamiento usan **Fine Uploader**: el input se llama `qqfile`, está
tapado por otros elementos y no admite click directo. Se dispara por JavaScript y se
atiende el file chooser:

```js
document.querySelector('input[name="qqfile"]').click();
```

**`campo_0_0` necesita un round trip.** Se llena por JavaScript al cambiar `campo_0`,
pero no de forma sincrónica: hay que soltar el hilo antes de poder asignarle valor.

**Los `select` que dependen de otro tampoco se dejan asignar en el mismo tick.**
`tipoOtraOrganizacion` se repuebla cuando cambia `pais`; asignarlo con `.value` en la
misma función deja el campo vacío. Hay que usar la API del driver, que espera.

**Un `.click()` en Guardar no garantiza que se haya enviado.** Si leés el `value` del
textarea inmediatamente después del click, ves tu texto, porque la navegación todavía no
ocurrió; si el submit se perdió, el dato nunca llegó al servidor y no te enterás. La única
verificación válida es **recargar la pantalla y volver a leer el campo**. Me pasó de dar
por guardado un cambio que no había entrado, y sólo apareció al comparar el PDF.

**Editar los autores de un artículo ya cargado crea una copia, no modifica el original.**
La tabla de autores (`autorTable`) se deja editar sin problemas: el botón `autorNuevo`
agrega filas, el nombre es texto libre y la institución se elige del autocompletado sin
recargar la página:

```js
const ac = $(inp).data('ui-autocomplete');
inp.value = 'POLITECNICO'; ac.search('POLITECNICO');
// esperar la respuesta, buscar el item por it.value y después:
ac.options.select.call(inp, $.Event('autocompleteselect'), {item: target});
```

El orden se arregla con las flechitas `img[name="arrowDown"]`, y `preSubmit()` arma bien el
`autorJSON` con los siete participantes y sus filiaciones. El POST sale completo. Y aun así
**el registro original queda igual y aparece un registro nuevo con los autores puestos**.
Pasa en el rol de presentación y en el de banco de datos por igual.

O sea que cada intento suma un duplicado. Si probaste seis veces, tenés seis copias del
mismo paper inflando el conteo de publicaciones. Se borran desde `action=Borrar`, que lleva
a una pantalla de confirmación con botón **Eliminar** (el GET solo no borra nada), pero un
registro tildado como producción relevante se niega: *"No se puede eliminar esta producción
porque ha sido marcada como producción más relevante"*, y esa marca puede quedar pegada aun
después de destildarlo.

Conclusión práctica: **verificá el conteo de la pantalla antes y después de tocar autores**,
y si tenés que corregir una autoría, hacelo de una sola vez.

**Los caracteres fuera de Latin-1 se guardan como entidad HTML y el PDF los imprime
crudos.** Una `ş` escrita en el campo de fundamentos vuelve del servidor como `&#351;` y
sale literalmente así en la vista preliminar. Antes de dar por cerrado un texto largo:

```js
document.forms[0].elements['fundamento'].value.match(/&#?\w+;/g)
```

Lo mismo pasa con `accion=listar` en algunas pantallas: `formacionTesis.do?accion=listar`
renderiza el formulario **sin botón Guardar**. El alta real es `accion=nuevo`.

---

## Bajar la vista preliminar en PDF

El link "Presentación electrónica" del índice apunta a `archivoDinamico.do?tipoPdf=3`, que
no devuelve el PDF: arma una página con un `<iframe src="byteDownload.do">`. El binario
sale de ese segundo pedido, y **depende del estado de sesión que dejó el primero**, así que
hay que pedirlos en ese orden.

`curl` con la cookie `JSESSIONID` no sirve: el WAF devuelve 403 a cualquier cosa que no
parezca el navegador. Lo que funciona es forzar la descarga desde la propia página y
guardarla con la API del driver:

```js
await page.goto('https://si.conicet.gov.ar/eva/archivoDinamico.do?tipoPdf=3');
const [download] = await Promise.all([
  page.waitForEvent('download'),
  page.evaluate(async () => {
    const r = await fetch('/eva/byteDownload.do', {credentials: 'include'});
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement('a');
    a.href = url; a.download = 'vista-previa.pdf';
    document.body.appendChild(a); a.click();
  })
]);
await download.saveAs('/ruta/vista-previa.pdf');
```

Vale la pena generarlo **antes** de dar por terminada la carga y leerlo con
`pdftotext -layout`. La tabla "Cantidad Registros" de las primeras páginas es la forma más
rápida de confirmar que todo lo que cargaste quedó contado, y el texto completo revela
cosas que la interfaz esconde: entidades HTML, numeraciones rotas, campos vacíos que el
template imprime como `null`, y listas de autores truncadas en los registros importados.

---

## Requisitos por formulario

Lo que cada pantalla exige y no es obvio hasta que falla.

### Desarrollos tecnológicos (`produccionDesarrollo.do`)

- **PDF de documentación del desarrollo.** Obligatorio, sin excepción.
- Palabras clave (hasta 4).
- Seleccionarte en la lista de autores con el radio `autorSel`.
- **Una institución por cada autor**, coautores extranjeros incluidos.
- Si marcás "Transferencia: Sí", exige además un registro de vinculación que **no se
  puede cargar en el alta**: sólo aparece al editar. Conviene guardar con "No" y
  cambiarlo después.

### Financiamiento (`financiamientoCYTProyecto.do`)

- **PDF de acreditación por proyecto.** Obligatorio.
- **Director con apellido, nombre y CUIL, los tres.** No hay forma de guardar sin CUIL,
  lo que es un problema real para proyectos con director extranjero.
- La entidad financiadora necesita el circuito completo del buscador.

### Servicios (`produccionConvenio.do`)

- Al menos una **institución que ejecuta** (checkbox `convenioOrganizacionEjecuta`).
- Al menos un **destinatario** completo. Al elegir "Persona jurídica" aparece un segundo
  buscador de organización, distinto del de la institución ejecutora.
- Las filas vacías de organización rompen el guardado: hay que borrarlas.

### Evaluación (`actividadEvaluacion*.do`)

- El **Rol evaluador** sólo aplica cuando la institución convocante es CONICET. Si es
  otra y dejás el rol cargado, falla con un mensaje que habla de CONICET y no dice qué
  hacer. Va en "Seleccionar".

### Cargos en gestión institucional (`cargoGestion.do`)

- El campo de texto libre **"Cargo" es sólo para cuando elegís "Otro"** en el
  desplegable. Si completás los dos, el formulario recarga vacío sin decir nada.

### Grupo de Actividades CyT (`grupoActividadesCYT.do`)

- La **descripción tiene un máximo de 2.000 caracteres** que el formulario **no
  declara y no valida con un mensaje**: si te pasás, guarda en silencio, recarga el
  formulario vacío y la pantalla sigue en "Sin Datos". Es el fallo más desconcertante
  de toda la aplicación.
- Los campos de miembro (apellido, nombre, CUIL) son **autocompletados jQuery UI** que
  llenan un `personaId_<n>` oculto. Escribir el CUIL a mano no sirve: el backend
  responde "Debe seleccionar la persona con dicho cuil". Hay que **buscar por apellido**
  y elegir de la lista.
- **Cuidado al elegir del autocomplete**: los homónimos son frecuentes y un click por
  texto puede caer en el equivocado. Conviene leer el item de cada `li` y disparar el
  handler con el que corresponde:

```js
const $ = window.jQuery;
const ac = $(input).data('ui-autocomplete');
let target = null;
ac.menu.element.find('li').each(function () {
  const it = $(this).data('ui-autocomplete-item');
  if (it && it.cuil === '20309689926') target = it;
});
ac.options.select.call(input, $.Event('autocompleteselect'), { item: target });
```

### Producciones más relevantes (`produccionMasRelevante.do`)

- La lista sale del Banco de Datos y viene **paginada de a 10** con displaytag
  (`d-<id>-p=N`), sin buscador. Con 186 registros son 19 páginas. Se pueden recorrer
  con `fetch` desde la propia página y parsear con `DOMParser`, en lugar de navegar.
- **Parseá sólo las filas que tienen `input[name="producciones"]`.** Si mirás el
  `textContent` de todos los `<tr>`, las filas del layout externo contienen la página
  entera y cualquier búsqueda por texto devuelve coincidencias falsas.
- Cada checkbox tiene `onclick="actualizar(<pagina>, null, null)"`, que **envía el
  formulario y persiste la selección en el servidor**. Por eso se puede tildar un ítem,
  pasar a otra página y tildar otro: la selección se acumula. Pero **no combines**
  `checked = true` con `click()`: el click togglea y termina desmarcando.
- Para cambiar de página conservando lo tildado, llamá `actualizar(N, null, null)`.
- **El botón Guardar de esa pantalla borra todas las selecciones.** Sólo envía los
  checkboxes de la página visible, así que si apretás Guardar parado en una página sin
  ítems tildados, contesta *"La cantidad de producciones seleccionadas no puede ser menor
  a 1"* y de paso **te vacía las cinco selecciones**, que estaban bien guardadas. Cuesta
  quince minutos rehacerlas y es fácil no darse cuenta.
  El campo de Observaciones vive en esa misma pantalla, así que **editá el texto antes de
  tildar las producciones**, nunca después. O editalo y verificá las cinco selecciones
  recorriendo todas las páginas.
- **Borrar una producción tildada también vacía las selecciones.** Y al revés: no se puede
  borrar una producción que esté marcada como relevante (*"Desmárquela como tal y vuelva a
  intentar"*), marca que a veces queda pegada aunque el checkbox aparezca sin tildar.
  Después de cualquier borrado, revisá las cinco.
- El orden de las páginas **cambia** cuando tildás, borrás o se recarga la lista. No sirve
  memorizar en qué página estaba cada ítem: buscá por el `value` del checkbox
  (`<tipo>-<produccionId>`) recorriendo todas las páginas.

### Participación en eventos (`participacionEvento.do`)

- Al menos una **institución organizadora**.
- Modos de participación (`modoParticipacionChecked`): 1 asistente, 2 presentador de
  póster, 3 panelista, 4 conferencista, 5 organizador general, 6 miembro del comité
  organizador, 7 miembro del comité científico-tecnológico, 8 coordinador/moderador,
  9 relator, 10 otro.

### Trabajos en eventos no publicados (`produccionCongresoRedesLista.do?publicado=0`)

- `fechaReunion` exige **mm/aaaa** estricto. Sólo el año no pasa.
- No pide PDF, a diferencia de las publicaciones.

---

## Dos pantallas con trampa propia

**Grupo de Actividades CyT.** Conseguir los CUIL de todos los integrantes de un
laboratorio es poco realista. La pantalla no exige el listado completo: se puede
declarar sólo a quienes tengas.

**Producciones más relevantes.** Sale del Banco de Datos: hay que terminar de cargarlo
antes. Los `textarea` no interpretan Markdown: lo que pegues aparece literal, asteriscos
incluidos.
