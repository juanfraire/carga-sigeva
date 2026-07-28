#!/usr/bin/env python3
"""
cosechar.py -- arma el catalogo local de IDs de SIGEVA (solo lectura)

SIGEVA identifica revistas e instituciones por un ID interno. Si se conocen esos
IDs, el alta de una produccion se puede completar de una sola pasada, sin pasar
por los buscadores de tres pantallas (que son lentos y fragiles).

Los IDs estan dentro de las producciones YA cargadas. Este script las abre en
modo Editar, los extrae y arma:

    catalogo.json
      revistas      : {nombre normalizado: publicacionId}
      instituciones : {nombre normalizado: {id, label, otra}}

No modifica nada: solo navega y lee. Los campos de autores se renderizan por
JavaScript, asi que hay que abrir la pagina de verdad (no alcanza con fetch).

Uso:
    SIGEVA_USER=... SIGEVA_PASS=... ./.venv/bin/python cosechar.py
    ./.venv/bin/python cosechar.py --limit 10
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import cargar as C          # reutiliza login, rol y utilidades

import config as CFG

AQUI = CFG.DATOS_DIR
CATALOGO = AQUI / "catalogo.json"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def hrefs_en_vivo(page) -> list:
    """Lista los enlaces de Editar directamente de SIGEVA.

    Antes esto salia de inventario.json, pero ese archivo envejece apenas se
    carga algo nuevo. Leerlo en vivo evita cosechar sobre una foto vieja.
    """
    return page.evaluate(r"""async () => {
        const dec = new TextDecoder('iso-8859-1');
        const base = 'bcoProduccionListaPublicacion.do?idMenu=1466&paginar=true'
                   + '&idModulo=6&prod=cientifica&idGrupo=6';
        const vistos = new Set();
        for (let p = 1; p <= 15; p++) {
            const r = await fetch(`${base}&d-3997137-p=${p}&d-8106305-p=${p}`,
                                  {credentials: 'same-origin'});
            const doc = new DOMParser().parseFromString(
                dec.decode(await r.arrayBuffer()), 'text/html');
            doc.querySelectorAll('a[href*="action=Editar"]').forEach(
                a => vistos.add(a.getAttribute('href')));
        }
        return Array.from(vistos);
    }""")


def extraer(page) -> dict:
    # string raw: el JS lleva sus propias barras invertidas
    return page.evaluate(r"""() => {
        const val = (n) => { const e = document.querySelector(`[name="${n}"]`);
                             return e ? e.value : ''; };
        const todos = (n) => Array.from(document.querySelectorAll(`[name="${n}"]`))
                                  .map(e => e.value);
        const labels = todos('autorOrganizacionLabel');
        const ids    = todos('autorOrganizacionId');
        const otras  = todos('autorisOtraOrganizacion');
        // en modo Editar la revista y el ISSN se muestran como texto, no en inputs
        const texto = document.body.innerText || '';
        const trozo = (patron) => {
            const m = texto.match(new RegExp(patron));
            return m ? m[1].trim() : '';
        };
        return {
            publicacionId: val('publicacionId'),
            revista: val('revista') || val('srevista')
                     || trozo('Revista:\\s*\\*?\\s*([^\\n]{3,120})'),
            issn: val('issn') || trozo('ISSN\\s*:?\\s*([0-9]{4}-[0-9]{3}[0-9Xx])'),
            instituciones: labels.map((l, i) => ({
                label: l, id: ids[i] || '', otra: otras[i] || ''})),
        };
    }""")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args()

    catalogo = json.loads(CATALOGO.read_text(encoding="utf-8")) if CATALOGO.exists() else {}
    revistas = catalogo.get("revistas", {})
    instituciones = catalogo.get("instituciones", {})

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(C.PERFIL), headless=False, viewport={"width": 1400, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        C.esperar_login(page)
        C.entrar_banco_datos(page)

        hrefs = hrefs_en_vivo(page)
        if a.limit:
            hrefs = hrefs[:a.limit]
        C.log(f"{len(hrefs)} producciones a revisar (solo lectura)")

        fallos = 0
        for i, href in enumerate(hrefs, 1):
            try:
                page.goto(f"{C.BASE}/eva/{href}", wait_until="domcontentloaded",
                          timeout=45_000)
                page.wait_for_timeout(400)      # deja correr el JS que arma autores
                d = extraer(page)
            except PWTimeout:
                fallos += 1
                continue

            if d["publicacionId"] and d["revista"]:
                revistas[norm(d["revista"])] = {
                    "id": d["publicacionId"], "label": d["revista"], "issn": d["issn"]}
            for inst in d["instituciones"]:
                if inst["label"] and inst["id"]:
                    instituciones[norm(inst["label"])] = {
                        "id": inst["id"], "label": inst["label"],
                        "otra": inst["otra"] == "true"}

            if i % 10 == 0 or i == len(hrefs):
                C.log(f"  {i}/{len(hrefs)} -> {len(revistas)} revistas, "
                      f"{len(instituciones)} instituciones")

        ctx.close()

    CATALOGO.write_text(json.dumps(
        {"revistas": revistas, "instituciones": instituciones},
        ensure_ascii=False, indent=1), encoding="utf-8")
    C.log(f"Listo. {len(revistas)} revistas y {len(instituciones)} instituciones "
          f"en catalogo.json ({fallos} páginas fallaron)")


if __name__ == "__main__":
    main()
