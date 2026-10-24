#!/usr/bin/env python3
"""
config.py -- todo lo que cambia de una persona a otra

Se lee de `config.json` en la raiz del proyecto. Si no existe, se usan los
valores por defecto y el programa avisa que hay que crearlo.

    cp ejemplos/config.ejemplo.json config.json && $EDITOR config.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO = Path(os.environ.get("CARGA_SIGEVA_CONFIG", RAIZ / "config.json"))
DATOS_DIR = RAIZ / "datos"

DEFECTOS = {
    # Quien sos: el apellido con el que figuras como autor. Sirve para que el
    # cargador marque la fila correcta como "autor declarante".
    "apellido": "",

    # Mail de contacto para las APIs publicas (Crossref, OpenAlex y HAL piden
    # identificarse; con mail dan mas cuota y menos throttling).
    "mail_contacto": "",

    # Instancia de SIGEVA. Probado solo con la de CONICET.
    "sigeva": {
        "base": "https://si.conicet.gov.ar",
        "rol_banco_datos": 96,
    },

    # Bibliografia de entrada, en formato BibTeX.
    "bib": "",

    # Carpetas donde buscar los PDF del texto completo. Se aceptan dos
    # convenciones de nombre: <clavebibtex>.pdf y <ANIO>-<Venue>-<Tema>.pdf
    "carpetas_pdf": [],

    # Area del conocimiento que se declara en cada produccion. El campo es el
    # `value` del combo de SIGEVA; el subcampo puede ser su `value` o un trozo
    # de su etiqueta ("Telecomunicaciones"), porque se puebla por AJAX y su
    # value no esta en el HTML. inventariar.py los deja en datos/areas.json.
    "area_conocimiento": {
        "campo": "6",        # 1.2 Ciencias de la Computacion e Informacion
        "subcampo": "7",     # 1.2.1 Ciencias de la Computacion
    },

    # Desde que anio interesa cargar (0 = todo).
    "desde_anio": 0,
}


def _fusionar(base: dict, encima: dict) -> dict:
    out = dict(base)
    for k, v in (encima or {}).items():
        out[k] = _fusionar(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def cargar() -> dict:
    if not ARCHIVO.exists():
        print(f"No encuentro {ARCHIVO.name}. Copiá ejemplos/config.ejemplo.json "
              f"y completalo.", file=sys.stderr)
        return dict(DEFECTOS)
    return _fusionar(DEFECTOS, json.loads(ARCHIVO.read_text(encoding="utf-8")))


CONF = cargar()

APELLIDO = (CONF.get("apellido") or "").strip().lower()
MAIL = CONF.get("mail_contacto") or ""
BASE = CONF["sigeva"]["base"].rstrip("/")
ROL_BANCO_DATOS = int(CONF["sigeva"]["rol_banco_datos"])
BIB = Path(CONF["bib"]).expanduser() if CONF.get("bib") else None
CARPETAS_PDF = [Path(p).expanduser() for p in CONF.get("carpetas_pdf") or []]
AREA_CONOCIMIENTO = (CONF["area_conocimiento"]["campo"],
                     CONF["area_conocimiento"]["subcampo"])
DESDE_ANIO = int(CONF.get("desde_anio") or 0)

USER_AGENT = f"carga-sigeva/1.0 ({'mailto:' + MAIL if MAIL else 'sin contacto'})"


def es_declarante(apellido: str) -> bool:
    """True si ese apellido es el del dueño del Banco de Datos."""
    if not APELLIDO:
        return False
    import unicodedata
    def norm(s):
        s = unicodedata.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not unicodedata.combining(c))
    return norm(apellido).startswith(norm(APELLIDO))


def ruta_datos(nombre: str) -> Path:
    DATOS_DIR.mkdir(exist_ok=True)
    return DATOS_DIR / nombre