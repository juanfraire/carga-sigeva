#!/usr/bin/env python3
"""
cargar.py -- carga en el Banco de Datos de SIGEVA los registros faltantes

Abre un Chromium visible. VOS te logueas a mano; el script espera y sigue desde
la sesion ya autenticada. Nunca pide ni guarda la contrasena.

    python3 cargar.py --dry-run --limit 3     # llena, saca captura, NO guarda
    python3 cargar.py --paso-a-paso           # pide confirmacion antes de guardar
    python3 cargar.py --tipo articulo --limit 10
    python3 cargar.py --desde 2024

Nunca aprieta "Enviar Presentacion": esto solo escribe en el Banco de Datos.

Log append-only en estado.json para poder reanudar sin repetir. Antes de crear
cualquier registro se lo busca en la lista viva de SIGEVA: estado.json solo
sabe lo que cargo este script, y un duplicado en una declaracion jurada es peor
que un faltante.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from catalogo import Catalogo
import config as CFG

AQUI = CFG.DATOS_DIR
PERFIL = AQUI / ".perfil-chromium"
CAPTURAS = AQUI / "capturas"
ESTADO = AQUI / "estado.json"

BASE = CFG.BASE
INTRANET = f"{BASE}/intranet/index.htm"
ROL_BANCO_DATOS = CFG.ROL_BANCO_DATOS     # id del rol en redirect(<id>)

# SIGEVA se pone lento con el uso sostenido: conviene espaciar los altas
PAUSA_ENTRE_REGISTROS = 4_000             # ms

# el formulario lo dice ("Tamaño máximo del archivo 35 MegaBytes") pero no
# lo valida con un mensaje: con un PDF mas grande guarda sin error y no queda
MAX_PDF_MB = 35

URL_LISTA = (f"{BASE}/eva/bcoProduccionListaPublicacion.do"
             "?idModulo=6&idGrupo=6&idMenu=1466&prod=cientifica")
URL_NUEVO_ARTICULO = f"{BASE}/eva/bcoPrecargarArticulo.do?action=Nuevo"
URL_NUEVO_EVENTO = (f"{BASE}/eva/bcoProduccionListaPublicacionCongreso.do"
                    "?action=Nuevo&publicado=1")

AREA_CONOCIMIENTO = CFG.AREA_CONOCIMIENTO  # ver config.json
IDIOMAS = {"es": "Español", "en": "Inglés", "fr": "Francés", "pt": "Portugués"}

PAISES = {
    "spain": "España", "usa": "Estados Unidos", "united states": "Estados Unidos",
    "france": "Francia", "germany": "Alemania", "italy": "Italia", "china": "China",
    "argentina": "Argentina", "chile": "Chile", "brazil": "Brasil", "brasil": "Brasil",
    "canada": "Canadá", "uk": "Reino Unido", "united kingdom": "Reino Unido",
    "netherlands": "Países Bajos", "japan": "Japón", "india": "India",
    "australia": "Australia", "greece": "Grecia", "portugal": "Portugal",
    "belgium": "Bélgica", "switzerland": "Suiza", "austria": "Austria",
    "sweden": "Suecia", "norway": "Noruega", "finland": "Finlandia",
    "denmark": "Dinamarca", "poland": "Polonia", "turkey": "Turquía",
    "mexico": "México", "colombia": "Colombia", "peru": "Perú",
    "uruguay": "Uruguay", "ireland": "Irlanda", "czech republic": "República Checa",
    "south korea": "Corea del Sur", "korea": "Corea del Sur", "israel": "Israel",
}

TIPO_REUNION = {"workshop": "Workshop", "symposium": "Simposio",
                "congress": "Congreso", "conference": "Conferencia"}


# ------------------------------------------------------------------ utilidades

def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def registrar(entrada: dict) -> None:
    """estado.json es append-only: permite reanudar sin recargar nada dos veces."""
    historial = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else []
    historial.append({**entrada, "cuando": datetime.now().isoformat(timespec="seconds")})
    # se escribe aparte y se reemplaza: cortar el proceso a mitad de escritura
    # no puede dejar el log truncado
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(historial, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ESTADO)


def ya_cargado(clave: str) -> bool:
    if not ESTADO.exists():
        return False
    return any(e.get("clave") == clave
               and e.get("resultado") in ("guardado", "ya-estaba", "guardado-fecha-mal")
               for e in json.loads(ESTADO.read_text(encoding="utf-8")))


def sinacentos(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# lo que NFKD no descompone y tiene un equivalente obvio en Latin-1: sin esto
# la 'ı' de "Yanıkömeroğlu" o las comillas y rayas de un resumen salian como '?'
EQUIVALENTES = str.maketrans({
    "ı": "i", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "œ": "oe", "Œ": "OE",
    "‘": "'", "’": "'", "‚": ",", "“": '"', "”": '"', "„": '"',
    "‐": "-", "‑": "-", "–": "-", "—": "-", "−": "-",
    "μ": "µ", "•": "·", "≤": "<=", "≥": ">=", "≈": "~", "∼": "~", "→": "->",
})


def a_latin1(s: str) -> str:
    """Lleva a ISO-8859-1 lo que no entra, sin tocar lo que si entra.

    SIGEVA guarda los caracteres fuera de Latin-1 como entidad HTML y el PDF
    del CV los imprime crudos: 'Güneş' saldria como 'G&#252;ne&#351;'. La
    'ü' entra; la 'ş' pasa a 's'.
    """
    out = []
    s = (s or "").translate(EQUIVALENTES)
    for i, c in enumerate(s):
        try:
            c.encode("latin-1")
            out.append(c)
        except UnicodeEncodeError:
            base = unicodedata.normalize("NFKD", c)
            nombre = unicodedata.name(c, "")
            griega = re.match(r"GREEK (SMALL|CAPITAL) LETTER (\w+)$", nombre)
            if griega:          # "βcrit" -> "beta crit", "Δt" -> "Delta t"
                letra = griega.group(2).lower()
                out.append(letra.capitalize() if griega.group(1) == "CAPITAL" else letra)
                if s[i + 1:i + 2].isalnum():
                    out.append(" ")
                continue
            out.append("".join(b for b in base if not unicodedata.combining(b)
                               and b.encode("latin-1", "ignore")) or "?")
    return "".join(out)


def idioma_de(reg: dict) -> str:
    t = reg["titulo"] + " " + reg["venue"]
    if re.search(r"\b(rencontres|francophones|j'ai|le |les |pour )", t, re.I):
        return IDIOMAS["fr"]
    if re.search(r"\b(análisis|estrategias|sistema|redes de|reunión)\b", t, re.I):
        return IDIOMAS["es"]
    return IDIOMAS["en"]


def palabras_clave(reg: dict, n: int = 4) -> list:
    """Las del paper (emparejar.py las saca del PDF) o, si no hay, del titulo.

    El formulario las pide en MAYUSCULA.
    """
    if reg.get("palabras_clave"):
        return [a_latin1(k).upper() for k in reg["palabras_clave"][:n]]
    vacias = {"a", "an", "the", "of", "for", "in", "to", "and", "with", "on", "via",
              "from", "at", "by", "its", "toward", "towards", "using", "based",
              "into", "over", "under", "case", "study", "new", "novel", "approach"}
    vistas, out = set(), []
    for p in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", reg["titulo"]):
        k = p.lower().strip("-")
        if k in vacias or k in vistas:
            continue
        vistas.add(k)
        out.append(p.upper())
        if len(out) == n:
            break
    return out


def sede_evento(reg: dict) -> dict:
    """Saca ciudad, pais y fecha del booktitle de DBLP cuando estan.

    Formato tipico: '..., ANRW 2025, Madrid, Spain, 22 July 2025'
    """
    v = reg["venue"]
    datos = {"ciudad": "", "pais": "", "fecha": ""}
    # lo cargado a mano manda sobre cualquier deduccion
    if reg.get("pais_evento"):
        return {"ciudad": reg.get("ciudad_evento", ""),
                "pais": reg["pais_evento"],
                "fecha": reg.get("fecha_evento", "")}
    for clave, etiqueta in PAISES.items():
        m = re.search(r"([A-ZÁÉÍÓÚ][\w\.\- ]+),\s*(?:[A-Z]{2},\s*)?" + re.escape(clave) + r"\b",
                      v, re.I)
        if m:
            datos["ciudad"] = m.group(1).strip()
            datos["pais"] = etiqueta
            break
    meses = {"january": "01", "february": "02", "march": "03", "april": "04",
             "may": "05", "june": "06", "july": "07", "august": "08",
             "september": "09", "october": "10", "november": "11", "december": "12"}
    MES = "|".join(meses)
    # DBLP escribe tanto "22 July 2025" como "December 16-18, 2024"
    # si el booktitle no trae la sede, se usa la que publica Crossref
    if not datos["pais"] and reg.get("evento_lugar"):
        ciudad, pais = _pais_en_texto(reg["evento_lugar"])
        if pais:
            datos["ciudad"], datos["pais"] = ciudad, pais

    f = re.search(rf"(\d{{1,2}})\s*(?:[-–]\s*\d{{1,2}}\s*)?({MES})\.?,?\s+(\d{{4}})", v, re.I)
    if f:
        datos["fecha"] = f"{int(f.group(1)):02d}/{meses[f.group(2).lower()]}/{f.group(3)}"
    else:
        f = re.search(rf"({MES})\.?\s+(\d{{1,2}})\s*(?:[-–]\s*\d{{1,2}})?,?\s+(\d{{4}})",
                      v, re.I)
        if f:
            datos["fecha"] = f"{int(f.group(2)):02d}/{meses[f.group(1).lower()]}/{f.group(3)}"
    return datos


def mes_anio(fecha: str) -> str:
    """dd/mm/aaaa o mm/aaaa -> mm/aaaa, que es lo que pide SIGEVA.

    sede_evento devuelve dd/mm/aaaa cuando la saca del booktitle, pero
    datos-manuales.json la trae en mm/aaaa: hay que aceptar las dos.
    """
    partes = (fecha or "").split("/")
    return "/".join(partes[-2:]) if len(partes) in (2, 3) else ""


def _pais_en_texto(texto: str) -> tuple:
    """Busca un pais conocido en un texto libre y devuelve (ciudad, pais)."""
    for clave, etiqueta in PAISES.items():
        m = re.search(r"(?:^|[,\s])" + re.escape(clave) + r"\s*$", texto, re.I)
        if m:
            ciudad = texto[:m.start()].strip(" ,")
            ciudad = re.sub(r",?\s*[A-Z]{2}$", "", ciudad).strip(" ,")
            return ciudad, etiqueta
    return "", ""


def tipo_reunion_de(reg: dict) -> str:
    v = sinacentos(reg["venue"])
    for k, etiqueta in TIPO_REUNION.items():
        if k in v:
            return etiqueta
    return "Conferencia"


# La precarga por DOI deja Editorial y Pais de edicion vacios (y son obligatorios).
# El prefijo del DOI identifica a la editorial sin ambiguedad.
POR_PREFIJO_DOI = {
    "10.1109": ("IEEE", "Estados Unidos"),
    "10.1016": ("Elsevier", "Países Bajos"),
    "10.1007": ("Springer", "Alemania"),
    "10.1145": ("Association for Computing Machinery", "Estados Unidos"),
    "10.3389": ("Frontiers Media", "Suiza"),
    "10.3390": ("MDPI", "Suiza"),
    "10.1002": ("Wiley", "Estados Unidos"),
    "10.1049": ("Institution of Engineering and Technology", "Reino Unido"),
    "10.1080": ("Taylor & Francis", "Reino Unido"),
    "10.1155": ("Hindawi", "Reino Unido"),
    "10.1504": ("Inderscience", "Reino Unido"),
    "10.1017": ("Cambridge University Press", "Reino Unido"),
    "10.4108": ("EAI", "Bélgica"),
    "10.5194": ("Copernicus", "Alemania"),
}
POR_NOMBRE = {
    "ieee": ("IEEE", "Estados Unidos"),
    "elsevier": ("Elsevier", "Países Bajos"),
    "springer": ("Springer", "Alemania"),
    "acm": ("Association for Computing Machinery", "Estados Unidos"),
    "wiley": ("Wiley", "Estados Unidos"),
    "frontiers": ("Frontiers Media", "Suiza"),
    "mdpi": ("MDPI", "Suiza"),
    "artech": ("Artech House", "Estados Unidos"),
    "iet": ("Institution of Engineering and Technology", "Reino Unido"),
}


def editorial_y_pais(reg: dict) -> tuple:
    """Deduce (editorial, pais de edicion) del DOI, o del texto si no hay DOI."""
    if reg.get("editorial") and reg.get("pais_edicion"):
        return reg["editorial"], reg["pais_edicion"]
    doi = reg.get("doi") or ""
    prefijo = doi.split("/")[0]
    if prefijo in POR_PREFIJO_DOI:
        return POR_PREFIJO_DOI[prefijo]
    texto = sinacentos(f"{reg.get('editorial','')} {reg.get('venue','')}")
    for clave, par in POR_NOMBRE.items():
        if clave in texto:
            return par
    return (reg.get("editorial") or "", "")


def asegurar_editorial(page, reg: dict) -> list:
    """La editorial es obligatoria: se garantiza que quede algo cierto.

    Si el DOI y el texto no la identifican, se usa el nombre del organismo que
    aparece en el venue, y como ultimo recurso el propio nombre de la
    publicacion. Nunca se inventa una editorial de un tercero.
    """
    avisos = []
    campo = page.locator('input[name="editorial"]')
    if not campo.count():
        return avisos
    if campo.first.input_value().strip():
        return avisos

    editorial, _ = editorial_y_pais(reg)
    if not editorial:
        venue = reg.get("venue_oficial") or reg.get("venue") or ""
        m = re.search(r"\b(IEEE|ACM|AIAA|IET|IFIP|Springer|Elsevier|Wiley|MDPI|"
                      r"USENIX|SPIE|AAS|CEUR)\b", venue, re.I)
        editorial = m.group(1).upper() if m else venue.split(",")[0][:80]
    if editorial:
        campo.first.fill(editorial)
        avisos.append(f"editorial deducida: {editorial[:40]}")
    else:
        avisos.append("editorial vacía (SIGEVA la exige)")

    sel = page.locator('select[name="pais"], select[name="paisEdicion"]')
    if sel.count() and sel.first.input_value() in ("", "-1", "-2"):
        avisos.append("país de edición vacío")
    return avisos


def fijar_fechas(page, fechas: dict) -> None:
    """Escribe las fechas y verifica que queden. Va justo antes de Guardar.

    Los campos de fecha son datepickers de jQuery UI (calendar-year-month,
    calendar-year). Al cerrarse, el picker escribe en el campo el mes y año
    que tiene SELECCIONADOS, y no lo que se tipeo; sin seleccion, es el mes
    actual. Con page.fill el picker se abre, y al pasar al campo siguiente
    se cierra y pisa la fecha: asi quedaron en 07/2026 los 70 registros de
    julio. Por eso se fija con setDate, que mueve la seleccion y el valor
    juntos, y se escribe tambien el input oculto que algunos formularios
    repiten con el mismo name.
    """
    resultado = page.evaluate(
        """(fechas) => {
            const $ = window.jQuery;
            // un picker abierto escribiria su seleccion al cerrarse
            if ($) $('.hasDatepicker').each(function () { $(this).datepicker('hide'); });
            if (document.activeElement) document.activeElement.blur();
            const leido = {};
            for (const [nombre, valor] of Object.entries(fechas)) {
                const p = valor.split('/');
                const d = p.length === 2 ? new Date(+p[1], +p[0] - 1, 1) : new Date(+p[0], 1, 1);
                document.getElementsByName(nombre).forEach(el => {
                    if (el.type !== 'hidden' && $ && $(el).hasClass('hasDatepicker'))
                        $(el).datepicker('setDate', d);
                    else
                        el.value = valor;
                });
                leido[nombre] = Array.from(document.getElementsByName(nombre)).map(e => e.value);
            }
            return leido;
        }""", fechas)
    for nombre, valor in fechas.items():
        if not resultado.get(nombre) or any(v != valor for v in resultado[nombre]):
            raise RuntimeError(f"la fecha {nombre} quedó {resultado.get(nombre)} "
                               f"en vez de {valor}")


def fecha_evento_de(reg: dict) -> str:
    """Fecha del evento en mm/aaaa.

    Si no se conoce la sede se usa la de publicacion: para un paper de
    congreso es del mismo año.
    """
    return (mes_anio(sede_evento(reg)["fecha"])
            or reg.get("fecha_publicacion") or f"01/{reg['anio']}")


def fechas_de(page, reg: dict) -> dict:
    """Las fechas que corresponden a este registro, segun los campos del formulario.

    Cada vuelta por el buscador de revistas o de instituciones re-renderiza el
    formulario, asi que se escriben al final, con fijar_fechas.
    """
    fechas = {}
    if page.locator('input[name="fechaPublica"]').count() and reg.get("fecha_publicacion"):
        fechas["fechaPublica"] = reg["fecha_publicacion"]
    if page.locator('input[name="anioPublica"]').count():
        fechas["anioPublica"] = str(reg["anio"])
    if page.locator('input[name="fechaReunion"]').count():
        fechas["fechaReunion"] = fecha_evento_de(reg)
    return fechas


def anio_esperado(reg: dict) -> int:
    """Año que la lista de SIGEVA debe mostrar despues de guardar.

    En articulos sale de la fecha de publicacion; en eventos, del año de
    publicacion de las actas.
    """
    if reg["tipo"] == "articulo" and reg.get("fecha_publicacion"):
        return int(reg["fecha_publicacion"].split("/")[-1])
    return int(reg["anio"])


def limpiar_titulo(s: str) -> str:
    """Saca restos de LaTeX que el bib arrastra ($mu$D3TN -> muD3TN)."""
    s = re.sub(r"\$([^$]*)\$", r"\1", s)
    return a_latin1(re.sub(r"\s{2,}", " ", s.replace("\\", "")).strip())


# --------------------------------------------------------------------- sesion

def esperar_login(page, espera_ms: int = 300_000) -> None:
    page.goto(INTRANET, wait_until="domcontentloaded")
    if page.locator('a[onclick*="redirect("]').count() > 0:
        log("Sesión ya autenticada.")
        return

    # Modo desatendido: credenciales por variable de entorno, nunca en archivo.
    #   SIGEVA_USER=... SIGEVA_PASS=... python3 cargar.py
    usuario, clave = os.environ.get("SIGEVA_USER"), os.environ.get("SIGEVA_PASS")
    if usuario and clave:
        log("Ingresando con las credenciales del entorno.")
        page.wait_for_selector('input#username', timeout=30_000)
        page.fill('input#username', usuario)
        page.fill('input#password', clave)
        page.click('button[name="submitBtn"]')
        try:
            # los enlaces de rol viven en un menu colapsado: estan en el DOM
            # pero no visibles, asi que se espera 'attached', no 'visible'
            page.wait_for_selector('a[onclick*="redirect("]', state="attached",
                                   timeout=60_000)
            log("Sesión iniciada.")
            return
        except PWTimeout:
            # SIGEVA bloquea el usuario al 5to intento fallido: dejamos evidencia
            # en vez de reintentar a ciegas.
            CAPTURAS.mkdir(exist_ok=True)
            page.screenshot(path=str(CAPTURAS / "login-fallido.png"), full_page=True)
            sys.exit(f"No pude iniciar sesión. Quedé en {page.url}\n"
                     f"Mirá capturas/login-fallido.png antes de reintentar.")

    print("\n" + "=" * 66)
    print("  Ingresá tu usuario y contraseña en la ventana de Chromium.")
    print(f"  Yo no los veo ni los guardo. Espero hasta {espera_ms // 60_000} minutos.")
    print("=" * 66 + "\n")
    try:
        page.wait_for_selector('a[onclick*="redirect("]', state="attached",
                                timeout=espera_ms)
    except PWTimeout:
        sys.exit("No detecté la sesión iniciada. Volvé a correrlo.")
    log("Sesión detectada.")


def entrar_banco_datos(page) -> None:
    page.goto(INTRANET, wait_until="domcontentloaded")
    page.evaluate(f"redirect({ROL_BANCO_DATOS})")
    page.wait_for_url("**/eva/**", timeout=30_000)
    log("Dentro del Banco de Datos.")


def sesion_viva(page) -> bool:
    return "/eva/" in page.url and "login" not in page.url.lower()


# ------------------------------------------------------------------- llenado

def rellenar_junto_a(page, etiqueta: str, valor: str) -> bool:
    """Llena el input que sigue a una etiqueta. True si escribio algo.

    Algunos campos (Editorial) aparecen como input solo cuando la precarga no
    los completo, y en esa forma no tienen 'name' util.
    """
    return page.evaluate(
        """([etiqueta, valor]) => {
            const celdas = Array.from(document.querySelectorAll('td,th,label,span'));
            const rot = celdas.find(e => new RegExp('^' + etiqueta + '\\\\s*:?\\\\s*\\\\*?$', 'i')
                                          .test((e.textContent||'').trim()));
            if (!rot) return false;
            let n = rot.nextElementSibling;
            for (let i = 0; n && i < 3; i++, n = n.nextElementSibling) {
                const c = n.querySelector('input[type=text]');
                if (c && !c.readOnly && !c.value.trim()) {
                    c.value = valor;
                    c.dispatchEvent(new Event('input', {bubbles: true}));
                    c.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
            }
            return false;
        }""", [etiqueta, valor])


def mostrar_todos_los_autores(page) -> None:
    """Despliega la tabla de autores completa.

    En articulos, cada vez que el formulario vuelve del buscador de
    instituciones la tabla muestra solo algunos autores y un boton
    "Ver más (4/8)". El Buscar de una fila oculta no se puede clickear.
    """
    botones = page.locator('input[name="btnSubmitBuscar"]')
    for _ in range(10):
        if all(botones.nth(i).is_visible() for i in range(botones.count())):
            return
        # por texto y no por tag: el control no es un <button> ni un <input>
        ver_mas = page.get_by_text(re.compile(r"Ver m[aá]s"))
        visibles = [i for i in range(ver_mas.count()) if ver_mas.nth(i).is_visible()]
        if not visibles:
            return
        ver_mas.nth(visibles[0]).click()
        page.wait_for_timeout(400)


def completar_comunes(page, reg: dict, con_adjunto: bool) -> list:
    """Campos que comparten los dos formularios. Devuelve avisos."""
    avisos = []

    # si el flujo de instituciones no volvio al formulario, esto corre sobre la
    # pantalla equivocada y se cuelga 30s por campo: mejor cortar en seco
    if not page.locator('select[name="idioma"]').count():
        raise RuntimeError("el formulario no volvió tras cargar las instituciones "
                           f"(quedé en {page.url.split('/')[-1][:60]})")
    page.select_option('select[name="idioma"]', label=idioma_de(reg))

    resumen = reg.get("resumen") or ""
    if resumen:
        page.fill('textarea[name="hdnresumen"]', a_latin1(resumen))
    else:
        # SIGEVA lo exige, asi que sin resumen el guardado va a fallar igual
        raise RuntimeError("sin resumen (SIGEVA lo exige); conseguirlo primero")

    # campo_0_0 lo puebla JavaScript al cambiar campo_0, y despues del flujo de
    # instituciones puede tardar: se espera a que aparezca la opcion buscada
    page.select_option('select[name="campo_0"]', AREA_CONOCIMIENTO[0])
    subcampo = AREA_CONOCIMIENTO[1]
    for intento in range(6):
        page.wait_for_timeout(500)
        # config.json admite el value del combo o un trozo de su etiqueta: los
        # subcampos llegan por AJAX y su value no figura en el HTML inicial
        valor = subcampo if subcampo.isdigit() else _opcion_por_texto(
            page, 'select[name="campo_0_0"]', re.escape(subcampo))
        if valor and _elegir(page, 'select[name="campo_0_0"]', valor):
            break
    else:
        avisos.append("no pude fijar el área del conocimiento")

    campos = page.locator('input[name="palabraLabel"]')
    for i, palabra in enumerate(palabras_clave(reg, min(4, campos.count()))):
        campos.nth(i).fill(palabra)

    if con_adjunto and reg.get("pdf") and Path(reg["pdf"]).exists():
        mb = Path(reg["pdf"]).stat().st_size / 2**20
        if mb > MAX_PDF_MB:
            raise RuntimeError(
                f"el PDF pesa {mb:.0f} MB y SIGEVA acepta hasta {MAX_PDF_MB}. "
                "Comprimirlo, por ejemplo: gs -sDEVICE=pdfwrite "
                "-dPDFSETTINGS=/printer -o chico.pdf grande.pdf")
        page.set_input_files('input[name="theFile"]', reg["pdf"])
        # el Instructivo recomienda el Post-Print (version aceptada); si no
        # esta en la lista se usa la primera opcion real. Cuando lo unico que
        # hay es el preprint (arXiv), "version_pdf": "preprint" en
        # datos-manuales.json lo declara como tal: ponerle post-print seria falso
        preprint = reg.get("version_pdf") == "preprint"
        valor = page.evaluate(
            """(preprint) => {
                const s = document.querySelector('select[name="tipoAdjunto"]');
                if (!s) return null;
                const opts = Array.from(s.options).filter(o => o.value && o.value !== '-1');
                if (preprint) {
                    const pre = opts.find(o => /pre.?print/i.test(o.text));
                    return pre ? pre.value : 'sin-preprint';
                }
                const pref = opts.find(o => /post.?print|aceptad/i.test(o.text));
                return (pref || opts[0] || {}).value || null;
            }""", preprint)
        if valor == "sin-preprint":
            raise RuntimeError("el PDF es un preprint y el formulario no ofrece "
                               "esa opción en el tipo de adjunto")
        if valor:
            page.select_option('select[name="tipoAdjunto"]', valor)
        # el formulario de eventos no tiene ese selector: no es un problema
    elif con_adjunto:
        avisos.append("sin PDF")
    return avisos


def cargar_articulo(page, reg: dict) -> list:
    # el importador de SIGEVA (Crossref/Elsevier) es lento y a veces no responde:
    # dos intentos antes de darlo por perdido
    # DBLP escribe los DOI con tramos en mayuscula (10.1016/J.COMNET...) y el
    # importador de Elsevier no siempre los resuelve asi: se prueba tal cual y
    # despues en minusculas.
    # El importador es intermitente: cuando responde lo hace en 2-3 segundos, y
    # cuando no, no responde nunca. Conviene un timeout corto y varios intentos
    # espaciados, alternando la capitalizacion del DOI.
    minusculas = reg["doi"].lower()
    variantes = [reg["doi"], minusculas, reg["doi"], minusculas]
    if minusculas == reg["doi"]:
        variantes = [reg["doi"]] * 4

    for i, doi in enumerate(variantes):
        if i:
            page.wait_for_timeout(4_000)        # respiro entre intentos
        page.goto(URL_NUEVO_ARTICULO, wait_until="domcontentloaded")
        page.fill('input[name="identificador"]', doi)
        page.click('input[type="submit"][value="Precargar"]')
        # el submit navega: hay que esperar el formulario destino, no el load
        # state (que vuelve de inmediato sobre la pagina vieja)
        try:
            page.wait_for_selector('select[name="idioma"]', state="attached",
                                   timeout=25_000)
            if i:
                log(f"    precarga OK en el intento {i + 1}")
            break
        except PWTimeout:
            if i == len(variantes) - 1:
                CAPTURAS.mkdir(exist_ok=True)
                page.screenshot(
                    path=str(CAPTURAS / f"precarga-fallida-{reg['clave'][:30]}.png"),
                    full_page=True)
                raise RuntimeError(
                    f"la precarga no respondió en {len(variantes)} intentos "
                    f"(DOI {reg['doi']})")

    avisos = completar_comunes(page, reg, con_adjunto=True)

    # La precarga es inconsistente: a veces trae Editorial y Pais, a veces los
    # deja vacios (y son obligatorios). Editorial solo existe como input cuando
    # falta, y sin 'name' estable, asi que se ubica por su etiqueta.
    editorial, pais = editorial_y_pais(reg)
    if editorial and not rellenar_junto_a(page, "Editorial", editorial):
        pass                                    # ya venia de la precarga
    elif not editorial:
        avisos.append("editorial sin deducir")

    sel_pais = page.locator('select[name="pais"]')
    if sel_pais.count() and sel_pais.first.input_value() in ("", "-1", "-2"):
        if pais:
            try:
                page.select_option('select[name="pais"]', label=pais)
            except Exception:
                avisos.append(f"país '{pais}' no está en la lista")
        else:
            avisos.append("país de edición sin deducir")

    # SIGEVA exige fecha de publicacion en mm/aaaa. La escribe fijar_fechas al
    # final, con la del registro aunque la precarga haya traido otra
    campo_fecha = page.locator('input[name="fechaPublica"]')
    if campo_fecha.count() and not reg.get("fecha_publicacion") \
            and not campo_fecha.first.input_value().strip():
        avisos.append("sin fecha de publicación")
    elif reg.get("fecha_aproximada"):
        avisos.append("mes de publicación estimado")

    paginas = re.match(r"\s*(\d+)\s*-\s*(\d+)", reg.get("paginas") or "")
    if paginas:
        for campo, valor in (("paginaInicial", paginas.group(1)),
                             ("paginaFinal", paginas.group(2))):
            loc = page.locator(f'input[name="{campo}"]')
            if loc.count() and not loc.first.input_value().strip():
                loc.first.fill(valor)

    if page.locator('input[name="autorSel"]:checked').count() == 0:
        avisos.append("no quedó marcado el autor declarante")
    return avisos


def elegir_revista(page, reg: dict) -> list:
    """Elige la revista del catalogo por ISSN (o por nombre), o la da de alta.

    Es la parte que reemplaza al importador roto: buscar por ISSN es
    determinista, y si la revista no esta en el catalogo hay un camino de alta
    manual en la misma pantalla.
    """
    avisos = []
    issn = (reg.get("issn") or "").strip()
    nombre = (reg.get("venue_oficial") or reg.get("venue") or "").strip()

    def buscar(por_issn: bool) -> int:
        if por_issn:
            page.fill('input[name="bissn"]', issn)
            page.click('input[value="Buscar por ISSN / e-ISSN"]')
        else:
            page.fill('input[name="brevista"]', nombre[:60])
            page.click('input[value="Buscar por Nombre"]')
        page.wait_for_selector('input[type="submit"][value="Seleccionar"]',
                               state="attached", timeout=45_000)
        return page.locator('input[name="idPublicacion"]').count()

    encontradas = buscar(por_issn=bool(issn))
    if not encontradas and issn and nombre:
        # el ISSN no dio nada: probar por nombre antes de darla de alta
        encontradas = buscar(por_issn=False)

    opciones = page.locator('input[name="idPublicacion"]')
    if encontradas:
        opciones.first.check()
        if encontradas > 1:
            avisos.append(f"{encontradas} revistas coincidían, tomé la primera")
    elif issn:
        # no esta en el catalogo: alta como "otra revista". SIGEVA la acepta
        # solo con ISSN o e-ISSN, asi que sin ISSN no hay camino por aca.
        page.check('input[name="otraRevistaSeleccionada"]')
        page.fill('input[name="botrarevista"]', nombre[:120])
        page.fill('input[name="botroissn"]', issn)
        avisos.append("revista cargada como 'otra' (no figura en el catálogo)")
    else:
        raise RuntimeError(
            f"la revista '{nombre[:50]}' no está en el catálogo y no tengo su "
            f"ISSN, que SIGEVA exige para darla de alta")

    page.click('input[type="submit"][value="Seleccionar"]')
    page.wait_for_selector('input[name="produccion"]', state="attached", timeout=45_000)
    return avisos


# SIGEVA exige institucion para CADA autor. El catalogo es casi solo argentino,
# asi que las extranjeras se dan de alta por "Ingresar otra".
PLACEHOLDER_INSTITUCION = "SIN DATO"
TIPO_UNIV_ESTATAL = "75"          # para buscar en el catalogo argentino
TIPO_INTERNACIONAL = "81"         # "Entidad internacional", para las de afuera

PAIS_ISO = {
    "AR": "Argentina", "US": "Estados Unidos", "FR": "Francia", "DE": "Alemania",
    "CN": "China", "ES": "España", "IT": "Italia", "GB": "Reino Unido",
    "NL": "Países Bajos", "BE": "Bélgica", "CH": "Suiza", "AT": "Austria",
    "PT": "Portugal", "GR": "Grecia", "SE": "Suecia", "NO": "Noruega",
    "FI": "Finlandia", "DK": "Dinamarca", "PL": "Polonia", "CZ": "República Checa",
    "IE": "Irlanda", "CA": "Canadá", "BR": "Brasil", "CL": "Chile", "MX": "México",
    "CO": "Colombia", "PE": "Perú", "UY": "Uruguay", "JP": "Japón", "IN": "India",
    "KR": "Corea del Sur", "AU": "Australia", "IL": "Israel", "TR": "Turquía",
    "RU": "Rusia", "SG": "Singapur", "LU": "Luxemburgo", "RO": "Rumania",
}


def _elegir(page, selector: str, valor: str) -> bool:
    """select_option sobre el PRIMER combo que matchea.

    En la pantalla de instituciones hay varios select con el mismo name (el
    bloque de filtro y el de alta), y page.select_option falla por ambiguedad
    en modo estricto. Con .first el fallo desaparece.
    """
    try:
        page.locator(selector).first.select_option(valor, timeout=8_000)
        return True
    except Exception as e:
        log(f"      no pude fijar {selector}: {str(e).splitlines()[0][:70]}")
        return False


def _opcion_por_texto(page, selector: str, patron: str) -> str | None:
    """Devuelve el value de la opcion cuyo texto matchea, o None."""
    return page.evaluate(
        """([sel, pat]) => {
            const e = document.querySelector(sel);
            if (!e) return null;
            const rx = new RegExp(pat, 'i');
            const o = Array.from(e.options).find(x => rx.test(x.text.trim()));
            return o ? o.value : null;
        }""", [selector, patron])


def asignar_institucion(page, fila: int, autor: dict) -> str:
    """Asigna la institucion del autor de la fila indicada. Devuelve un aviso o ''.

    Los combos se manejan con select_option (eventos reales): si se les asigna
    el value por JavaScript, Struts no registra el cambio y la busqueda vuelve
    siempre vacia.
    """
    nombre_inst = (autor.get("institucion") or "").strip() or PLACEHOLDER_INSTITUCION
    pais_es = PAIS_ISO.get((autor.get("pais_institucion") or "").upper(), "")

    # SIGEVA exige al menos 3 caracteres en el campo de la fila antes de
    # abrir el buscador; si se aprieta Buscar vacio contesta "El texto a buscar
    # tiene menos de 3 caracteres" y la pantalla nunca se abre.
    mostrar_todos_los_autores(page)
    campo = page.locator('input[name="autorOrganizacionBuscar"]')
    boton = page.locator('input[name="btnSubmitBuscar"]').nth(fila)
    if boton.is_visible():
        if fila < campo.count():
            campo.nth(fila).fill(nombre_inst[:60])
        boton.click()
    else:
        # la fila sigue oculta: el click de Playwright esperaria a que se vea.
        # Desde JavaScript el handler corre igual.
        page.evaluate(
            """([fila, texto]) => {
                const c = document.getElementsByName('autorOrganizacionBuscar')[fila];
                if (c) c.value = texto;
                document.getElementsByName('btnSubmitBuscar')[fila].click();
            }""", [fila, nombre_inst[:60]])
    page.wait_for_selector('select[name="filtroPais"]', state="attached", timeout=60_000)

    # La busqueda valida tres cosas y avisa con mensajes propios:
    #   - el tipo de institucion es obligatorio siempre
    #   - si el pais es Argentina, tambien la provincia
    #   - hay que elegir una existente o dar de alta una nueva "en el nivel
    #     inferior" (el bloque de "otra organizacion")
    val_pais = _opcion_por_texto(page, 'select[name="filtroPais"]',
                                 f"^{re.escape(pais_es)}$") if pais_es else None
    if val_pais:
        # cada cambio de combo puede re-renderizar el bloque: si uno no
        # responde se sigue igual, porque el alta manual cubre el caso
        _elegir(page, 'select[name="filtroPais"]', val_pais)
        page.wait_for_timeout(600)          # el combo de provincia se repuebla
        if pais_es == "Argentina":
            prov = _opcion_por_texto(page, 'select[name="filtroProvincia"]',
                                     "rdoba|Buenos Aires")
            if prov:
                _elegir(page, 'select[name="filtroProvincia"]', prov)
        # sin filtrar por tipo: el catalogo registra cada institucion con el
        # suyo (JPL, PUC de Chile...) y filtrar de mas las esconde
        page.fill('input[name="filtroOrganizacion"]', nombre_inst[:40])
        page.click('input[type="button"][value="Buscar"]')
        page.wait_for_timeout(1_500)
        # Solo sirve un resultado que sea REALMENTE la institucion buscada: la
        # busqueda por pais devuelve todo lo que hay de ese pais, y quedarse
        # con el primero adjudicaria una filiacion falsa.
        # se ignoran las palabras genericas: SIGEVA castellaniza los nombres
        # ("Universitat Politecnica" -> "UNIVERSIDAD POLITECNICA") y exigirlas
        # todas haria fallar el match
        from catalogo import GENERICAS
        distintivas = lambda s: {w for w in re.findall(r"[a-z]{4,}", sinacentos(s))
                                 if w not in GENERICAS}
        objetivo = distintivas(nombre_inst)
        opciones = page.locator("span.orgBuscar")
        for i in range(min(opciones.count(), 40)):
            texto = opciones.nth(i).inner_text()
            if objetivo and objetivo <= distintivas(texto):
                opciones.nth(i).click()
                # el boton Seleccionar recien aparece cuando la pantalla se
                # actualiza con la institucion elegida
                try:
                    page.wait_for_selector('input[value="Seleccionar"]',
                                           state="attached", timeout=20_000)
                    page.locator('input[value="Seleccionar"]').first.click()
                    page.wait_for_selector('input[name="produccion"]',
                                           state="attached", timeout=60_000)
                    return ""
                except PWTimeout:
                    pass
                break

    # No esta en el catalogo. El bloque de alta ("Solo en caso de no encontrar
    # la institucion...") YA esta en esta misma pantalla: hay que completarlo y
    # recien entonces apretar INGRESAR OTRA. Apretarlo antes envia el bloque
    # vacio y dispara las validaciones de pais/provincia/tipo.
    if pais_es:
        val = _opcion_por_texto(page, 'select[name="pais"]',
                                f"^{re.escape(pais_es)}$")
        if val:
            _elegir(page, 'select[name="pais"]', val)
            page.wait_for_timeout(1_200)    # el combo de provincia se repuebla

    # La provincia es obligatoria si el pais es Argentina, y el combo se
    # repuebla por JavaScript al cambiar el pais. Si quedan opciones reales se
    # elige una: sin eso el alta se rechaza.
    opciones_prov = page.evaluate(
        """() => {
            const e = document.querySelector('select[name="provincia"]');
            if (!e) return [];
            return Array.from(e.options)
                .filter(o => o.value && o.value !== '-1')
                .map(o => [o.value, o.text.trim()]);
        }""")
    if opciones_prov:
        elegida = None
        for valor, texto in opciones_prov:
            if re.search(r"rdoba|Buenos Aires", texto, re.I):
                elegida = valor
                break
        _elegir(page, 'select[name="provincia"]', elegida or opciones_prov[0][0])
    _elegir(page, 'select[name="tipoOtraOrganizacion"]', TIPO_INTERNACIONAL)
    page.fill('input[name="otraOrganizacion"]', nombre_inst[:120])
    page.click('input[value="Ingresar otra"]')
    try:
        page.wait_for_selector('input[name="produccion"]', state="attached",
                               timeout=45_000)
    except PWTimeout:
        # quedo en la pantalla de instituciones: contar por que
        cuerpo = page.inner_text("body")
        quejas = re.findall(r"(?:Debe|Si selecciona)[^\n]{0,110}", cuerpo)[:3]
        CAPTURAS.mkdir(exist_ok=True)
        page.screenshot(path=str(CAPTURAS / "alta-institucion-fallida.png"),
                        full_page=True)
        raise RuntimeError("el alta de '" + nombre_inst[:34] + "' fue rechazada: "
                           + " | ".join(q.strip() for q in quejas))
    return "" if autor.get("institucion") else f"{autor['apellido']}: institución sin dato"


def fijar_soporte(page, reg: dict) -> list:
    """Marca el soporte y, si es electronico, exige URL o DOI.

    Se aplica DESPUES de cargar autores: el flujo de alta de instituciones
    re-renderiza el formulario y pierde los checkboxes.
    """
    avisos = []
    enlace = reg.get("url") or (f"https://doi.org/{reg['doi']}" if reg.get("doi") else "")
    soportes = page.locator('input[name="tipoSoporteChecked"]')
    if soportes.count() < 2:
        return avisos
    if enlace:
        if not soportes.nth(1).is_checked():
            soportes.nth(1).check()
        campo = page.locator('input[name="web"]')
        if campo.count() and not campo.first.input_value().strip():
            campo.first.fill(enlace[:250])
    else:
        if soportes.nth(1).is_checked():
            soportes.nth(1).uncheck()
        if not soportes.nth(0).is_checked():
            soportes.nth(0).check()
        avisos.append("sin URL ni DOI: se declara sólo impreso")
    return avisos


def falta_en_catalogo(reg: dict, cat) -> bool:
    """True si algun coautor tiene una institucion que no esta en el catalogo.

    En ese caso no sirve inyectar: SIGEVA no puede persistir una filiacion
    contra una organizacion inexistente (TransientPropertyValueException) y el
    guardado falla sin mensaje. Hay que darla de alta por el flujo real, que la
    crea de verdad. Una vez creada queda en el catalogo para siempre.
    """
    from catalogo import BASURA
    for a in reg.get("autores", []):
        nombre = (a.get("institucion") or "").strip()
        # mismo criterio que inyectar_autores: lo verificado a mano no se filtra
        if not nombre or (BASURA.match(nombre) and not a.get("verificada")):
            continue
        if CFG.es_declarante(a["apellido"]):
            continue
        if not cat.institucion(nombre):
            return True
    return False


def cargar_autores(page, reg: dict) -> list:
    """Carga los autores en orden y marca al declarante (config.json: apellido).

    La institucion de cada coautor se deja vacia a proposito: el buscador anda
    mal y no hace falta.
    """
    avisos = []
    filas = page.locator('input[name="autorParticipacionLabel"]')
    boton = page.locator('button[name="autorNuevo"], input[name="autorNuevo"]')
    intentos = 0
    while filas.count() < len(reg["autores"]) and boton.count() and intentos < 40:
        boton.first.click()
        page.wait_for_timeout(150)
        intentos += 1

    propio = None
    for i, autor in enumerate(reg["autores"]):
        if i >= filas.count():
            break
        filas.nth(i).fill(a_latin1(f"{autor['apellido']}, {autor['nombre']}".strip(", ")))
        if CFG.es_declarante(autor["apellido"]):
            propio = i
    if len(reg["autores"]) > filas.count():
        avisos.append(f"entraron {filas.count()} de {len(reg['autores'])} autores")

    if propio is not None:
        radios = page.locator('input[name="autorSel"]')
        if propio < radios.count():
            radios.nth(propio).check()
        # sin radio (14.11.24.5 en adelante) se marca como en inyectar_autores
        elif not page.evaluate(
                """([i, personaId]) => {
                    const p = document.getElementsByName('autorPersonaId')[i];
                    if (!p || !personaId) return false;
                    p.value = personaId;
                    return true;
                }""", [propio, CFG.PERSONA_ID]):
            avisos.append("no pude marcar al declarante (¿falta sigeva.persona_id en config.json?)")
    else:
        avisos.append(f"no encontré a {CFG.CONF['apellido']} entre los autores")

    # institucion de cada autor: SIGEVA la exige para todos. La del declarante la
    # completa el sistema solo, asi que se saltea.
    sin_dato = 0
    for i, autor in enumerate(reg["autores"]):
        if i >= filas.count() or i == propio:
            continue
        try:
            if asignar_institucion(page, i, autor):
                sin_dato += 1
        except PWTimeout:
            CAPTURAS.mkdir(exist_ok=True)
            try:
                page.screenshot(path=str(CAPTURAS / "institucion-atascada.png"),
                                full_page=True)
                # el HTML dice mas que la captura: filas ocultas, controles
                (CAPTURAS / f"institucion-atascada-{reg['clave'][:30]}.html") \
                    .write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
            # sin volver al formulario no se puede seguir con este registro
            raise RuntimeError(
                f"el alta de institución de {autor['apellido']} no volvió al "
                f"formulario")
    if sin_dato:
        avisos.append(f"{sin_dato} autores con institución '{PLACEHOLDER_INSTITUCION}'")
    return avisos


def buscar_en_lista(page, reg: dict) -> dict | None:
    """Busca el registro en la lista viva de SIGEVA: {anio, href} o None.

    'anio' es el que muestra la lista y 'href' el enlace de Editar. SIGEVA
    puede volver del Guardar sin mensaje de error y sin haber guardado nada,
    asi que el unico criterio confiable es encontrarlo en la lista. Sirve
    tambien antes de crear, para no duplicar lo que se cargo por otro camino.

    Despues del Guardar la pagina puede seguir navegando (popup de upload,
    redirect) y eso destruye el contexto en medio del evaluate: se espera a
    que asiente y se reintenta.
    """
    for intento in range(5):
        try:
            page.wait_for_load_state("load", timeout=45_000)
            return _buscar_en_lista(page, reg)
        except Exception as e:
            if "context was destroyed" not in str(e) or intento == 4:
                raise
            log("    la página seguía navegando, reintento la verificación")
            page.wait_for_timeout(4_000)
    return None


def confirmar_guardado(page, reg: dict, intentos: int = 6) -> dict | None:
    """buscar_en_lista con paciencia, para usar despues de Guardar.

    Con PDF grandes la subida sigue en curso cuando la pagina ya volvio a la
    lista: el registro aparece segundos despues. Darlo por no guardado en ese
    momento invitaba a reintentar y duplicar.
    """
    for i in range(intentos):
        fila = buscar_en_lista(page, reg)
        if fila:
            return fila
        if i < intentos - 1:
            page.wait_for_timeout(10_000)
    return None


def _buscar_en_lista(page, reg: dict) -> dict | None:
    """Una pasada por la lista.

    Se mira solo la columna Titulo de la tabla del tipo que corresponde (la
    pagina trae articulos, libros y eventos juntos, y un paper de congreso y su
    version de revista pueden compartir titulo). La lista trunca los titulos
    con "...", asi que se compara por prefijo. El año NO filtra: hay registros
    guardados con el año mal (los de julio de 2026), y filtrar por año los
    haria invisibles y terminaria en un duplicado. Se devuelve para que quien
    llama lo verifique. Se recorren todas las paginas, no un numero fijo.
    """
    clave = re.sub(r"[^a-z0-9]", "", sinacentos(limpiar_titulo(reg["titulo"])))
    if not clave:
        return None
    r = page.evaluate(
        r"""async ([clave, tabla]) => {
            const dec = new TextDecoder('iso-8859-1');
            const base = 'bcoProduccionListaPublicacion.do?idMenu=1466&paginar=true'
                       + '&idModulo=6&prod=cientifica&idGrupo=6';
            const norm = (s) => (s || '').normalize('NFKD')
                .replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
            const vistas = new Set();
            for (let p = 1; p <= 40; p++) {
                const r = await fetch(`${base}&d-${tabla}-p=${p}`, {credentials: 'same-origin'});
                const doc = new DOMParser().parseFromString(dec.decode(await r.arrayBuffer()), 'text/html');
                // por el parametro de orden (-s): desde la pagina 2 los enlaces
                // de todas las tablas copian la query, con el -p de esta
                const t = Array.from(doc.querySelectorAll('table'))
                    .find(x => x.tHead && x.tHead.innerHTML.includes(`d-${tabla}-s=`));
                if (!t) return p === 1 ? 'sin-tabla' : null;
                const cab = Array.from(t.tHead.querySelectorAll('th'))
                    .map(h => h.textContent.trim());
                const iTit = cab.indexOf('Título'), iAnio = cab.indexOf('Año');
                if (iTit < 0) return 'sin-tabla';
                let nuevas = 0;
                for (const f of (t.tBodies.length ? Array.from(t.tBodies[0].rows) : [])) {
                    const celdas = Array.from(f.cells).map(c => c.textContent.trim());
                    if (celdas.length <= iTit) continue;
                    const k = celdas.join('|');
                    if (vistas.has(k)) continue;
                    vistas.add(k);
                    nuevas++;
                    const crudo = celdas[iTit];
                    const truncado = /\.\.\.\s*$/.test(crudo);
                    const tit = norm(truncado ? crudo.replace(/[.\s]+$/, '') : crudo);
                    if (tit === clave || (truncado && tit.length >= 25 && clave.startsWith(tit))) {
                        const ed = f.querySelector('a[href*="action=Editar"]');
                        return {anio: iAnio >= 0 ? (parseInt(celdas[iAnio], 10) || 0) : 0,
                                href: ed ? ed.getAttribute('href') : ''};
                    }
                }
                if (!nuevas) return null;
            }
            return null;
        }""", [clave, "3997137" if reg["tipo"] == "articulo" else "8106305"])
    if r == "sin-tabla":
        # sin la tabla no se puede afirmar nada, y un 'no esta' falso
        # terminaria en un duplicado
        raise RuntimeError("no encontré la tabla de la lista: ¿cambió el HTML de SIGEVA?")
    return r or None


def anio_en_lista(page, reg: dict) -> int | None:
    fila = buscar_en_lista(page, reg)
    return fila["anio"] if fila else None


def aparece_en_lista(page, reg: dict) -> bool:
    return buscar_en_lista(page, reg) is not None


def fechas_guardadas(page, href: str, nombres: list) -> dict:
    """Lee las fechas de un registro ya guardado, abriendolo en modo Editar.

    Solo lee: trae la pagina con fetch y no envia nada.
    """
    return page.evaluate(
        r"""async ([href, nombres]) => {
            const dec = new TextDecoder('iso-8859-1');
            const r = await fetch(href, {credentials: 'same-origin'});
            const doc = new DOMParser().parseFromString(dec.decode(await r.arrayBuffer()), 'text/html');
            const out = {};
            for (const n of nombres) out[n] = Array.from(doc.getElementsByName(n)).map(e => e.value);
            return out;
        }""", [href, nombres])


def inyectar_autores(page, reg: dict, cat) -> list:
    """Carga autores y filiaciones inyectando las filas ocultas del formulario.

    SIGEVA arma las filiaciones navegando tres pantallas por autor. Pero al
    enviar el formulario solo mira un puñado de inputs ocultos, asi que se los
    puede escribir directamente: cero recargas de pagina por autor. La idea sale
    de la extension SIGEVA-JSON (github.com/indirivacua/SIGEVA-JSON).

    Si la institucion esta en el catalogo se usa su ID; si no, se carga como
    "otra organizacion" con el nombre real. Nunca se inventa una institucion.
    """
    avisos = []
    from catalogo import BASURA
    datos = []
    for a in reg["autores"]:
        cruda = (a.get("institucion") or "").strip()
        # OpenAlex a veces devuelve cualquier cosa ("FC Barcelona"): antes de
        # escribir un dato falso en una DDJJ, mejor dejarlo sin informar. Lo
        # que viene de datos-manuales.json con "verificada" ya lo miro alguien
        # (Vint Cerf si es de Google)
        if cruda and BASURA.match(cruda) and not a.get("verificada"):
            cruda = ""
        a = {**a, "institucion": cruda}
        inst = cat.institucion(cruda)
        datos.append({
            "nombre": a_latin1(f"{a['apellido']}, {a['nombre']}".strip(", ")),
            "propio": CFG.es_declarante(a["apellido"]),
            "label": (inst or {}).get("label") or (a.get("institucion") or "").strip(),
            "id": (inst or {}).get("id", ""),
            "paisId": "",
        })

    sin_catalogo = sum(1 for d in datos if d["label"] and not d["id"])
    sin_dato = sum(1 for d in datos if not d["label"])
    for d in datos:
        if not d["label"]:
            d["label"] = PLACEHOLDER_INSTITUCION

    resultado = page.evaluate(
        """([autores, tipoInternacional, personaId]) => {
            const filas = () => document.getElementsByName('autorParticipacionLabel');
            const nuevo = document.getElementsByName('autorNuevo')[0];
            while (filas().length < autores.length && nuevo) nuevo.click();

            const oculto = (n, v) =>
                `<input type="hidden" name="${n}" value="${String(v).replace(/"/g, '&quot;')}">`;

            autores.forEach((a, i) => {
                const campos = filas();
                if (i >= campos.length) return;
                campos[i].value = a.nombre;
                // Cada autor tiene su tabla anidada: el nombre en el <thead> y
                // las filiaciones en el <tbody>. Al guardar, preSubmit() arma
                // autorJSON leyendo solo ese <tbody>: una fila en otro lugar
                // se ve en pantalla pero no viaja (asi quedaron sin
                // filiaciones los eventos de julio de 2026, con 14.11.20).
                const tabla = campos[i].closest('table');
                if (!tabla) return;
                const cuerpo = tabla.tBodies[0] || tabla.appendChild(document.createElement('tbody'));
                const esOtra = a.id ? 'false' : 'true';
                cuerpo.insertAdjacentHTML('beforeend', `
                    <tr class="odd"><td colspan="2"><div>${a.label}</div>
                    ${oculto('autorOrganizacionLabel', a.label)}
                    ${oculto('autorOrganizacionId', a.id)}
                    ${oculto('autorParticipacionOrganizacionId', '')}
                    ${oculto('autorParticipacionId', '')}
                    ${oculto('autorisOtraOrganizacion', esOtra)}
                    ${oculto('autorPaisId', a.paisId)}
                    ${oculto('autorProvinciaId', '')}
                    ${oculto('autorRelacionadaId', '')}
                    ${oculto('autorNivel', '')}
                    ${oculto('autorRuta', a.label)}
                    ${oculto('autorTipoId', a.id ? '' : tipoInternacional)}
                    ${oculto('autorAffiliationId', '')}
                    </td><td><input type="button" name="autorOrganizacionBorrar"
                       value="Borrar" class="borrar"></td></tr>`);
            });

            // el declarante: hasta 14.11.20 era un radio (autorSel); desde
            // 14.11.24.5 es el autor con autorPersonaId = id de persona
            const idx = autores.findIndex(a => a.propio);
            let marcado = false;
            if (idx >= 0) {
                const radios = document.getElementsByName('autorSel');
                const personas = document.getElementsByName('autorPersonaId');
                if (radios[idx]) {
                    radios[idx].checked = true;
                    radios[idx].dispatchEvent(new Event('change', {bubbles: true}));
                    marcado = true;
                } else if (personas[idx] && personaId) {
                    personas[idx].value = personaId;
                    marcado = true;
                }
            }
            return {filas: filas().length, declarante: idx, marcado};
        }""", [datos, TIPO_INTERNACIONAL, CFG.PERSONA_ID])

    if resultado["declarante"] < 0:
        avisos.append(f"no encontré a {CFG.CONF['apellido']} entre los autores")
    elif not resultado["marcado"]:
        avisos.append("no pude marcar al declarante (¿falta sigeva.persona_id en config.json?)")
    if resultado["filas"] < len(datos):
        avisos.append(f"entraron {resultado['filas']} de {len(datos)} autores")
    if sin_catalogo:
        avisos.append(f"{sin_catalogo} instituciones cargadas como 'otra'")
    if sin_dato:
        avisos.append(f"{sin_dato} autores con institución '{PLACEHOLDER_INSTITUCION}'")
    return avisos


def cargar_articulo_manual(page, reg: dict) -> list:
    """Alta de articulo sin precarga: por 'Omitir'. Es la via confiable."""
    # "Omitir" pasa por el mismo servlet lento que la precarga y a veces no
    # devuelve la pantalla: se reintenta en vez de perder el registro
    for intento in range(1, 6):
        page.goto(URL_NUEVO_ARTICULO, wait_until="domcontentloaded")
        try:
            page.wait_for_selector('input[type="submit"][value="Omitir"]',
                                   state="attached", timeout=20_000)
            page.click('input[type="submit"][value="Omitir"]')
            page.wait_for_selector('input[name="bissn"]', state="attached",
                                   timeout=45_000)
            break
        except PWTimeout:
            if intento == 5:
                raise RuntimeError("SIGEVA no respondió al abrir el alta "
                                   "(el servidor está lento; probá más tarde)")
            log(f"    SIGEVA no respondió, reintento {intento + 1}/5")
            page.wait_for_timeout(8_000)

    cat = Catalogo()
    rev = cat.revista(reg.get("venue_oficial") or reg.get("venue") or "",
                      reg.get("issn", ""))
    if rev:
        # con el ID del catalogo se saltean las dos pantallas del buscador
        page.evaluate(
            "([id, label]) => {"
            "  const p = document.querySelector('[name=publicacionId]');"
            "  if (p) p.value = id;"
            "  const s = document.querySelector('textarea[name=srevista]');"
            "  if (s) s.value = label;"
            "}", [rev["id"], rev["label"]])
        avisos = []
    else:
        avisos = elegir_revista(page, reg)

    editorial, pais = editorial_y_pais(reg)
    if editorial:
        page.fill('input[name="editorial"]', editorial)
    else:
        avisos.append("editorial sin deducir")
    if pais:
        try:
            page.select_option('select[name="pais"]', label=pais)
        except Exception:
            avisos.append(f"país '{pais}' no está en la lista")
    else:
        avisos.append("país de edición sin deducir")

    page.fill('input[name="produccion"]', limpiar_titulo(reg["titulo"]))
    enlace = reg.get("url") or (f"https://doi.org/{reg['doi']}" if reg.get("doi") else "")
    # SIGEVA exige URL o DOI si el soporte es electronico
    soportes = page.locator('input[name="tipoSoporteChecked"]')
    if soportes.count() > 1 and not enlace:
        if soportes.nth(1).is_checked():
            soportes.nth(1).uncheck()
        if not soportes.nth(0).is_checked():
            soportes.nth(0).check()
        avisos.append("sin URL ni DOI: se declara sólo impreso")
    for campo, valor in (("volumen", reg.get("volumen")),
                         ("numero", reg.get("numero")),
                         ("web", enlace[:250]),
                         ("doi", reg.get("doi"))):
        if valor:
            page.fill(f'input[name="{campo}"]', str(valor))
    paginas = re.match(r"\s*(\d+)\s*-\s*(\d+)", reg.get("paginas") or "")
    if paginas:
        page.fill('input[name="paginaInicial"]', paginas.group(1))
        page.fill('input[name="paginaFinal"]', paginas.group(2))
    # la fecha la escribe fijar_fechas al final: escribirla aca no sirve,
    # el datepicker la pisa (ver fijar_fechas)
    if not reg.get("fecha_publicacion"):
        avisos.append("sin fecha de publicación")
    elif reg.get("fecha_aproximada"):
        avisos.append("mes de publicación estimado")

    page.check('input[name="tipoReferato"][value="2"]')      # con referato
    page.check('input[name="publicado"][value="1"]')         # publicado
    soportes = page.locator('input[name="tipoSoporteChecked"]')
    if soportes.count() > 1 and not soportes.nth(1).is_checked():
        soportes.nth(1).check()                              # electronico/digital

    avisos += asegurar_editorial(page, reg)
    if falta_en_catalogo(reg, cat):
        # alta real de las instituciones que faltan: mas lento pero es la unica
        # forma de que SIGEVA las cree
        avisos.append("instituciones nuevas: uso el alta real (más lento)")
        avisos += cargar_autores(page, reg)
    else:
        avisos += inyectar_autores(page, reg, cat)
    avisos += fijar_soporte(page, reg)
    avisos += completar_comunes(page, reg, con_adjunto=True)
    return avisos


def cargar_evento(page, reg: dict) -> list:
    sede = sede_evento(reg)
    if not sede["pais"]:
        raise RuntimeError("no pude deducir el país del evento desde el booktitle")

    page.goto(URL_NUEVO_EVENTO, wait_until="domcontentloaded")
    page.select_option('select[name="tipoTrabajo"]', label="Artículo Completo")
    page.fill('input[name="produccion"]', limpiar_titulo(reg["titulo"]))
    page.select_option('select[name="tipoPublicacion"]', label="Libro")
    page.fill('input[name="tituloPublicacion"]', reg["venue"][:250])
    # SIGEVA valida el formato: un ISSN en el campo ISBN lo rechaza
    ident = (reg.get("isbn") or "").strip()
    if re.fullmatch(r"[\d\-]{10,17}[\dXx]?", ident or ""):
        page.fill('input[name="issnIsbn"]', ident)
    page.select_option('select[name="paisEdicion"]', label=sede["pais"])
    page.fill('input[name="lugarPublicacion"]', sede["ciudad"])
    editorial, _ = editorial_y_pais(reg)
    page.fill('input[name="editorial"]', editorial or reg.get("editorial") or "")
    # anioPublica y fechaReunion las escribe fijar_fechas al final (ver ahi)
    evento = re.split(r",\s*\d{1,2}\s+\w+\s+\d{4}", reg["venue"])[0]
    page.fill('input[name="reunionCientifica"]', evento[:250])
    page.select_option('select[name="tipoReunion"]', label=tipo_reunion_de(reg))
    page.check('input[name="alcanceInternacional"]')
    page.select_option('select[name="paisEvento"]', label=sede["pais"])
    page.fill('input[name="lugarReunion"]', sede["ciudad"])

    # el soporte es obligatorio, y si se marca "electronico" SIGEVA exige la URL
    enlace = reg.get("url") or (f"https://doi.org/{reg['doi']}" if reg.get("doi") else "")
    soportes = page.locator('input[name="tipoSoporteChecked"]')
    if soportes.count() > 1:
        if enlace:
            if not soportes.nth(1).is_checked():
                soportes.nth(1).check()                  # electronico/digital
            page.fill('input[name="web"]', enlace[:250])
        elif not soportes.nth(0).is_checked():
            soportes.nth(0).check()                      # impreso, sin URL que dar

    avisos = asegurar_editorial(page, reg)
    cat = Catalogo()
    if falta_en_catalogo(reg, cat):
        # igual que en articulos: inyectar una "otra" sin ID no persiste, hay
        # que pasar por el alta real para que SIGEVA cree la institucion
        avisos.append("instituciones nuevas: uso el alta real (más lento)")
        avisos += cargar_autores(page, reg)
    else:
        avisos += inyectar_autores(page, reg, cat)
    avisos += fijar_soporte(page, reg)
    avisos += completar_comunes(page, reg, con_adjunto=True)
    return avisos


# ---------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="llena y captura, no guarda")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--paso-a-paso", action="store_true", help="confirma cada guardado")
    p.add_argument("--tipo", choices=["articulo", "evento"], default=None)
    p.add_argument("--desde", type=int, default=None)
    p.add_argument("--con-pdf", action="store_true",
                   help="sólo los registros que tienen full text: sin archivo "
                        "SIGEVA no guarda")
    p.add_argument("--perfil-limpio", action="store_true",
                   help="usa un contexto nuevo (tipo incógnito) en vez del perfil "
                        "guardado: evita el estado de sesión que traba a SIGEVA")
    p.add_argument("--via", choices=["manual", "precarga", "auto"], default="manual",
                   help="manual = por Omitir (confiable); precarga = por DOI "
                        "(rapida pero intermitente); auto = precarga y si falla, manual")
    a = p.parse_args()

    datos = json.loads((AQUI / "faltantes-enriquecidos.json").read_text(encoding="utf-8"))
    cola = [r for r in datos
            if r["tipo"] in ("articulo", "evento")
            and (not a.tipo or r["tipo"] == a.tipo)
            and (not a.desde or (r["anio"] or 0) >= a.desde)
            and not ya_cargado(r["clave"])
            and (not a.con_pdf or (r.get("pdf") and Path(r["pdf"]).exists()))
            and not r.get("excluir")
            and not r.get("en_prensa")]
    en_prensa = sum(1 for r in datos if r.get("en_prensa") and not ya_cargado(r["clave"]))
    if en_prensa:
        log(f"{en_prensa} en prensa ('to appear' en el .bib): quedan para cuando salgan")
    # los articulos con DOI son los mas baratos y los que mas pesan: primero
    cola.sort(key=lambda r: (r["tipo"] != "articulo", not r["doi"], -(r["anio"] or 0)))
    if a.limit:
        cola = cola[:a.limit]

    if not cola:
        sys.exit("No hay nada pendiente con esos filtros.")
    log(f"{len(cola)} registros en cola. Modo: "
        f"{'DRY-RUN (no guarda)' if a.dry_run else 'CARGA REAL'}")
    CAPTURAS.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        if a.perfil_limpio:
            # SIGEVA se traba con estado de sesión acumulado; varios usuarios
            # reportan que sólo funciona en ventana de incógnito
            navegador = pw.chromium.launch(headless=False)
            ctx = navegador.new_context(viewport={"width": 1400, "height": 1000})
        else:
            ctx = pw.chromium.launch_persistent_context(
                str(PERFIL), headless=False, viewport={"width": 1400, "height": 1000},
                accept_downloads=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        esperar_login(page)
        entrar_banco_datos(page)

        ok = fallos = 0
        for i, reg in enumerate(cola, 1):
            etiqueta = f"{reg['anio']} {reg['titulo'][:56]}"
            log(f"({i}/{len(cola)}) [{reg['tipo']}] {etiqueta}")
            if i > 1:
                page.wait_for_timeout(PAUSA_ENTRE_REGISTROS)

            if not sesion_viva(page):
                log("    la sesión expiró, reingresando")
                try:
                    esperar_login(page)
                    entrar_banco_datos(page)
                except SystemExit:
                    registrar({"clave": reg["clave"], "resultado": "sesion-expirada"})
                    break
                if not sesion_viva(page):
                    registrar({"clave": reg["clave"], "resultado": "sesion-expirada"})
                    break

            # estado.json solo sabe lo que cargo este script. Lo cargado a mano,
            # o un Guardar que tiro LockAcquisitionException pero entro igual,
            # se ve recien en la lista
            try:
                ya_esta = aparece_en_lista(page, reg)
            except Exception as e:
                log(f"    no pude revisar la lista ({str(e)[:120]}); corto acá")
                break
            if ya_esta:
                log("    ya está en SIGEVA, lo salteo")
                registrar({"clave": reg["clave"], "titulo": reg["titulo"],
                           "resultado": "ya-estaba"})
                continue
            try:
                if reg["tipo"] != "articulo":
                    avisos = cargar_evento(page, reg)
                elif a.via == "manual" or not reg["doi"]:
                    avisos = cargar_articulo_manual(page, reg)
                elif a.via == "precarga":
                    avisos = cargar_articulo(page, reg)
                else:
                    try:
                        avisos = cargar_articulo(page, reg)
                    except Exception as e:
                        log(f"    precarga falló ({e}); voy por la vía manual")
                        avisos = cargar_articulo_manual(page, reg)
                        avisos.append("cargado por vía manual")
                # al final, cuando ya nada re-renderiza el formulario
                esperadas = fechas_de(page, reg)
                fijar_fechas(page, esperadas)
            except Exception as e:
                detalle = re.sub(r"\s+", " ", str(e))[:400]
                log(f"    NO SE PUDO: {detalle[:160]}")
                try:
                    page.screenshot(
                        path=str(CAPTURAS / f"error-{reg['clave'][:36].replace('/', '_')}.png"),
                        full_page=True)
                except Exception:
                    pass
                registrar({"clave": reg["clave"], "titulo": reg["titulo"],
                           "resultado": "error", "detalle": detalle[:300]})
                fallos += 1
                continue

            if avisos:
                log("    avisos: " + ", ".join(avisos))

            captura = CAPTURAS / f"{reg['tipo']}-{reg['clave'][:40].replace('/', '_')}.png"
            page.screenshot(path=str(captura), full_page=True)

            if a.dry_run:
                registrar({"clave": reg["clave"], "titulo": reg["titulo"],
                           "resultado": "dry-run", "avisos": avisos,
                           "captura": captura.name})
                ok += 1
                try:            # libera el formulario en el servidor
                    page.click('input[type="submit"][value="Volver"]', timeout=10_000)
                except Exception:
                    pass
                continue

            if a.paso_a_paso:
                r = input("    ¿Guardar? [s/N/q] ").strip().lower()
                if r == "q":
                    break
                if r != "s":
                    registrar({"clave": reg["clave"], "resultado": "omitido"})
                    continue

            # el boton abre un popup de upload: no hay que esperar navegacion
            try:
                page.click('input[type="submit"][value="Guardar"]', no_wait_after=True)
                page.wait_for_load_state("networkidle", timeout=45_000)
            except Exception:
                pass
            try:
                cuerpo = page.inner_text("body")
            except Exception:
                # el popup de upload puede dejar la pagina ilegible un momento;
                # lo que importa es si el registro quedo, asi que se verifica
                page.wait_for_timeout(3_000)
                try:
                    cuerpo = page.inner_text("body")
                except Exception:
                    cuerpo = ""
            # SIGEVA usa varios verbos: ingresar, seleccionar, completar,
            # adjuntar, especificar. Antes se escapaban dos y el guardado
            # fallido se reportaba como exitoso.
            error = re.search(r"(debe [a-záéíóú]+[^\n]{0,130})", cuerpo, re.I)
            if error and reg.get("pdf") and Path(reg["pdf"]).exists() \
                    and re.search(r"seleccione nuevamente el archivo", cuerpo, re.I):
                # SIGEVA limpia el input de archivo al re-renderizar: se vuelve
                # a adjuntar y se guarda otra vez
                log("    re-adjuntando el archivo y reintentando")
                try:
                    page.set_input_files('input[name="theFile"]', reg["pdf"])
                    # el re-render tambien pisa las fechas: hay que reponerlas
                    fijar_fechas(page, esperadas)
                    page.click('input[type="submit"][value="Guardar"]')
                    page.wait_for_load_state("networkidle", timeout=45_000)
                except Exception:
                    pass
                cuerpo = page.inner_text("body")
                error = re.search(r"(debe [a-záéíóú]+[^\n]{0,130})", cuerpo, re.I)

            if error:
                log(f"    RECHAZADO: {error.group(1)}")
                page.screenshot(path=str(CAPTURAS / f"rechazo-{reg['clave'][:40]}.png"),
                                full_page=True)
                registrar({"clave": reg["clave"], "titulo": reg["titulo"],
                           "resultado": "rechazado", "detalle": error.group(1)})
                fallos += 1
                continue

            # No alcanza con "no hubo mensaje de error": esto es una declaracion
            # jurada y un 'guardado' falso haria que el registro se saltee para
            # siempre. Se confirma yendo a buscarlo a la lista.
            fila = confirmar_guardado(page, reg)
            anio = fila["anio"] if fila else None
            if anio is None:
                log("    NO QUEDÓ GUARDADO (no aparece en la lista)")
                page.screenshot(path=str(CAPTURAS / f"no-guardo-{reg['clave'][:36].replace('/', '_')}.png"),
                                full_page=True)
                registrar({"clave": reg["clave"], "titulo": reg["titulo"],
                           "resultado": "no-guardado",
                           "detalle": "sin error visible, pero no figura en la lista"})
                fallos += 1
                continue
            # y con el año correcto: en julio de 2026 se guardaron 70 registros
            # con la fecha del dia sin que nada lo avisara
            if anio != anio_esperado(reg):
                log(f"    GUARDADO CON EL AÑO MAL: la lista dice {anio}, "
                    f"tenía que decir {anio_esperado(reg)}. Corto la tanda.")
                registrar({"clave": reg["clave"], "titulo": reg["titulo"],
                           "tipo": reg["tipo"], "resultado": "guardado-fecha-mal",
                           "detalle": f"lista {anio}, esperado {anio_esperado(reg)}"})
                fallos += 1
                break
            # el año de la lista no distingue un 07/2026 de un 09/2026: se abre
            # el registro y se comparan las fechas una por una
            guardadas = fechas_guardadas(page, fila["href"], list(esperadas)) if fila["href"] else {}
            distintas = {k: v for k, v in guardadas.items()
                         if any(x != esperadas[k] for x in v) or not v}
            if not fila["href"] or distintas:
                log(f"    GUARDADO CON FECHAS MAL: {distintas or 'no pude abrirlo'}, "
                    f"esperaba {esperadas}. Corto la tanda.")
                registrar({"clave": reg["clave"], "titulo": reg["titulo"],
                           "tipo": reg["tipo"], "resultado": "guardado-fecha-mal",
                           "detalle": f"guardado {distintas}, esperado {esperadas}"})
                fallos += 1
                break

            registrar({"clave": reg["clave"], "titulo": reg["titulo"],
                       "tipo": reg["tipo"], "resultado": "guardado",
                       "avisos": avisos, "verificado": True})
            ok += 1
            log("    guardado y verificado en la lista")

        log(f"Listo. {ok} ok, {fallos} con problemas. Detalle en estado.json")
        if not a.dry_run:
            # foto final de lo que quedo, en la misma sesion: sirve de control
            # y deja inventario.json al dia para el proximo diff
            try:
                import inventariar
                inventariar.actualizar(page)
            except Exception as e:
                log(f"No pude releer la lista: {str(e).splitlines()[0][:100]}")
        ctx.close()


if __name__ == "__main__":
    main()
