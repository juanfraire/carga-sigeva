# SIGEVA por dentro

Referencia de campos, URL e identificadores del Banco de Datos, relevados sobre
**SIGEVA CONICET 14.11.20** entre el 27 y el 28 de julio de 2026.

Todo esto se descubrió leyendo el DOM. No hay documentación oficial de la
interfaz; los manuales del CONICET explican cómo usar la aplicación, no cómo
está construida. Si SIGEVA cambia de versión, esto puede quedar viejo.

## Entrar

| Paso | Cómo |
|---|---|
| Login | `/cas/login` — `input#username`, `input#password`, `button[name=submitBtn]` |
| Portada | `/intranet/index.htm` |
| Elegir rol | los enlaces llaman `redirect(<idRol>)`, que completa `#rolId` y envía `#rolForm` |
| Banco de Datos | `redirect(96)` → `/eva/indexBancoDatos.do` |
| Presentación/solicitud | `redirect(72)` |

Los enlaces de rol están en un menú colapsado: existen en el DOM pero no son
visibles, así que hay que esperarlos con `state="attached"`, no `visible`.

## Pantallas del Banco de Datos

| Rubro | URL (relativa a `/eva/`) |
|---|---|
| Menú principal con los conteos | `indexBancoDatos.do?idModulo=1&idGrupo=0&idMenu=0` |
| Publicaciones | `bcoProduccionListaPublicacion.do?idModulo=6&idGrupo=6&idMenu=1466&prod=cientifica` |
| Desarrollos tecnológicos | `bcoProduccionListaDesarrollo.do?idModulo=6&idGrupo=6&idMenu=1467&prod=tecnologica` |
| Servicios | `bcoProduccionListaServicios.do?idModulo=6&idGrupo=6&idMenu=1481&prod=tecnologica` |
| Financiamiento | `bcoFinanciamientoCyTLista.do?idModulo=5&idGrupo=5&idMenu=1459` |
| Evaluación | `bcoActividadEvaluacionLista.do?idModulo=5&idGrupo=5&idMenu=1462` |
| Extensión / comunicación pública | `bcoExtensionLista.do?idModulo=5&idGrupo=5&idMenu=1463` |
| Formación de RRHH | `bcoFormacionRRHH.do?idModulo=5&idGrupo=5&idMenu=1460` |
| Cargos docentes | `bcoCargoDocenteLista.do?idModulo=4&idGrupo=4&idMenu=1455` |
| Cargos en gestión | `bcoCargoGestionLista.do?idModulo=4&idGrupo=4&idMenu=1457` |
| Redes y eventos | `bcoRedesLista.do?idModulo=7&idGrupo=7&idMenu=1469` |
| Premios | `bcoPremioLista.do?idModulo=7&idGrupo=7&idMenu=1470` |
| Imprimir CV | `filtroImprimirCurriculum.do` |

El menú principal trae el conteo de cada rubro. Sirve de control: si el
inventario que armás no coincide con esos números, algo se te escapó.

### Altas

| Tipo | URL |
|---|---|
| Artículo (con precarga por DOI) | `bcoPrecargarArticulo.do?action=Nuevo` |
| Trabajo en evento | `bcoProduccionListaPublicacionCongreso.do?action=Nuevo&publicado=1` |
| Libro | `bcoProduccionLibroPublicacion.do?action=Nuevo` |
| Parte de libro | `bcoProduccionListaPublicacionCapituloLibro.do?action=Nuevo` |
| Tesis | `bcoProduccionListaPublicacionTesis.do?action=Nuevo` |
| Informe técnico | `bcoProduccionInformeTecnico.do?action=Nuevo` |

En artículos, el botón **Omitir** de la precarga lleva al formulario completo con
todos los campos editables. Es el camino confiable.

## Campos del formulario de artículo

Formulario `cProduccionArticuloActionForm`.

| Campo | Nombre |
|---|---|
| ISSN a buscar / nombre de revista | `bissn` / `brevista` |
| Revista elegida (display) | `srevista` (textarea) |
| **ID de la revista** | `publicacionId` |
| Editorial | `editorial` |
| País de edición / ciudad | `pais` / `lugarEdicion` |
| Título | `produccion` |
| Idioma | `idioma` |
| Volumen, tomo, número | `volumen`, `tomo`, `numero` |
| Páginas | `paginaInicial`, `paginaFinal` |
| Fecha (mm/aaaa) | `fechaPublica` |
| URL, DOI | `web`, `doi` |
| Referato | `tipoReferato` (2 = con referato) |
| Estado | `publicado` (1 = publicado) |
| Soporte | `tipoSoporteChecked` (1 impreso, 2 electrónico) |
| Autor declarante | `autorSel` (radio, índice de fila) |
| Nombre de cada autor | `autorParticipacionLabel` |
| Resumen | `hdnresumen` (textarea) |
| Área del conocimiento | `campo_0` → `campo_0_0` (dependiente) |
| Palabras clave | `palabraLabel` (varias) |
| Full text | `theFile` + `tipoAdjunto` |
| OPT-OUT | `tipoAdjuntoMotivoExclusion` |
| Token CSRF | `org.apache.struts.taglib.html.TOKEN` |

`campo_0_0` se llena por JavaScript al cambiar `campo_0`; hay que esperar a que
aparezca la opción antes de seleccionarla.

## Campos del formulario de evento

