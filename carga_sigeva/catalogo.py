#!/usr/bin/env python3
"""
catalogo.py -- resuelve nombres de revistas e instituciones a IDs de SIGEVA

SIGEVA identifica revistas e instituciones por un ID interno. Teniendo el ID se
puede completar el formulario de una sola pasada, sin pasar por los buscadores
de tres pantallas. Los IDs se cosechan con cosechar.py.

El matcheo va de lo estricto a lo laxo: alias conocido, nombre normalizado
igual, tokens distintivos contenidos, y por ultimo similitud de texto.
"""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import config as CFG

AQUI = CFG.DATOS_DIR
CATALOGO = AQUI / "catalogo.json"

# palabras que no distinguen una institucion de otra
GENERICAS = {
    "university", "universidad", "universite", "universitat", "universiteit",
    "institute", "instituto", "research", "centre", "center", "centro",
    "national", "nacional", "de", "del", "la", "of", "the", "and", "y", "en",
    "di", "des", "du", "fur", "science", "sciences", "technology", "tecnologia",
}

# el nombre en ingles de OpenAlex no siempre coincide con el del catalogo
ALIAS = {
    "saarland university": "universitat des saarlandes",
    "inria": "institut national de recherche en informatique",
    "national space activities commission": "comision nacional de actividades espaciales",
    "conae": "argentinian space agency",
}

# filiaciones que OpenAlex devuelve mal y no hay que escribir en una DDJJ
BASURA = re.compile(r"^(fc |football|club |hospital de |google|facebook|twitter)", re.I)

UMBRAL_DIFUSO = 0.88


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _tokens(s: str) -> set:
    return {t for t in norm(s).split() if t not in GENERICAS and len(t) > 2}


class Catalogo:
    def __init__(self, ruta: Path = CATALOGO):
        datos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
        self.instituciones = list(datos.get("instituciones", {}).values())
        self.revistas = list(datos.get("revistas", {}).values())
        self._inst = [(norm(v["label"]), _tokens(v["label"]), v)
                      for v in self.instituciones]
        self._rev = [(norm(v["label"]), _tokens(v["label"]), v) for v in self.revistas]

    @staticmethod
    def _buscar(entradas: list, nombre: str) -> dict | None:
        """Del criterio mas estricto al mas laxo, sin bajar de lo defendible.

        Un solo token compartido NO alcanza: "Nanjing University" y "Nanjing
        Institute of Geology" comparten "nanjing" y son instituciones distintas.
        Escribir la equivocada en una declaracion jurada es peor que dejarla
        como "otra organizacion" con el nombre real.
        """
        n = norm(ALIAS.get(norm(nombre), nombre))
        if not n:
            return None
        tn = _tokens(n)
        for cn, ct, v in entradas:
            if n == cn:
                return v
        for cn, ct, v in entradas:
            if tn and ct and tn == ct:
                return v
        for cn, ct, v in entradas:
            if tn and ct and (tn <= ct or ct <= tn) and min(len(tn), len(ct)) >= 2:
                return v
        mejor_r, mejor_v = 0.0, None
        for cn, ct, v in entradas:
            r = SequenceMatcher(None, n, cn).ratio()
            if r > mejor_r:
                mejor_r, mejor_v = r, v
        return mejor_v if mejor_r >= UMBRAL_DIFUSO else None

    def institucion(self, nombre: str) -> dict | None:
        if not nombre or BASURA.match(nombre.strip()):
            return None
        return self._buscar(self._inst, nombre)

    def revista(self, nombre: str, issn: str = "") -> dict | None:
        if issn:
            for v in self.revistas:
                if v.get("issn") and norm(v["issn"]) == norm(issn):
                    return v
        return self._buscar(self._rev, nombre)


def resumen_cobertura(faltantes: list) -> str:
    """Cuanto del trabajo pendiente puede resolverse con el catalogo actual."""
    cat = Catalogo()
    total = resueltas = 0
    pendientes: dict = {}
    for r in faltantes:
        for a in r.get("autores", []):
            nombre = a.get("institucion")
            if not nombre:
                continue
            total += 1
            if cat.institucion(nombre):
                resueltas += 1
            else:
                pendientes[nombre] = pendientes.get(nombre, 0) + 1
    lineas = [f"Filiaciones: {total} | resueltas: {resueltas} "
              f"({100 * resueltas // max(total, 1)}%)",
              f"Instituciones distintas sin resolver: {len(pendientes)}"]
    for k, v in sorted(pendientes.items(), key=lambda x: -x[1])[:15]:
        lineas.append(f"  {v:>3}x  {k[:60]}")
    return "\n".join(lineas)


if __name__ == "__main__":
    datos = json.loads((AQUI / "faltantes-enriquecidos.json").read_text(encoding="utf-8"))
    cat = Catalogo()
    print(f"Catálogo: {len(cat.revistas)} revistas, {len(cat.instituciones)} instituciones\n")
    print(resumen_cobertura(datos))
