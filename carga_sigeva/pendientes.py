#!/usr/bin/env python3
"""
pendientes.py -- arma PENDIENTES.md con lo que falta cargar, por categoria

Cruza faltantes-enriquecidos.json con estado.json y agrupa lo no cargado segun
que dato falta, para poder completarlo a mano.

Uso:
    python3 pendientes.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import config as CFG

AQUI = CFG.DATOS_DIR
SALIDA = CFG.RAIZ / "PENDIENTES.md"

# motivo del ultimo intento -> (categoria, que hace falta)
CATEGORIAS = [
    (r"sin resumen", "resumen", "Falta el abstract"),
    (r"país del evento|pais del evento", "sede", "Falta ciudad y país del congreso"),
    (r"editorial", "editorial", "Falta la editorial"),
    (r"pais de edición|país de edición", "editorial", "Falta el país de edición"),
    (r"no figura en la lista", "silencioso", "Guarda sin error pero no queda (a resolver por mí)"),
    (r"Timeout|no respondió", "timeout", "El servidor no respondió (reintentar)"),
]


def categoria(reg: dict, motivo: str) -> tuple:
    if not (reg.get("pdf") and Path(reg["pdf"]).exists()):
        return "fulltext", "Falta el PDF del texto completo"
    for patron, cat, desc in CATEGORIAS:
        if re.search(patron, motivo or "", re.I):
            return cat, desc
    return "otro", motivo or "sin diagnóstico"


def enlace(reg: dict) -> str:
    if reg.get("doi"):
        return f"[{reg['doi']}](https://doi.org/{reg['doi']})"
    return reg.get("url") or "—"


def main():
    registros = json.loads((AQUI / "faltantes-enriquecidos.json").read_text(encoding="utf-8"))
    estado = json.loads((AQUI / "estado.json").read_text(encoding="utf-8"))

    guardados = {e["clave"] for e in estado if e.get("resultado") == "guardado"}
    ultimo = {}
    for e in estado:
        if e.get("clave"):
            ultimo[e["clave"]] = e.get("detalle") or e.get("resultado") or ""

    grupos: dict = {}
    for r in registros:
        if (r["tipo"] not in ("articulo", "evento")
                or r["clave"] in guardados
                or r.get("excluir")):        # decisiones tomadas, no pendientes
            continue
        cat, desc = categoria(r, ultimo.get(r["clave"], ""))
        grupos.setdefault(cat, {"desc": desc, "regs": []})["regs"].append(r)

    orden = ["fulltext", "sede", "resumen", "editorial", "silencioso", "timeout", "otro"]
    titulos = {
        "fulltext": "Falta el PDF del texto completo",
        "sede": "Falta la sede del congreso",
        "resumen": "Falta el resumen",
        "editorial": "Falta la editorial o el país de edición",
        "silencioso": "Guardan sin error pero no quedan",
        "timeout": "El servidor no respondió",
        "otro": "Otros",
    }
    mios = {"silencioso", "timeout"}

    total = sum(len(g["regs"]) for g in grupos.values())
    out = [
        "# Pendientes de carga en SIGEVA",
        "",
        f"{total} registros sin cargar, sobre 78 cargables. Los otros 43 ya están.",
        "",
        "Generado por `sigeva-carga/pendientes.py`. Para regenerarlo:",
        "",
        "```bash",
        "cd sigeva-carga && python3 pendientes.py",
        "```",
        "",
    ]

    for cat in orden:
        g = grupos.get(cat)
        if not g:
            continue
        regs = sorted(g["regs"], key=lambda r: (-(r["anio"] or 0), r["titulo"]))
        out += [f"## {titulos[cat]} ({len(regs)})", ""]
        if cat in mios:
            out += ["Estos son problemas del cargador, no tuyos. No necesito nada.", ""]
        out += ["| # | Año | Tipo | Título | Publicado en | DOI |",
                "|---|---|---|---|---|---|"]
        for i, r in enumerate(regs, 1):
            titulo = r["titulo"].replace("|", "\\|")
            venue = (r.get("venue_oficial") or r.get("venue") or "—").replace("|", "\\|")
            out.append(f"| {i} | {r['anio']} | {r['tipo']} | {titulo[:88]} | "
                       f"{venue[:60]} | {enlace(r)} |")
        out.append("")
        if cat == "fulltext":
            out += [
                "**Cómo ayudar:** dejá el PDF en `sigeva-carga/pdfs/` con el nombre "
                "que figura abajo, y el cargador lo toma solo.",
                "",
                "| # | Nombre de archivo esperado |",
                "|---|---|",
            ]
            for i, r in enumerate(regs, 1):
                nombre = re.sub(r"[^A-Za-z0-9._-]", "_", r["clave"])[:80] + ".pdf"
                out.append(f"| {i} | `{nombre}` |")
            out.append("")
        elif cat == "sede":
            out += ["**Cómo ayudar:** completá ciudad y país de cada congreso.", "",
                    "| # | Ciudad | País |", "|---|---|---|"]
            out += [f"| {i} |  |  |" for i in range(1, len(regs) + 1)]
            out.append("")
        elif cat == "resumen":
            out += ["**Cómo ayudar:** pegá el abstract de cada uno.", ""]
            for i, r in enumerate(regs, 1):
                out += [f"**{i}. {r['titulo'][:80]}**", "", "> ", ""]
        elif cat == "editorial":
            out += ["**Cómo ayudar:** indicá editorial y país de edición.", "",
                    "| # | Editorial | País |", "|---|---|---|"]
            out += [f"| {i} |  |  |" for i in range(1, len(regs) + 1)]
            out.append("")

    SALIDA.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"-> {SALIDA}")
    for cat in orden:
        if cat in grupos:
            print(f"   {titulos[cat]}: {len(grupos[cat]['regs'])}")


if __name__ == "__main__":
    main()