Formulario `cProduccionCongresoActionForm`. Comparte `idioma`, `hdnresumen`,
`campo_0`, `palabraLabel`, `theFile` y los autores. Propios:

| Campo | Nombre |
|---|---|
| Tipo de trabajo | `tipoTrabajo` (1 = artículo completo) |
| Título | `produccion` |
| Tipo de publicación | `tipoPublicacion` (5 libro, 6 revista) |
| Título del libro/revista | `tituloPublicacion` |
| ISSN/ISBN | `issnIsbn` (valida el formato) |
| País/ciudad de edición | `paisEdicion`, `lugarPublicacion` |
| Editorial, año | `editorial`, `anioPublica` |
| Nombre del evento | `reunionCientifica` |
| Tipo de evento | `tipoReunion` (1 conferencia, 3 simposio, 4 workshop) |
| Alcance | `alcanceNacional`, `alcanceInternacional` |
| País/ciudad del evento | `paisEvento`, `lugarReunion` |
| Fecha del evento (mm/aaaa) | `fechaReunion` |
| Institución organizadora | `institucionOrganizadora` |

## Filiaciones

Los inputs ocultos que el backend lee al guardar, uno por filiación:

```html
<input type="hidden" name="autorOrganizacionLabel" value="...">
<input type="hidden" name="autorOrganizacionId"    value="...">
<input type="hidden" name="autorParticipacionOrganizacionId" value="">
<input type="hidden" name="autorParticipacionId"   value="">
<input type="hidden" name="autorisOtraOrganizacion" value="false">
<input type="hidden" name="autorPaisId"      value="">
<input type="hidden" name="autorProvinciaId" value="">
<input type="hidden" name="autorRelacionadaId" value="">
<input type="hidden" name="autorNivel"       value="">
<input type="hidden" name="autorRuta"        value="...">
<input type="hidden" name="autorTipoId"      value="">
<input type="hidden" name="autorAffiliationId" value="">
```

Dónde insertarlos:

- **Artículos**: al final del `<tbody>` de la tabla del autor.
- **Eventos**: inmediatamente después del `<tr>` del autor (el `<tbody>` está
  vacío porque el autor vive en un `<th>`).

Sólo sirve con `autorOrganizacionId` real. Ver el límite en el README.

## Buscador de instituciones

Se llega con el botón `btnSubmitBuscar` de la fila del autor, que corre
`autor.participacionSubmitBuscar(this)`. **Antes hay que escribir al menos tres
caracteres** en `autorOrganizacionBuscar` de esa fila.

La pantalla tiene dos bloques que se validan por separado:

1. **Filtro de búsqueda**: `filtroPais`, `filtroProvincia`, `tipoOrganizacion`,
   `filtroOrganizacion` + botón `Buscar`. Los resultados son
   `<span class="orgBuscar" onclick="navegar('<id>')">`; hay que hacer click en
   el que corresponde y después presionar `Seleccionar`, que **aparece recién
   tras el re-render**.
2. **Alta de una nueva** ("Solo en caso de no encontrar la institución"):
   `pais`, `provincia`, `tipoOtraOrganizacion`, `otraOrganizacion` + botón
   `Ingresar otra`. Hay que llenarlo **antes** de presionar el botón; el botón no
   despliega nada.

El país del bloque de alta arranca en Argentina, y con Argentina la provincia
pasa a ser obligatoria.

Cuando hay varios `select` con el mismo `name` en la pantalla, seleccionar por
nombre falla por ambigüedad en modo estricto de Playwright: usar el primero.

**Cuidado con los resultados**: filtrar por país devuelve *todas* las
instituciones de ese país. Quedarse con el primer resultado adjudica una
filiación falsa. Verificá que el texto coincida de verdad, ignorando palabras
genéricas (SIGEVA castellaniza: *Universitat Politècnica* aparece como
*UNIVERSIDAD POLITECNICA*).

Tipos de institución (`tipoOrganizacion`): 73 organismo de CyT, 74 entidad
administrativa de gobierno, 75 universidad estatal, 76 universidad privada,
77 otra institución educativa, 78 empresa, 79 entidad sin fines de lucro,
80 establecimiento de salud, 81 entidad internacional.

En el alta manual (`tipoOtraOrganizacion`) **no están las opciones de
universidad**: para una universidad extranjera la menos incorrecta es
*Entidad internacional*.

El catálogo es casi exclusivamente argentino, aunque tiene entradas extranjeras
cargadas por otros usuarios.

## Pantalla de solicitud

Fuera del Banco de Datos, en el rol *Usuario presentación/solicitud*
(`redirect(72)`), una convocatoria pide:

- **Grupo de Actividades CyT**, con documentación de acreditación adjunta.
- **Aspectos éticos**: declaración jurada por sí/no.
- **Participación en PDTS**.
- **Fundamentos, solicitud e historial**: cinco `textarea` de hasta 10.000
  caracteres.
- **Producciones más relevantes**: seleccionar hasta cinco ítems del Banco de
  Datos más un texto de justificación de hasta 2.500 caracteres.
- **Archivos adjuntos**: CV y avales en PDF.

Los `textarea` no interpretan Markdown: lo que pegues aparece literal, asteriscos
incluidos. Y el Instructivo advierte que pegar abstracts desde PDF o Word mete
caracteres rotos, así que conviene normalizar el texto antes.

Las producciones que la solicitud muestra salen del Banco de Datos, así que hay
que terminar de cargarlo **antes** de armar la presentación.