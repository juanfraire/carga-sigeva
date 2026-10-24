# carga-sigeva

Herramienta para poblar el **Banco de Datos de Actividades de CyT de SIGEVA**
desde un archivo BibTeX, sin cargar cada publicación a mano.

Cargar cien publicaciones en SIGEVA son varias tardes de formularios. Esto lo
reduce a correr cuatro comandos y revisar el resultado. Cada registro queda con
su revista o evento, autores con filiación, resumen, área del conocimiento,
palabras clave y PDF adjunto.

> **Probado únicamente en SIGEVA CONICET** (`si.conicet.gov.ar`), versión
> 14.11.20. SIGEVA lo usan también universidades y CVar con la misma base de
> código, así que es razonable que funcione en otras instancias, pero **nadie lo
> verificó todavía**. Si lo probás en otra, contá cómo te fue en un issue.

## Qué hace

```
   cv.bib ──▶ registros.json
                   │
                   ├── diff contra lo que ya está en SIGEVA ──▶ faltantes.json
                   │
                   ├── enriquecido con OpenAlex, Crossref y HAL
                   │   (resumen, ISSN, fecha, filiación de coautores, PDF)
                   │
                   └──▶ Playwright llena y guarda cada formulario
```

Cubre las dos pantallas que concentran el volumen: **artículos en revistas** y
**trabajos en eventos C-T publicados**.

## Instalación

```bash
git clone https://github.com/juanfraire/carga-sigeva
cd carga-sigeva
python3 -m venv .venv && ./.venv/bin/pip install playwright
./.venv/bin/playwright install chromium

cp ejemplos/config.ejemplo.json config.json
$EDITOR config.json
```

`config.json` es lo único que hay que tocar: tu apellido, tu mail de contacto,
la ruta del `.bib`, las carpetas donde tenés los PDF y el área del conocimiento
que querés declarar. El campo va por su `value`; el subcampo puede ir por
`value` o por un trozo de su etiqueta (`"subcampo": "Telecomunicaciones"`),
porque llega por AJAX y su `value` no está en el HTML. `inventariar.py` deja
los valores de los dos combos en `datos/areas.json`.

## Uso

```bash
cd carga_sigeva

# 1. Normalizar la bibliografía
python3 bib2registros.py

# 2. Inventariar lo que YA está cargado (solo lectura) y sacar la diferencia
../.venv/bin/python inventariar.py   # inventario.json, catálogo de IDs y combos
python3 diff.py

# 3. Completar lo que el .bib no trae
python3 emparejar.py           # resumen, ISSN, fecha, filiaciones, PDFs locales
python3 pdfs_hal.py            # busca los full text que falten en HAL y OpenAlex

# 4. Cargar. Primero en seco, siempre.
../.venv/bin/python cargar.py --dry-run --limit 3
../.venv/bin/python cargar.py --con-pdf --perfil-limpio
```

Credenciales: por defecto abre un Chromium visible y espera a que ingreses vos.
Para corridas desatendidas, `SIGEVA_USER` y `SIGEVA_PASS` por variable de
entorno. **Nunca se escriben en disco.**

### Flags de `cargar.py`

| Flag | Qué hace |
|---|---|
| `--dry-run` | Llena el formulario y saca captura, **no guarda** |
| `--limit N` | Procesa N y para |
| `--paso-a-paso` | Pide confirmación antes de cada guardado |
| `--con-pdf` | Sólo los que tienen full text (sin archivo SIGEVA rechaza) |
| `--perfil-limpio` | Contexto de navegador nuevo (ver más abajo, importante) |
| `--desde AAAA`, `--tipo` | Filtros |

## Esto es una declaración jurada

El diseño está sesgado a no meter datos falsos, aun a costa de cargar menos:

- **Nunca inventa.** Si no encuentra la sede de un congreso, el resumen o la
  editorial, corta ese registro y lo reporta en vez de completar con algo
  plausible.
- **Verifica lo que guarda.** Después de cada alta va a buscar el registro a la
  lista. No alcanza con que no haya mensaje de error: SIGEVA puede volver del
  Guardar sin quejarse y sin haber guardado nada.
- **No duplica.** `estado.json` es append-only y se re-verifica contra el
  inventario antes de crear.
