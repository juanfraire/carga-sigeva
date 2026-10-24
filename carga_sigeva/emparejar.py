#!/usr/bin/env python3
"""
emparejar.py -- asocia cada faltante con su PDF y le extrae el resumen

Fuentes de PDF (dos convenciones de nombre distintas, ninguna coincide con las
claves del .bib):
  A) proyects/0000-00-informes/informe-investigador-cic/papers-2025/
     nombrados <apellido><anio><primerapalabra>.pdf  -> se reconstruye la clave
  B) unc/0000-00-papers/
     nombrados <ANIO>-<Venue>-<Tema>.pdf             -> se matchea anio + venue

El resumen sale del propio PDF (pdftotext) y se normaliza antes de escribirlo:
el Instructivo del CONICET avisa que pegar abstracts desde PDF mete caracteres
rotos, asi que se limpian ligaduras, guiones de corte y espacios.

Uso:
    python3 emparejar.py            # escribe faltantes-enriquecidos.json
    python3 emparejar.py --informe  # solo muestra cobertura, no escribe
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
import urllib.parse
from pathlib import Path

import config as CFG

AQUI = CFG.DATOS_DIR
# carpetas donde buscar los PDF, en el orden de config.json
CARPETAS = CFG.CARPETAS_PDF

VACIAS = {"a", "an", "the", "on", "of", "for", "in", "to", "and", "with", "toward",
          "towards", "from", "at", "by", "is", "are", "la", "el", "de", "del", "un"}


def sinacentos(s: str) -> str:
    # la i turca sin punto no se descompone en NFKD: "Yanıkömeroğlu" quedaba
    # sin cruzar con el "Yanikomeroglu" del .bib
    s = unicodedata.normalize("NFKD", s.lower().replace("ı", "i"))
    return "".join(c for c in s if not unicodedata.combining(c))


def clave_scholar(reg: dict) -> str:
    """Reconstruye la convencion <apellido><anio><primerapalabra>."""
    if not reg["autores"]:
        return ""
    apellido = re.sub(r"[^a-z]", "", sinacentos(reg["autores"][0]["apellido"]))
    palabras = [re.sub(r"[^a-z0-9]", "", sinacentos(p))
                for p in reg["titulo"].split()]
    palabras = [p for p in palabras if p and p not in VACIAS]
    return f"{apellido}{reg['anio']}{palabras[0]}" if palabras else ""


def fichas_por_anio_venue() -> list:
    """PDFs nombrados <ANIO>-<Venue>-<Tema>.pdf, en todas las carpetas."""
    fichas = []
    for carpeta in CARPETAS:
        if not carpeta.is_dir():
            continue
        for p in sorted(carpeta.glob("*.pdf")):
            m = re.match(r"((?:19|20)\d{2})-([^-]+)-?(.*)\.pdf$", p.name)
            if not m:
                continue
            fichas.append({"anio": int(m.group(1)),
                           "venue": sinacentos(m.group(2)),
                           "tema": sinacentos(m.group(3)),
                           "ruta": p})
    return fichas


def tokens(s: str) -> set:
    return {t for t in re.findall(r"[a-z]{3,}", sinacentos(s)) if t not in VACIAS}


# puntaje minimo para aceptar un match del corpus unc/. Adjuntar el PDF
# equivocado es peor que no adjuntar ninguno: el umbral es deliberadamente alto.
UMBRAL_UNC = 1.2


def emparejar_por_nombre(faltantes: list, unc: list) -> dict:
    """Asignacion uno a uno entre faltantes y PDFs, por rareza de termino.

    Un token que aparece en muchos nombres de archivo ('ieee', 'satellite',
    'routing') casi no discrimina; uno raro ('phantomlink', 'ulloriaq') es casi
    una firma. El puntaje suma 1/frecuencia por token compartido.
    """
    df = {}
    for f in unc:
        for t in tokens(f["tema"]) | tokens(f["venue"]):
            df[t] = df.get(t, 0) + 1

    pares = []
    for i, r in enumerate(faltantes):
        tt = tokens(r["titulo"])
        for j, f in enumerate(unc):
            if f["anio"] != (r["anio"] or 0):      # el anio del archivo es el de publicacion
                continue
            comunes = (tokens(f["tema"]) | tokens(f["venue"])) & tt
            if len(comunes) < 2:
                continue
            pts = sum(1.0 / df[t] for t in comunes)
            if pts >= UMBRAL_UNC:
                pares.append((pts, len(comunes), i, j))

    pares.sort(reverse=True)
    asignado_reg, asignado_pdf, salida = set(), set(), {}
    for pts, n, i, j in pares:
        if i in asignado_reg or j in asignado_pdf:
            continue
        asignado_reg.add(i)
        asignado_pdf.add(j)
        salida[i] = (unc[j]["ruta"], "media" if pts >= 2.0 else "baja")
    return salida


# ------------------------------------------------------------------- resumenes

CORTES = re.compile(
    r"\b(index terms|keywords|key words|palabras clave|i\.\s*introduction|"
    r"1\.\s*introduction|introduction\b)", re.I)


def limpiar_texto(s: str) -> str:
    """Normaliza lo que sale del PDF: ligaduras, cortes de linea, comillas."""
    reemplazos = {
        "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
        "ﬄ": "ffl", "‘": "'", "’": "'", "“": '"',
        "”": '"', "–": "-", "—": "-", "−": "-",
        " ": " ", " ": " ", " ": " ", "﻿": "",
    }
    for a, b in reemplazos.items():
        s = s.replace(a, b)
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)      # palabra cortada al final
    s = re.sub(r"\s*\n\s*", " ", s)
    s = "".join(c for c in s if c == "\n" or unicodedata.category(c)[0] != "C")
    return re.sub(r"\s{2,}", " ", s).strip()


CACHE = AQUI / "cache-crossref.json"


def resumen_crossref(doi: str, cache: dict) -> str:
    """Abstract publico desde la API de Crossref (viene en JATS-XML)."""
    if not doi:
        return ""
    if doi in cache:
        return cache[doi]
    import urllib.request
    import urllib.error
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": CFG.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            datos = json.load(r)
        crudo = datos.get("message", {}).get("abstract", "") or ""
    except Exception:
        crudo = ""
    if crudo:
        crudo = re.sub(r"<[^>]+>", " ", crudo)                   # saca el JATS
        crudo = re.sub(r"^\s*(abstract|resumen)\b[\s:.-]*", "", crudo, flags=re.I)
        crudo = limpiar_texto(crudo)
    cache[doi] = crudo
    return crudo


def clave_apellido(nombre: str) -> str:
    """Ultima palabra significativa del nombre, normalizada, para cruzar autores."""
    # el guion tambien separa: "Karabulut-Kurt" y "Karabulut Kurt" son el mismo
    partes = [p for p in re.split(r"[\s,\-]+", sinacentos(nombre)) if len(p) > 1]
    return re.sub(r"[^a-z]", "", partes[-1]) if partes else ""


PAIS_EN_TEXTO = {
    "argentina": "AR", "usa": "US", "united states": "US", "germany": "DE",
    "spain": "ES", "france": "FR", "italy": "IT", "china": "CN", "chile": "CL",
    "brazil": "BR", "netherlands": "NL", "belgium": "BE", "switzerland": "CH",
    "united kingdom": "GB", "canada": "CA", "japan": "JP", "india": "IN",
}


def pais_del_texto(texto: str) -> str:
    """El pais suele venir dentro de la filiacion cruda.

    A veces al final ('...,Dresden,Germany') y a veces en el medio, seguido de
    codigo postal ('D3TN U.S. Corp., Florida,Miami,FL,USA,33131').
    """
    limpio = sinacentos(re.sub(r"&#x[0-9A-Fa-f]+;", " ", texto or ""))
    for nombre, iso in PAIS_EN_TEXTO.items():
        if re.search(r"(^|[,\s])" + re.escape(nombre) + r"($|[,\s.])", limpio):
            return iso
    return ""


def limpiar_institucion(nombre: str) -> str:
    """Deja solo el nombre de la institucion, sin la direccion postal.

    OpenAlex a veces devuelve la filiacion cruda entera: nombre, ciudad,
    estado, pais y codigo postal. SIGEVA quiere el nombre.
    """
    import html
    nombre = html.unescape(nombre or "").strip()
    partes = [p.strip() for p in nombre.split(",") if p.strip()]
    if len(partes) <= 1:
        return nombre
    # Si el resto son ciudad/estado/pais/codigo postal, alcanza con el primer
    # tramo: es el nombre de la institucion. Si no, se conservan los que no
    # parezcan direccion (algunos nombres llevan coma propia).
    cola = " ".join(partes[1:])
    if pais_del_texto(cola) or re.search(r"\d{4}", cola):
        return partes[0]
    return ", ".join(partes[:2])


def aplicar_afiliaciones(reg: dict, afiliaciones: dict) -> None:
    """afiliaciones viene indexado por el nombre del autor en OpenAlex.

    La clave de cruce se calcula aca y no al guardar en el cache: si cambia la
    normalizacion (paso con la i turca de "Yanıkömeroğlu"), un cache viejo
    seguia sin cruzar.
    """
    por_apellido = {clave_apellido(k): v for k, v in afiliaciones.items()}
    for a in reg.get("autores", []):
        d = por_apellido.get(clave_apellido(a["apellido"])) or {}
        crudo = d.get("institucion", "")
        a["institucion"] = limpiar_institucion(crudo)
        a["pais_institucion"] = d.get("pais", "") or pais_del_texto(crudo)


def _crossref(doi: str, cache: dict) -> dict:
    """Lo que interesa de /works/{doi}: sede del evento y fechas."""
    clave = "cr:" + doi
    if clave not in cache:
        try:
            m = _pedir("https://api.crossref.org/works/"
                       + urllib.parse.quote(doi)).get("message") or {}
        except Exception:
            m = {}
        cache[clave] = {
            "lugar": (m.get("event") or {}).get("location") or "",
            "fechas": [(m.get(k) or {}).get("date-parts", [[None]])[0]
                       for k in ("published-online", "published-print", "created")],
        }
    return cache[clave]


def sede_crossref(reg: dict, cache: dict) -> str:
    """Sede del congreso segun Crossref (campo event.location)."""
    if reg["tipo"] != "evento" or not reg.get("doi"):
        return ""
    return _crossref(reg["doi"], cache)["lugar"]


def fecha_crossref(reg: dict, cache: dict) -> str:
    """mm/aaaa de la primera publicacion segun Crossref.

    OpenAlex devuelve AAAA-01-01 cuando solo conoce el año, y eso se cargaba
    como enero. Crossref suele tener el mes en published-online o
    published-print, y si no en created (alta del DOI), que en IEEE coincide
    con la "Date of publication" del early access. Se toma la mas temprana
    que traiga mes.
    """
    if not reg.get("doi"):
        return ""
    con_mes = [tuple(f[:2]) for f in _crossref(reg["doi"], cache)["fechas"]
               if f and len(f) >= 2 and f[0] and f[1]]
    if not con_mes:
        return ""
    anio, mes = min(con_mes)
    return f"{mes:02d}/{anio}"


def _pedir(url: str) -> dict:
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": CFG.USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def mismo_titulo(a: str, b: str, umbral: float = 0.9) -> bool:
    from difflib import SequenceMatcher
    na, nb = (re.sub(r"[^a-z0-9]", "", sinacentos(x)) for x in (a, b))
    return bool(na and nb) and SequenceMatcher(None, na, nb).ratio() >= umbral


def resumen_openalex(reg: dict, cache: dict) -> str:
    """Abstract desde OpenAlex. Viene como indice invertido {palabra: [pos]}.

    Cubre mucho mas que Crossref porque IEEE no deposita abstracts ahi. Busca
    por DOI y, si no hay, por titulo exacto.
    """
    # oa5: afiliaciones por nombre (ver aplicar_afiliaciones). Las busquedas
    # por titulo llevan prefijo propio: las de antes de verificar el titulo
    # pueden ser de otro trabajo y no hay que reusarlas
    clave = "oa5:" + reg["doi"] if reg["doi"] else "oa6t:" + reg["titulo_clave"]
    if clave in cache:
        d = cache[clave]
        reg["fecha_publicacion"] = d.get("fecha", "")
        reg["issn"] = reg.get("issn") or d.get("issn", "")
        reg["venue_oficial"] = d.get("venue", "")
        aplicar_afiliaciones(reg, d.get("afiliaciones", {}))
        return d.get("resumen", "")
    datos = None
    try:
        if reg["doi"]:
            datos = _pedir(f"https://api.openalex.org/works/doi:{urllib.parse.quote(reg['doi'])}")
        else:
            q = urllib.parse.quote(reg["titulo"][:180])
            res = _pedir(f"https://api.openalex.org/works?filter=title.search:{q}&per-page=1")
            datos = (res.get("results") or [None])[0]
            # la busqueda por titulo devuelve el mas parecido, que puede ser
            # otro trabajo: sin esto un paper se queda con el resumen, la fecha
            # y las filiaciones de uno ajeno
            if datos and not mismo_titulo(reg["titulo"], datos.get("display_name") or ""):
                datos = None
    except Exception:
        datos = None

    texto = ""
    idx = (datos or {}).get("abstract_inverted_index")
    if idx:
        posiciones = {}
        for palabra, ps in idx.items():
            for p in ps:
                posiciones[p] = palabra
        texto = limpiar_texto(" ".join(posiciones[k] for k in sorted(posiciones)))
        texto = re.sub(r"^\s*(abstract|resumen)\b[\s:.-]*", "", texto, flags=re.I)
        # HAL rellena con esto cuando el deposito no trae abstract real, y el
        # repositorio del CONICET con las lineas de filiacion ("Fil: Perez,
        # Juan. Universidad...")
        if re.fullmatch(r"(inter)?national audience\.?", texto.strip(), re.I) \
                or re.match(r"Fil:", texto.strip()):
            texto = ""
    # la fecha sirve para el campo mm/aaaa de SIGEVA, que es obligatorio
    fecha = ""
    m = re.match(r"(\d{4})-(\d{2})", (datos or {}).get("publication_date", "") or "")
    if m:
        fecha = f"{m.group(2)}/{m.group(1)}"
    # el ISSN permite elegir la revista en SIGEVA sin depender del importador
    fuente = ((datos or {}).get("primary_location") or {}).get("source") or {}
    issns = fuente.get("issn") or []
    issn = (fuente.get("issn_l") or (issns[0] if issns else "")) or ""
    venue = fuente.get("display_name") or ""
    # afiliacion de cada coautor: SIGEVA exige institucion para todos
    afiliaciones = {}
    for a in (datos or {}).get("authorships", []) or []:
        nombre = ((a.get("author") or {}).get("display_name") or "").strip()
        if not nombre:
            continue
        inst = (a.get("institutions") or [{}])[0]
        nom_inst = inst.get("display_name") or ""
        if not nom_inst:
            crudas = a.get("raw_affiliation_strings") or []
            nom_inst = crudas[0] if crudas else ""
        if nom_inst:
            afiliaciones[nombre] = {
                "institucion": nom_inst[:120],
                "pais": (inst.get("country_code") or "").upper()}
    cache[clave] = {"resumen": texto, "fecha": fecha, "issn": issn, "venue": venue,
                    "afiliaciones": afiliaciones}
    aplicar_afiliaciones(reg, afiliaciones)
    reg["fecha_publicacion"] = fecha
    reg["issn"] = reg.get("issn") or issn
    reg["venue_oficial"] = venue
    return texto


def extraer_resumen(pdf: Path) -> str:
    try:
        txt = subprocess.run(["pdftotext", "-f", "1", "-l", "2", str(pdf), "-"],
                             capture_output=True, text=True, timeout=25).stdout
    except Exception:
        return ""
    m = re.search(r"\bAbstract\b\s*[—\-:.]?\s*", txt, re.I)
    if not m:
        return ""
    resto = txt[m.end():]
    corte = CORTES.search(resto)
    resumen = limpiar_texto(resto[:corte.start()] if corte else resto[:2500])
    if len(resumen) < 120:
        return ""
    return resumen[:2400].rsplit(".", 1)[0] + "." if len(resumen) > 2400 else resumen


RE_INDEX_TERMS = re.compile(
    r"(?:Index Terms|Keywords|Key words|Mots-cl[ée]s)\s*[—–\-:.]*\s*(.+?)"
    r"(?:\.\s*(?:\n|$)|\n\s*\n|\n\s*(?:I\.|1\.?)\s+[A-Z])", re.S | re.I)


def palabras_clave_pdf(pdf: Path) -> list:
    """Index Terms / Keywords del propio paper, en el orden en que aparecen.

    Con dos columnas pdftotext a veces mete texto de la otra columna en medio
    de la lista: se corta en el primer termino que no parece una palabra clave
    (digitos, corchetes, mas de cinco palabras) en vez de cargar basura. Los
    parentesis si valen: "Deep Reinforcement Learning (DRL)".
    """
    try:
        txt = subprocess.run(["pdftotext", "-l", "2", str(pdf), "-"],
                             capture_output=True, text=True, timeout=25).stdout
    except Exception:
        return []
    m = RE_INDEX_TERMS.search(txt)
    if not m:
        return []
    out = []
    for k in re.split(r"[,;]", m.group(1)):
        k = re.sub(r"\s+", " ", limpiar_texto(k)).strip(" .")
        if not k or re.search(r"[\d\[\]]", k) or len(k.split()) > 5:
            break
        out.append(k)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--informe", action="store_true")
    a = p.parse_args()

    faltantes = json.loads((AQUI / "faltantes.json").read_text(encoding="utf-8"))
    faltantes = [r for r in faltantes if r["tipo"] in ("articulo", "evento",
                                                       "capitulo", "libro")]
    # PDFs nombrados por clave bibtex, en cualquiera de las carpetas
    por_clave = {}
    for carpeta in CARPETAS:
        if carpeta.is_dir():
            por_clave.update({p.stem.lower(): p for p in carpeta.glob("*.pdf")})
    indice_2025 = por_clave
    unc = fichas_por_anio_venue()
    print(f"PDFs disponibles: {len(por_clave)} por clave, {len(unc)} por año+venue\n")

    # 0) lo que ya bajo pdfs_hal.py a pdfs/, nombrado por clave saneada.
    #    Va primero para que re-correr este script no pierda esas rutas.
    bajados = AQUI / "pdfs"
    previos = {f.stem: f for f in bajados.glob("*.pdf")} if bajados.is_dir() else {}

    # 1) por nombre: la clave exacta primero, despues la reconstruccion
    #    <apellido><anio><palabra>. Esa reconstruccion puede dar lo mismo para
    #    dos papers ("Green satellite..." y "Green traffic..." de Liang 2025):
    #    un PDF ya asignado no se vuelve a usar. Dos pasadas, para que una
    #    reconstruccion no se quede con el archivo exacto de otro registro.
    usados = set()
    for r in faltantes:
        saneada = re.sub(r"[^A-Za-z0-9._-]", "_", r["clave"])[:80]
        exacta = previos.get(saneada) or indice_2025.get(r["clave"].lower())
        r["pdf"], r["pdf_confianza"] = (str(exacta), "alta") if exacta else (None, "")
        if exacta:
            usados.add(Path(exacta))
    pendientes = []
    for i, r in enumerate(faltantes):
        if r["pdf"]:
            continue
        k = clave_scholar(r)
        if k and k in indice_2025 and Path(indice_2025[k]) not in usados:
            r["pdf"], r["pdf_confianza"] = str(indice_2025[k]), "alta"
            usados.add(Path(indice_2025[k]))
        else:
            pendientes.append(i)

    # 2) el resto, contra unc/ con asignacion uno a uno
    porunc = emparejar_por_nombre([faltantes[i] for i in pendientes], unc)
    for pos, (ruta, conf) in porunc.items():
        r = faltantes[pendientes[pos]]
        r["pdf"], r["pdf_confianza"] = str(ruta), conf

    # 3) resumen: primero el abstract publico (Crossref), y si no hay, del PDF
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    stats = {"alta": 0, "media": 0, "baja": 0, "": 0}
    fuentes = {"openalex": 0, "crossref": 0, "pdf": 0, "sin": 0}
    for r in faltantes:
        stats[r["pdf_confianza"]] += 1
        r["fecha_publicacion"] = ""
        r["evento_lugar"] = sede_crossref(r, cache)
        r["resumen"] = resumen_openalex(r, cache)
        r["fecha_publicacion"] = fecha_crossref(r, cache) or r["fecha_publicacion"]
        if not r["fecha_publicacion"] and r["anio"]:
            r["fecha_publicacion"] = f"01/{r['anio']}"   # mes desconocido
            r["fecha_aproximada"] = True
        r["resumen_fuente"] = "openalex" if r["resumen"] else ""
        if not r["resumen"]:
            r["resumen"] = resumen_crossref(r["doi"], cache)
            r["resumen_fuente"] = "crossref" if r["resumen"] else ""
        if not r["resumen"] and r["pdf"] and r["pdf_confianza"] in ("alta", "media"):
            r["resumen"] = extraer_resumen(Path(r["pdf"]))
            r["resumen_fuente"] = "pdf" if r["resumen"] else ""
        fuentes[r["resumen_fuente"] or "sin"] += 1
        # las del paper, si estan; si no, cargar.py las deriva del titulo
        r["palabras_clave"] = (palabras_clave_pdf(Path(r["pdf"]))
                               if r["pdf"] and r["pdf_confianza"] == "alta" else [])
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    con_resumen = len(faltantes) - fuentes["sin"]

    print(f"Faltantes: {len(faltantes)}")
    print(f"  PDF confianza alta  : {stats['alta']}")
    print(f"  PDF confianza media : {stats['media']}")
    print(f"  PDF confianza baja  : {stats['baja']}  (revisar)")
    print(f"  sin PDF             : {stats['']}")
    print(f"  con resumen         : {con_resumen}"
          f"  (openalex {fuentes['openalex']}, crossref {fuentes['crossref']},"
          f" pdf {fuentes['pdf']}, sin {fuentes['sin']})\n")

    # los datos completados a mano (datos-manuales.json) pisan lo automático
    manuales = AQUI / "datos-manuales.json"
    if manuales.exists():
        datos_m = json.loads(manuales.read_text(encoding="utf-8"))
        aplicados = 0
        renombres = datos_m.get("_instituciones", {})
        for r in faltantes:
            for autor in r.get("autores", []):
                nuevo = renombres.get(autor.get("institucion"))
                if nuevo:
                    autor["institucion"] = nuevo
            d = datos_m.get(r["clave"])
            if not isinstance(d, dict):
                continue
            for k, v in d.items():
                if not k.startswith("_"):
                    r[k] = v
            aplicados += 1
        print(f"Datos manuales aplicados a {aplicados} registros")

    if not a.informe:
        (AQUI / "faltantes-enriquecidos.json").write_text(
            json.dumps(faltantes, ensure_ascii=False, indent=2), encoding="utf-8")
        print("-> faltantes-enriquecidos.json")


if __name__ == "__main__":
    main()
