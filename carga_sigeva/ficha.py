#!/usr/bin/env python3
"""
ficha.py -- arma la ficha de un registro para cargarlo a mano en SIGEVA

Vuelca todos los campos en el orden del formulario, listos para copiar y pegar,
incluidas las filiaciones de cada autor y la ruta del PDF.

Uso:
    python3 ficha.py                      # el pendiente que crea mas instituciones
    python3 ficha.py --clave <bibkey>
    python3 ficha.py --todos              # todos los pendientes
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cargar as C
from catalogo import Catalogo
import config as CFG

AQUI = CFG.DATOS_DIR
SALIDA = CFG.RAIZ / "FICHA-CARGA-MANUAL.md"


def nuevas_instituciones(reg: dict, cat: Catalogo) -> list:
    return sorted({a["institucion"] for a in reg["autores"]
                   if a.get("institucion") and not cat.institucion(a["institucion"])})


def ficha(reg: dict, cat: Catalogo) -> list:
    esdoc = reg["tipo"] == "evento"
    sede = C.sede_evento(reg) if esdoc else {}
    editorial, pais = C.editorial_y_pais(reg)
    enlace = reg.get("url") or (f"https://doi.org/{reg['doi']}" if reg.get("doi") else "")
    paginas = (reg.get("paginas") or "").replace("--", "-")

    out = [f"## {reg['titulo']}", "",
           f"`{reg['clave']}` · {reg['anio']} · "
           f"{'Trabajo en evento' if esdoc else 'Artículo en revista'}", ""]

    out += ["### Datos básicos", "", "| Campo | Valor |", "|---|---|"]
    if esdoc:
        out += [
            "| Tipo de trabajo | Artículo Completo |",
            f"| Título | {reg['titulo']} |",
            f"| Idioma | {C.idioma_de(reg)} |",
            "| Tipo de publicación | Libro |",
            f"| Título del libro | {reg['venue'][:150]} |",
            f"| País de edición | {sede.get('pais') or '(completar)'} |",
            f"| Ciudad de la editorial | {sede.get('ciudad') or '(completar)'} |",
            f"| Editorial | {editorial or '(completar)'} |",
            f"| Año de publicación | {reg['anio']} |",
        ]
    else:
        out += [
            f"| Revista (buscar por ISSN) | **{reg.get('issn') or 'sin ISSN'}** — "
            f"{reg.get('venue_oficial') or reg['venue']} |",
            f"| Editorial | {editorial or '(completar)'} |",
            f"| País de edición | {pais or '(completar)'} |",
            f"| Título del artículo | {reg['titulo']} |",
            f"| Idioma | {C.idioma_de(reg)} |",
            f"| Volumen | {reg.get('volumen') or '-'} |",
            f"| Número | {reg.get('numero') or '-'} |",
            f"| Páginas | {paginas or '-'} |",
            f"| Fecha de publicación | {reg.get('fecha_publicacion') or '-'} |",
            f"| DOI | {reg.get('doi') or '-'} |",
        ]
    out += [
        f"| URL | {enlace or '-'} |",
        "| Referato | Con referato |",
        "| Estado | Publicado |",
        f"| Soporte | {'Electrónico y/o Digital' if enlace else 'Impreso'} |",
        "",
    ]

    if esdoc:
        out += ["### Datos del evento", "", "| Campo | Valor |", "|---|---|",
                f"| Nombre del evento | {reg['venue'][:150]} |",
                f"| Tipo de evento | {C.tipo_reunion_de(reg)} |",
                "| Alcance | Internacional |",
                f"| País | {sede.get('pais') or '(completar)'} |",
                f"| Ciudad | {sede.get('ciudad') or '(completar)'} |",
                f"| Fecha (mm/aaaa) | {(sede.get('fecha') or '')[-7:] or reg.get('fecha_publicacion') or '-'} |",
                ""]

    out += ["### Autores, en orden", "",
            "| # | Autor | Institución | País | ¿Está en SIGEVA? |",
            "|---|---|---|---|---|"]
    for i, a in enumerate(reg["autores"], 1):
        inst = a.get("institucion") or ""
        enc = cat.institucion(inst) if inst else None
        propio = CFG.es_declarante(a["apellido"])
        estado = ("la completa SIGEVA sola" if propio
                  else "sí, buscar" if enc else "**hay que crearla**" if inst else "sin dato")
        pais_a = C.PAIS_ISO.get((a.get("pais_institucion") or "").upper(), "")
        out.append(f"| {i} | {a['apellido']}, {a['nombre']} | {inst or '—'} | "
                   f"{pais_a or '—'} | {estado} |")
    out.append("")

    out += ["### Resto", "", "| Campo | Valor |", "|---|---|",
            "| Área del conocimiento | 1.2 Ciencias de la Computación e Información |",
            "| Subárea | 1.2.1 Ciencias de la Computación |",
            f"| Palabras clave | {' · '.join(C.palabras_clave(reg))} |",
            f"| Full text | `{reg.get('pdf') or 'sin PDF'}` |",
            "| Tipo de archivo | Post print |", ""]

    out += ["### Resumen (copiar y pegar)", "", "```",
            reg.get("resumen") or "(sin resumen)", "```", ""]
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clave")
    p.add_argument("--todos", action="store_true")
    a = p.parse_args()

    datos = json.loads((AQUI / "faltantes-enriquecidos.json").read_text(encoding="utf-8"))
    estado = json.loads((AQUI / "estado.json").read_text(encoding="utf-8"))
    guardados = {e["clave"] for e in estado if e.get("resultado") == "guardado"}
    cat = Catalogo()

    pend = [r for r in datos if r["tipo"] in ("articulo", "evento")
            and r["clave"] not in guardados and not r.get("excluir")]
    if a.clave:
        elegidos = [r for r in pend if r["clave"] == a.clave]
    elif a.todos:
        elegidos = pend
    else:
        elegidos = sorted(pend, key=lambda r: -len(nuevas_instituciones(r, cat)))[:1]

    out = ["# Ficha para cargar a mano en SIGEVA", ""]
    for r in elegidos:
        nuevas = nuevas_instituciones(r, cat)
        if nuevas:
            out += [f"> Al guardar este registro quedan creadas en el catálogo de "
                    f"SIGEVA **{len(nuevas)} instituciones**: "
                    + ", ".join(nuevas) + ".", ""]
        out += ficha(r, cat)
    SALIDA.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"-> {SALIDA}")


if __name__ == "__main__":
    main()
