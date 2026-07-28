#!/usr/bin/env python3
"""
diff.py -- cruza registros.json (bib del CV) contra inventario.json (SIGEVA)

Salida:
    faltantes.json   lo que esta en el bib y no en SIGEVA
    dudosos.json     matcheos inciertos y posibles duplicados en SIGEVA
    (stdout)         resumen legible

Como matchea. La lista de SIGEVA trunca los titulos con "...", asi que no se
puede comparar por igualdad: se compara por PREFIJO normalizado (minusculas,
sin acentos, solo alfanumericos) y se desempata por año.

Uso:
    python3 diff.py
    python3 diff.py --desde 2017
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import config as CFG

AQUI = CFG.DATOS_DIR

# secciones de inventario.json que corresponden a publicaciones, y su tipo
SECCIONES = {
    "Año | Título | Revista | Editorial | Precarga": ("articulo", 0, 1, 2),
    "Año | Título | ISBN | Editorial": ("libro", 0, 1, 3),
    "Año | Título | Libro | Tipo de parte": ("capitulo", 0, 1, 2),
    "Año | Título | Tipo evento | Evento científico": ("evento", 0, 1, 3),
    "Fecha defensa / aprobación | Tesis | Título | Institución": ("tesis", 0, 1, 3),
}

# margen de años: SIGEVA suele registrar el año de publicacion final y el bib el
# de early access (o al reves)
TOLERANCIA_ANIOS = 1

# similitud minima para sospechar que un 'faltante' en realidad ya esta cargado
UMBRAL_DIFUSO = 0.80


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s)


def cargar_sigeva(inventario: dict) -> list:
    """Aplana las secciones de publicaciones de SIGEVA."""
    regs = []
    for seccion in inventario.get("publicaciones", []):
        conf = SECCIONES.get(seccion["seccion"])
        if not conf:
            continue
        tipo, i_anio, i_tit, i_venue = conf
        for r in seccion["registros"]:
            campos = r["campos"]
            crudo = campos[i_tit] if i_tit < len(campos) else ""
            truncado = crudo.rstrip().endswith("...")
            titulo = crudo.rstrip().rstrip(".").strip() if truncado else crudo
            anio = re.search(r"(19|20)\d{2}", campos[i_anio] if i_anio < len(campos) else "")
            regs.append({
                "tipo": tipo,
                "anio": int(anio.group()) if anio else None,
                "titulo": crudo,
                "clave": norm(titulo),
                "truncado": truncado,
                "venue": campos[i_venue] if i_venue < len(campos) else "",
                "href": r.get("href", ""),
                "usado_por": [],
            })
    return regs


def compatible(a: int | None, b: int | None) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= TOLERANCIA_ANIOS


def buscar(bib: dict, sigeva: list) -> list:
    """Candidatos de SIGEVA para una entrada del bib, mejor primero."""
    cb = bib["titulo_clave"]
    cands = []
    for s in sigeva:
        cs = s["clave"]
        if not cs or not cb:
            continue
        if cs == cb:
            calidad = "exacto"
        elif s["truncado"] and cb.startswith(cs):
            calidad = "prefijo"
        elif cb.startswith(cs) or cs.startswith(cb):
            calidad = "prefijo"
        else:
            continue
        cands.append((0 if calidad == "exacto" else 1,
                      0 if compatible(bib["anio"], s["anio"]) else 1, s, calidad))
    cands.sort(key=lambda x: (x[1], x[0], -len(x[2]["clave"])))
    return cands


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--desde", type=int, default=None, help="filtra el bib por año")
    a = p.parse_args()

    registros = json.loads((AQUI / "registros.json").read_text(encoding="utf-8"))
    inventario = json.loads((AQUI / "inventario.json").read_text(encoding="utf-8"))
    sigeva = cargar_sigeva(inventario)

    if a.desde:
        registros = [r for r in registros if (r["anio"] or 0) >= a.desde]

    faltantes, encontrados, dudosos, casi = [], [], [], []
    for r in registros:
        cands = buscar(r, sigeva)
        if not cands:
            # pase difuso: el titulo pudo cargarse distinto en SIGEVA
            # ("DTN of Things" vs "Delay Tolerant Networks of Things")
            mejor_r, mejor_s = 0.0, None
            for s in sigeva:
                if not s["clave"] or not compatible(r["anio"], s["anio"]):
                    continue
                a_, b_ = r["titulo_clave"], s["clave"]
                if s["truncado"]:
                    a_ = a_[:len(b_)]
                ratio = SequenceMatcher(None, a_, b_).ratio()
                if ratio > mejor_r:
                    mejor_r, mejor_s = ratio, s
            if mejor_s and mejor_r >= UMBRAL_DIFUSO:
                casi.append({**r, "sigeva": {"titulo": mejor_s["titulo"],
                                             "anio": mejor_s["anio"],
                                             "tipo": mejor_s["tipo"],
                                             "href": mejor_s["href"]},
                             "similitud": round(mejor_r, 3)})
                mejor_s["usado_por"].append(r["clave"])
                continue
            faltantes.append(r)
            continue
        _, penaliza_anio, mejor, calidad = cands[0]
        mejor["usado_por"].append(r["clave"])
        registro = {**r, "sigeva": {"titulo": mejor["titulo"], "anio": mejor["anio"],
                                    "tipo": mejor["tipo"], "href": mejor["href"]},
                    "calidad": calidad}
        if penaliza_anio or calidad != "exacto" or r["tipo"] != mejor["tipo"]:
            registro["motivo"] = "; ".join(filter(None, [
                f"año bib {r['anio']} vs SIGEVA {mejor['anio']}" if penaliza_anio else "",
                "match por prefijo (título truncado en SIGEVA)" if calidad == "prefijo" else "",
                f"tipo bib '{r['tipo']}' vs SIGEVA '{mejor['tipo']}'" if r["tipo"] != mejor["tipo"] else "",
            ]))
            dudosos.append(registro)
        encontrados.append(registro)

    # duplicados dentro de SIGEVA: misma clave normalizada y año compatible
    porclave = defaultdict(list)
    for s in sigeva:
        if s["clave"]:
            porclave[(s["clave"], s["anio"])].append(s)
    duplicados = [{"titulo": v[0]["titulo"], "anio": v[0]["anio"], "n": len(v),
                   "hrefs": [x["href"] for x in v]}
                  for v in porclave.values() if len(v) > 1]

    huerfanos = [{"titulo": s["titulo"], "anio": s["anio"], "tipo": s["tipo"],
                  "venue": s["venue"], "href": s["href"]}
                 for s in sigeva if not s["usado_por"]]

    (AQUI / "faltantes.json").write_text(
        json.dumps(faltantes, ensure_ascii=False, indent=2), encoding="utf-8")
    (AQUI / "dudosos.json").write_text(
        json.dumps({"casi_seguro_ya_cargados": casi, "matcheos_dudosos": dudosos,
                    "duplicados_en_sigeva": duplicados,
                    "en_sigeva_sin_bib": huerfanos}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    # ---------------------------------------------------------------- resumen
    print(f"Bib: {len(registros)} entradas" + (f" (desde {a.desde})" if a.desde else ""))
    print(f"SIGEVA: {len(sigeva)} publicaciones cargadas")
    print(f"  ya cargadas : {len(encontrados)}")
    print(f"  match difuso: {len(casi)}  (mismo trabajo con titulo distinto -> REVISAR)")
    print(f"  FALTANTES   : {len(faltantes)}")
    print()

    print("FALTANTES por tipo:")
    for t, n in Counter(r["tipo"] for r in faltantes).most_common():
        print(f"  {t:<10} {n:>3}")
    print()
    print("FALTANTES por año:")
    por_anio = Counter(r["anio"] for r in faltantes)
    for anio in sorted(por_anio, key=lambda x: (x is None, x), reverse=True):
        tipos = Counter(r["tipo"] for r in faltantes if r["anio"] == anio)
        det = " ".join(f"{k}:{v}" for k, v in sorted(tipos.items()))
        print(f"  {anio}  {por_anio[anio]:>3}   {det}")
    print()
    if casi:
        print("Match difuso, probablemente YA cargados (revisar antes de cargar):")
        for c in casi:
            print(f"  {c['similitud']}  bib: {c['titulo'][:58]}")
            print(f"         SIGEVA: {c['sigeva']['titulo'][:58]}")
        print()
    print(f"Matcheos dudosos (revisar): {len(dudosos)}")
    print(f"Posibles duplicados YA cargados en SIGEVA: {len(duplicados)}")
    for d in duplicados:
        print(f"  [{d['anio']}] x{d['n']}  {d['titulo'][:70]}")
    print(f"En SIGEVA pero no en el bib: {len(huerfanos)}")
    print()
    print("-> faltantes.json, dudosos.json")


if __name__ == "__main__":
    main()
