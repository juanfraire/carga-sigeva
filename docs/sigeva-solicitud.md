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

### 2. Las instituciones no se pueden inyectar

En el Banco de Datos, escribir los `input[type=hidden]` de la filiación funciona (ver
`sigeva-interno.md`). En las pantallas de solicitud, **no**: el servidor sólo reconoce la
entidad si pasó por `buscarOrganizacion.do`. Hay que hacer el ida y vuelta real.

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

## Grupo de Actividades CyT

Pantalla obligatoria y fácil de subestimar. Pide denominación, año de inicio,
institución de radicación, tipo de actividad, descripción, campos de aplicación, área
del conocimiento, **miembros con CUIL y rol**, y los datos de participación del
postulante. Más **documentación de acreditación en PDF**.

Conseguir los CUIL de todos los integrantes de un laboratorio es poco realista. La
pantalla no exige el listado completo: se puede declarar sólo a quienes tengas.

---

## Producciones más relevantes

Sale del Banco de Datos: hay que **terminar de cargarlo antes**. Se tildan hasta cinco
ítems y se justifica en un textarea de 2.500 caracteres.

Los `textarea` no interpretan Markdown: lo que pegues aparece literal, asteriscos
incluidos.
