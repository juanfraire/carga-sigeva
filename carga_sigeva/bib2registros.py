#!/usr/bin/env python3
"""
bib2registros.py -- normaliza el .bib del CV a registros.json

Fuente:  el .bib que indiques en config.json
Salida:  registros.json  (lista de registros normalizados, listos para diff y carga)

Sin dependencias externas: parser de BibTeX propio (el .bib es un export de DBLP
mas entradas manuales, formato regular).

Uso:
    python3 bib2registros.py                    # usa las rutas por defecto
    python3 bib2registros.py --bib X --out Y
    python3 bib2registros.py --resumen          # solo imprime el resumen
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import config as CFG

BIB_DEFECTO = CFG.BIB
OUT_DEFECTO = CFG.ruta_datos("registros.json")

# ---------------------------------------------------------------- parser bibtex

def _entradas_crudas(texto: str):
    """Devuelve (tipo, clave, cuerpo) por cada entrada @tipo{clave, ...}."""
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", texto):
        tipo = m.group(1).lower()
        clave = m.group(2).strip()
        # balanceo de llaves desde la apertura de la entrada
        inicio = texto.index("{", m.start())
        nivel = 0
        for i in range(inicio, len(texto)):
            if texto[i] == "{":
                nivel += 1
            elif texto[i] == "}":
                nivel -= 1
                if nivel == 0:
                    yield tipo, clave, texto[m.end():i]
                    break


def _campos(cuerpo: str) -> dict:
    """Parsea 'campo = {valor}' / 'campo = "valor"' / 'campo = token'."""
    out, i, n = {}, 0, len(cuerpo)
    while i < n:
        m = re.compile(r"(\w+)\s*=\s*").search(cuerpo, i)
        if not m:
            break
        nombre = m.group(1).lower()
        j = m.end()
        if j < n and cuerpo[j] == "{":
            nivel, k = 0, j
            while k < n:
                if cuerpo[k] == "{":
                    nivel += 1
                elif cuerpo[k] == "}":
                    nivel -= 1
                    if nivel == 0:
                        break
                k += 1
            valor, i = cuerpo[j + 1:k], k + 1
        elif j < n and cuerpo[j] == '"':
            k = cuerpo.index('"', j + 1)
            valor, i = cuerpo[j + 1:k], k + 1
        else:
            k = cuerpo.find(",", j)
            k = n if k == -1 else k
            valor, i = cuerpo[j:k], k
        out[nombre] = valor
    return out


# ------------------------------------------------------------ limpieza de texto

# comando LaTeX -> caracter combinante Unicode (se aplica sobre la letra base)
_COMBINANTES = {
    "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303",
    "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b",
    "c": "\u0327", "k": "\u0328", "d": "\u0323", "b": "\u0331", "r": "\u030a",
}
# comandos que producen una letra entera, no un acento
_LETRAS = {
    r"\ss": "ß", r"\aa": "å", r"\AA": "Å", r"\o": "ø", r"\O": "Ø",
    r"\l": "ł", r"\L": "Ł", r"\ae": "æ", r"\AE": "Æ", r"\oe": "œ",
    r"\OE": "Œ", r"\i": "i", r"\j": "j",
}

# DBLP escribe {\'{e}}; TeX clasico admite \'e, \'{e}, \c c, \c{c}
_RE_ACENTO = re.compile(
    r"\\([`'^\"~=.uvHckdbr])\s*\{?\s*(?:\\([ij])|([A-Za-z]))\s*\}?"
)


def _acentos(s: str) -> str:
    def rep(m):
        base = m.group(2) or m.group(3)
        return unicodedata.normalize("NFC", base + _COMBINANTES[m.group(1)])
    previo = None
    while previo != s:                      # {\'{e}} necesita mas de una pasada
        previo, s = s, _RE_ACENTO.sub(rep, s)
    for cmd, letra in sorted(_LETRAS.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(re.escape(cmd) + r"\{\}|" + re.escape(cmd) + r"(?![A-Za-z])",
                   letra, s)
    return s


def limpiar(s: str) -> str:
    """Colapsa saltos de linea, resuelve acentos LaTeX y saca llaves."""
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    s = _acentos(s)
    s = s.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_")
    s = s.replace("{-}", "-").replace("--", "-")
    s = s.replace("{", "").replace("}", "").replace("\\", "")
    return re.sub(r"\s+", " ", s).strip()


def clave_titulo(titulo: str) -> str:
    """Clave de matcheo: minusculas, sin acentos, solo alfanumericos."""
    s = unicodedata.normalize("NFKD", limpiar(titulo).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s)


def partir_autores(raw: str) -> list:
    """'First Last and First Last' -> [{'nombre':..,'apellido':..,'completo':..}]."""
    autores = []
    for a in re.split(r"\s+and\s+", limpiar(raw)):
        a = a.strip().rstrip(",")
        if not a:
            continue
        a = re.sub(r"\s+\d+$", "", a)          # sufijos DBLP tipo "Zhao 0001"
        if "," in a:                            # ya viene "Apellido, Nombre"
            apellido, _, nombre = a.partition(",")
        else:
            partes = a.split()
            apellido, nombre = partes[-1], " ".join(partes[:-1])
        autores.append({
            "apellido": apellido.strip(),
            "nombre": nombre.strip(),
            "completo": a,
        })
    return autores


# ------------------------------------------------------------------ tipificacion

def tipificar(tipo_bib: str, kw: str, venue: str) -> str:
    """Tipo de produccion para SIGEVA."""
    kw = kw.lower()
    if "thesis" in kw or tipo_bib in ("phdthesis", "mastersthesis"):
        return "tesis"
    # DBLP marca los preprints como CoRR; Google Scholar los exporta como
    # @article con journal "arXiv preprint arXiv:..." o "arXiv e-prints"
    if ("arxiv" in kw or "preprint" in kw or venue.lower().startswith("corr")
            or "arxiv" in venue.lower()):
        return "preprint"
    if tipo_bib == "article":
        return "articulo"
    if tipo_bib == "inproceedings":
        return "evento"
    if tipo_bib == "book":
        return "libro"
    if tipo_bib == "incollection":
        return "capitulo"
    return "otro"


def convertir(bib: Path) -> list:
    texto = bib.read_text(encoding="utf-8", errors="replace")
    registros = []
    vistas: dict = {}
    for tipo_bib, clave, cuerpo in _entradas_crudas(texto):
        # Google Scholar repite claves (dos papers 'liang2025green'). La clave
        # identifica el registro en estado.json y en pdfs/: repetida, el
        # segundo se daba por cargado y se salteaba en silencio.
        if clave in vistas:
            vistas[clave] += 1
            nueva = f"{clave}-{vistas[clave]}"
            print(f"Aviso: la clave '{clave}' está repetida en el .bib; "
                  f"la entrada siguiente pasa a '{nueva}'", file=sys.stderr)
            clave = nueva
        else:
            vistas[clave] = 1
        c = {k: limpiar(v) for k, v in _campos(cuerpo).items()}
        venue = c.get("journal") or c.get("booktitle") or c.get("publisher") or ""
        kw = c.get("keywords", "")
        anio = re.search(r"\d{4}", c.get("year", ""))
        registros.append({
            "clave": clave,
            "tipo": tipificar(tipo_bib, kw, venue),
            "tipo_bib": tipo_bib,
            "anio": int(anio.group()) if anio else None,
            "titulo": c.get("title", ""),
            "titulo_clave": clave_titulo(c.get("title", "")),
            "autores": partir_autores(c.get("author", "") or c.get("editor", "")),
            "venue": venue,
            "volumen": c.get("volume", ""),
            "numero": c.get("number", ""),
            "paginas": c.get("pages", ""),
            "editorial": c.get("publisher", ""),
            # el DOI se guarda tal cual: el importador de SIGEVA no siempre
            # resuelve la version en minusculas
            "doi": re.sub(r"^https?://(dx\.)?doi\.org/", "", c.get("doi", ""), flags=re.I),
            "url": c.get("url", ""),
            "issn": c.get("issn", ""),
            "isbn": c.get("isbn", ""),
            "keywords": kw,
            "destacado": "selected" in kw,
            # aceptado pero sin publicar: no se puede declarar como publicado
            # hasta que salga (y tenga DOI, paginas, editorial)
            "en_prensa": bool(re.search(r"to appear|in press|accepted|en prensa",
                                        c.get("note", ""), re.I)),
            "pdf": None,          # lo completa emparejar_pdfs.py
        })
    return registros


def resumen(registros: list) -> str:
    from collections import Counter
    por_tipo = Counter(r["tipo"] for r in registros)
    lineas = [f"Total: {len(registros)} entradas", "", "Por tipo:"]
    lineas += [f"  {t:<10} {n:>4}" for t, n in por_tipo.most_common()]
    desde = [r for r in registros if (r["anio"] or 0) >= 2017]
    lineas += ["", f"Desde 2017 (periodo evaluado): {len(desde)}", "", "Por anio:"]
    por_anio = Counter(r["anio"] for r in registros)
    for a in sorted(por_anio, key=lambda x: (x is None, x), reverse=True):
        lineas.append(f"  {a}  {por_anio[a]:>3}")
    sin_doi = [r for r in registros if not r["doi"]]
    lineas += ["", f"Sin DOI: {len(sin_doi)} (matcheo solo por titulo)"]
    return "\n".join(lineas)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bib", type=Path, default=BIB_DEFECTO)
    p.add_argument("--out", type=Path, default=OUT_DEFECTO)
    p.add_argument("--resumen", action="store_true", help="no escribe, solo resume")
    a = p.parse_args()

    if not a.bib or not a.bib.exists():
        sys.exit(f"No existe el .bib: {a.bib}")

    registros = convertir(a.bib)
    registros.sort(key=lambda r: (-(r["anio"] or 0), r["titulo"]))

    if not a.resumen:
        a.out.write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Escrito: {a.out}")
    print()
    print(resumen(registros))


if __name__ == "__main__":
    main()
