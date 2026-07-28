#!/usr/bin/env python3
"""
pdfs_hal.py -- consigue los full text que faltan desde repositorios abiertos

SIGEVA exige adjuntar el texto completo de cada produccion, y en disco solo hay
PDF para una parte. Este script busca el resto en fuentes abiertas y los baja a
pdfs/, nombrados por clave bibtex.

Fuentes, en orden:
  1. HAL (hal.science) -- Juan deposita ahi por Inria, asi que cubre lo reciente
  2. OpenAlex -> best_oa_location / open_access.oa_url (arXiv, repositorios)

No baja nada de sitios con paywall ni evade accesos: solo versiones que los
propios repositorios publican en abierto.

Uso:
    python3 pdfs_hal.py              # baja lo que falte
    python3 pdfs_hal.py --informe    # solo dice que encontraria
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import config as CFG

AQUI = CFG.DATOS_DIR
PDFS = AQUI / "pdfs"
DATOS = AQUI / "faltantes-enriquecidos.json"

CABECERAS = {"User-Agent": CFG.USER_AGENT}
MIN_BYTES = 20_000          # por debajo de esto no es un paper, es un error


def _json(url: str) -> dict:
    req = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def url_en_hal(reg: dict) -> str:
    """Busca en HAL por DOI y, si no, por titulo exacto."""
    base = "https://api.archives-ouvertes.fr/search/"
    consultas = []
    if reg.get("doi"):
        consultas.append(f'doiId_s:"{reg["doi"]}"')
    titulo = re.sub(r'["\\]', " ", reg["titulo"])[:150]
    consultas.append(f'title_t:"{titulo}"')
    for q in consultas:
        url = f"{base}?q={urllib.parse.quote(q)}&fl=fileMain_s,title_s&rows=3&wt=json"
        try:
            docs = _json(url).get("response", {}).get("docs", [])
        except Exception:
            continue
        for d in docs:
            if d.get("fileMain_s"):
                return d["fileMain_s"]
    return ""


def url_en_openalex(reg: dict) -> str:
    """Version en abierto que conozca OpenAlex (arXiv y repositorios)."""
    if not reg.get("doi"):
        return ""
    try:
        d = _json("https://api.openalex.org/works/doi:"
                  + urllib.parse.quote(reg["doi"]))
    except Exception:
        return ""
    for clave in ("best_oa_location", "primary_location"):
        loc = d.get(clave) or {}
        for campo in ("pdf_url", "landing_page_url"):
            u = loc.get(campo) or ""
            if u.lower().endswith(".pdf"):
                return u
    u = (d.get("open_access") or {}).get("oa_url") or ""
    return u if u.lower().endswith(".pdf") else ""


def bajar(url: str, destino: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers=CABECERAS)
        with urllib.request.urlopen(req, timeout=60) as r:
            datos = r.read()
    except Exception:
        return False
    if len(datos) < MIN_BYTES or not datos[:5].startswith(b"%PDF"):
        return False
    destino.write_bytes(datos)
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--informe", action="store_true")
    a = p.parse_args()

    registros = json.loads(DATOS.read_text(encoding="utf-8"))
    pendientes = [r for r in registros
                  if r["tipo"] in ("articulo", "evento", "capitulo")
                  and not (r.get("pdf") and Path(r["pdf"]).exists())]
    print(f"{len(pendientes)} producciones sin full text\n")
    PDFS.mkdir(exist_ok=True)

    hallados = {"hal": 0, "openalex": 0}
    sin_nada = []
    for i, r in enumerate(pendientes, 1):
        destino = PDFS / (re.sub(r"[^A-Za-z0-9._-]", "_", r["clave"])[:80] + ".pdf")
        if destino.exists() and destino.stat().st_size >= MIN_BYTES:
            r["pdf"], r["pdf_confianza"] = str(destino), "alta"
            continue

        for fuente, buscador in (("hal", url_en_hal), ("openalex", url_en_openalex)):
            url = buscador(r)
            if not url:
                continue
            if a.informe:
                hallados[fuente] += 1
                print(f"  [{fuente}] {r['titulo'][:58]}")
                break
            if bajar(url, destino):
                hallados[fuente] += 1
                r["pdf"], r["pdf_confianza"] = str(destino), "alta"
                print(f"  [{fuente}] {r['titulo'][:58]}")
                break
        else:
            sin_nada.append(r)
        if i % 20 == 0:
            print(f"  ... {i}/{len(pendientes)}")

    print(f"\nHAL: {hallados['hal']} | OpenAlex: {hallados['openalex']} | "
          f"sin encontrar: {len(sin_nada)}")
    if not a.informe:
        DATOS.write_text(json.dumps(registros, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        print("-> faltantes-enriquecidos.json actualizado")


if __name__ == "__main__":
    main()