- **Filtra la basura de las fuentes.** OpenAlex a veces devuelve como filiación
  cosas que no son instituciones académicas, incluidos clubes deportivos; ante
  una institución dudosa deja el campo sin informar antes que afirmar algo
  falso.
- **Nunca aprieta "Enviar Presentación".** Eso lo hace la persona.

## Lo que aprendimos de SIGEVA

Esta es la parte que probablemente más te sirva, la hayas encontrado buscando la
herramienta o no. Son horas de prueba y error contra una aplicación Struts vieja.

### El servidor se cuelga por estado de sesión, no por saturación

El síntoma es que el alta funciona un rato y después el servlet deja de
responder, mientras las pantallas de lectura siguen bien. La causa no es el
tráfico: es el estado acumulado en la sesión del navegador. Con un contexto
limpio (equivalente a una ventana de incógnito) desaparece. Por eso existe
`--perfil-limpio`, y por eso conviene tandas cortas.

Coincide con lo que reportan los usuarios en la propia [encuesta de satisfacción
del CONICET](https://www.conicet.gov.ar/wp-content/uploads/Informe-SIGEVA-para-WEB.pdf):
*"algunas opciones sólo aparecían entrando desde una ventana de incógnito"*, y
quince menciones a que SIGEVA se comporta distinto según el navegador.

### Los combos necesitan eventos reales

Asignar `select.value` por JavaScript no sirve: Struts no registra el cambio y
las búsquedas vuelven siempre vacías. Hay que usar la API de selección del
navegador (`select_option` en Playwright). Esto nos hizo creer durante horas que
el catálogo de instituciones estaba roto cuando funcionaba perfecto.

### Se pueden inyectar los campos ocultos

Para las filiaciones, SIGEVA hace navegar tres pantallas por autor. Pero al
enviar el formulario sólo mira un puñado de inputs ocultos, así que se los puede
escribir directamente en el DOM:

```html
<input type="hidden" name="autorOrganizacionLabel" value="NOMBRE DE LA INSTITUCIÓN">
<input type="hidden" name="autorOrganizacionId"    value="ID EN EL CATÁLOGO">
<input type="hidden" name="autorisOtraOrganizacion" value="false">
```

Un artículo de catorce autores pasa de unas 25 recargas de página a **una**. La
idea viene de [SIGEVA-JSON](https://github.com/indirivacua/SIGEVA-JSON), una
extensión de navegador que exporta e importa producciones en JSON y que vale la
pena mirar si tu caso de uso es otro.

**El límite:** sólo funciona con instituciones que ya tienen ID en el catálogo.
Inyectar `autorisOtraOrganizacion=true` con ID vacío hace que el backend
explote con `TransientPropertyValueException`, porque intenta persistir la
filiación contra una organización que no existe. Y una institución nueva se
persiste **sólo cuando se guarda un registro que la usa**, lo que crea un
círculo: para guardar necesitás la institución, para crear la institución
necesitás guardar. La salida es cargar ese registro a mano una vez; después
`cosechar.py` levanta el ID y el resto sale automático.

### Los formularios anidan distinto

En artículos las filiaciones van dentro del `<tbody>` de la fila del autor. En
eventos el autor vive en un `<th>` con el `<tbody>` vacío y hay que insertarlas
inmediatamente después de su fila. Mismo campo, misma app, distinto HTML.

### Validaciones que no son obvias

- La **institución es obligatoria para cada autor** en artículos. En eventos no.
- Si marcás soporte "Electrónico y/o Digital" **tenés que dar URL o DOI**.
- El **full text es obligatorio**. Sin archivo adjunto no guarda.
- Si el registro no pasa una validación, **el input de archivo se vacía** y hay
  que volver a adjuntarlo antes de reintentar.
- La fecha del evento va en **mm/aaaa**; la de publicación también.
- El buscador de instituciones exige **al menos tres caracteres**, y además país
  y tipo; si el país es Argentina, también provincia.
- La revista se puede dar de alta como "otra" **sólo si tenés el ISSN**.
- Los mensajes de error usan verbos distintos ("debe ingresar", "debe
  seleccionar", "debe adjuntar", "debe especificar"): filtrar por uno solo hace
  que un fallo se lea como éxito.

### Detalles técnicos

- El HTML se sirve en **ISO-8859-1**. Decodificarlo como UTF-8 produce
  `Cap�tulo`.
- Paginación estilo displaytag: `d-<idTabla>-p=N` en la query string.
- Los títulos en las listas vienen **truncados** con `...`, así que el diff
  compara por prefijo normalizado más año, con un pase difuso de respaldo.
- Los campos de autores se arman por JavaScript: `fetch` + parseo del HTML crudo
  no los ve, hay que abrir la página de verdad.
- La **precarga por DOI** (Crossref/Elsevier) existe y ahorra trabajo, pero es
  intermitente y deja vacíos campos obligatorios. Por eso el camino por defecto
  la evita.

## Lo que no cubre

- **Sólo publicaciones.** El Banco de Datos tiene además financiamiento,
  evaluación, cargos, formación de RRHH, desarrollos tecnológicos, servicios y
  extensión. Son pocos registros cada uno y con campos propios, así que conviene
  cargarlos a mano; pero la mecánica de esta herramienta sirve de base.
- **Partes de libros y tesis**, que tienen pantalla propia.
- **La pantalla de solicitud** de una convocatoria (Grupo de Actividades CyT,
  aspectos éticos, producciones más relevantes, los campos de texto libre de
  fundamentos y trayectoria). Eso se completa desde el rol *Usuario
  presentación/solicitud* y es trabajo de redacción, no de carga masiva. Está
  documentado en [`docs/sigeva-solicitud.md`](docs/sigeva-solicitud.md): URL de
  cada pantalla, qué exige cada formulario y las trampas que cuestan horas.
- **Alta de instituciones nuevas**, por lo explicado arriba.

## Antes de empezar: mirá los años, no la cantidad

Cuando la carga es para presentarse a una convocatoria, SIGEVA **sólo computa los
registros que caen dentro del período de la convocatoria** (por ejemplo 2017–2026).
Un rubro puede figurar "Con Datos" y valer cero.

En una presentación real nos pasó con cuatro rubros a la vez: desarrollos
tecnológicos, servicios, comunicación pública y evaluación figuraban cargados y
los registros eran todos anteriores al período. Un `diff` que sólo compara
títulos no lo detecta.

## Si sos una IA leyendo esto

Este repo está pensado también como punto de partida para que otro asistente
retome la interfaz de SIGEVA sin repetir el trabajo de descubrimiento. Lo más
valioso está en la sección anterior y en dos documentos:

- [`docs/sigeva-interno.md`](docs/sigeva-interno.md) — el **Banco de Datos**:
  nombres de campo, ids de rol, URL de cada pantalla, cómo se inyectan las
  filiaciones.
- [`docs/sigeva-solicitud.md`](docs/sigeva-solicitud.md) — las pantallas de
  **solicitud** de una convocatoria: qué exige cada formulario y las tres trampas
  que más tiempo cuestan.

Cuatro consejos de la experiencia:

**Sacá captura de pantalla ante cualquier fallo silencioso.** Los mensajes de
SIGEVA están en la página, no en el HTTP status.

**No confíes en la ausencia de error como señal de éxito**; andá a verificar que
el registro exista. Vale también al revés: SIGEVA tira
`LockAcquisitionException` de Hibernate cada tanto, y a veces el registro entró
igual. Reintentar sin verificar duplica.

**Los checkboxes se serializan por `value`, no por `checked`.** Poner sólo
`el.checked = true` desde JavaScript no alcanza en las pantallas de solicitud;
hay que poner también `el.value = 'true'`.

**Los `select` dependientes no se dejan asignar en el mismo tick.** `campo_0_0`
se puebla cuando cambia `campo_0`, y `tipoOtraOrganizacion` cuando cambia `pais`.
Asignarlos con `.value` en la misma función deja el campo vacío: hay que soltar
el hilo o usar la API del driver, que espera.

## Créditos y estado

Desarrollado **con asistencia de IA** (Claude), a partir de la necesidad de
cargar en SIGEVA una bibliografía extensa sin hacerlo registro por registro.

Se publica por si a alguien más le ahorra el mismo trabajo. No tiene relación
con el CONICET ni con el equipo de SIGEVA. Úsese con criterio: los datos que
cargues son una declaración jurada y la responsabilidad de revisarlos es de
quien firma.

Los aportes son bienvenidos, en especial pruebas en otras instancias de SIGEVA y
soporte para las pantallas que faltan.

## Licencia

MIT.