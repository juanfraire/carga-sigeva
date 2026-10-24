#!/usr/bin/env python3
"""
inventariar.py -- arma inventario.json con lo que YA esta cargado en SIGEVA

diff.py compara el .bib contra inventario.json, pero ningun otro script lo
genera. Este lo hace: entra al Banco de Datos, recorre la lista de
publicaciones y guarda cada tabla como una seccion

    {"publicaciones": [{"seccion": "Año | Título | Revista | ...",
                        "registros": [{"campos": [...], "href": "..."}]}]}

Solo lectura. En la misma sesion, para no pedir el ingreso dos veces:
  - guarda el HTML crudo en html/ (para re-parsear sin volver a entrar)
  - arma catalogo.json con los IDs de revistas e instituciones (cosechar.py)
  - guarda en areas.json los valores de los combos del area del conocimiento,
    que son los que pide config.json, y las etiquetas exactas de los paises

Uso:
    ../.venv/bin/python inventariar.py             # entra a SIGEVA
    ../.venv/bin/python inventariar.py --offline   # re-parsea html/ guardado
"""

from __future__ import annotations

import argparse
import json
import sys

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import cargar as C          # reutiliza URLs, rol y utilidades
import cosechar
import config as CFG

AQUI = CFG.DATOS_DIR
HTML = AQUI / "html"
INVENTARIO = AQUI / "inventario.json"
AREAS = AQUI / "areas.json"

PAGINAS = 15                # displaytag pagina de a 10: alcanza para 150 por tabla
ESPERA_LOGIN = 600_000      # ms: el ingreso lo hace la persona, sin apuro

# cada tabla con encabezado es una seccion. La primera columna ("Nuevo" en el
# encabezado, "Editar|Borrar" en las filas) se descarta para que los indices de
# diff.py (anio, titulo, venue) coincidan con las columnas de datos
PARSER = r"""(html) => {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const limpio = (e) => (e.textContent || '').replace(/\s+/g, ' ').trim();
    const out = [];
    doc.querySelectorAll('table').forEach(t => {
        const ths = Array.from(t.querySelectorAll(':scope > thead > tr > th'));
        if (!ths.length) return;
        const accion = ths.findIndex(th => limpio(th) === 'Nuevo');
        const cab = ths.filter((_, i) => i !== accion).map(limpio).filter(Boolean);
        const filas = Array.from(t.querySelectorAll(':scope > tbody > tr')).map(tr => {
            const a = tr.querySelector('a[href*="action=Editar"]');
            const tds = Array.from(tr.querySelectorAll(':scope > td'));
            return {campos: tds.filter((_, i) => i !== accion).map(limpio),
                    href: a ? a.getAttribute('href') : ''};
        }).filter(f => f.href);                 // "No hay registros cargados." no es fila
        out.push({seccion: cab.join(' | '), registros: filas});
    });
    return out;
}"""


def esperar_login(page) -> None:
    page.goto(C.INTRANET, wait_until="domcontentloaded")
    if page.locator('a[onclick*="redirect("]').count():
        return
    print("\n" + "=" * 66)
    print("  Ingresá tu usuario y contraseña en la ventana de Chromium.")
    print("  Yo no los veo ni los guardo. Espero hasta 10 minutos.")
    print("=" * 66 + "\n", flush=True)
    try:
        page.wait_for_selector('a[onclick*="redirect("]', state="attached",
                               timeout=ESPERA_LOGIN)
    except PWTimeout:
        sys.exit("No detecté la sesión iniciada. Volvé a correrlo.")
    C.log("Sesión detectada.")


def bajar_listas(page) -> list:
    """HTML de cada pagina de la lista de publicaciones, ya decodificado."""
    page.goto(C.URL_LISTA, wait_until="domcontentloaded", timeout=60_000)
    return page.evaluate(r"""async (n) => {
        const dec = new TextDecoder('iso-8859-1');
        const base = 'bcoProduccionListaPublicacion.do?idMenu=1466&paginar=true'
                   + '&idModulo=6&prod=cientifica&idGrupo=6';
        const out = [];
        for (let p = 1; p <= n; p++) {
            const r = await fetch(`${base}&d-3997137-p=${p}&d-8106305-p=${p}`,
                                  {credentials: 'same-origin'});
            out.push(dec.decode(await r.arrayBuffer()));
        }
        return out;
    }""", PAGINAS)


def bajar_indice(page) -> str:
    """Menu principal del Banco de Datos: trae el conteo de cada rubro."""
    page.goto(f"{C.BASE}/eva/indexBancoDatos.do?idModulo=1&idGrupo=0&idMenu=0",
              wait_until="domcontentloaded", timeout=60_000)
    return page.content()


def relevar_formulario(page) -> dict:
    """Combos del alta de evento que hacen falta para cargar, sin guardar nada.

    - campo_0 y su dependiente campo_0_0 (area del conocimiento)
    - paisEvento y paisEdicion, para usar las etiquetas exactas de SIGEVA

    Antes de tocar nada guarda el HTML y una captura del formulario: si un
    combo no responde, ahi se ve por que.
    """
    page.goto(C.URL_NUEVO_EVENTO, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_selector('select[name="campo_0"]', state="attached", timeout=45_000)
    (HTML / "form-evento.html").write_text(page.content(), encoding="utf-8")
    C.CAPTURAS.mkdir(exist_ok=True)
    page.screenshot(path=str(C.CAPTURAS / "form-evento.png"), full_page=True)

    opciones = lambda sel: page.evaluate(
        """(sel) => Array.from(document.querySelectorAll(sel)).map(e =>
                      Array.from(e.options).map(o => [o.value, o.text.trim()]))""", sel)
    # los values negativos son "Seleccionar" y los encabezados deshabilitados
    # ("2 INGENIERÍAS Y TECNOLOGÍAS" = -3): elegirlos se cuelga
    reales = lambda ops: [o for o in ops if o[0] and o[0] != "0" and not o[0].startswith("-")]
    datos = {"paises": {n: dict(reales(opciones(f'select[name="{n}"]')[0]))
                        for n in ("paisEvento", "paisEdicion")
                        if opciones(f'select[name="{n}"]')},
             "cantidad_campo_0": len(opciones('select[name="campo_0"]')),
             "areas": {}}

    combo = page.locator('select[name="campo_0"]:visible').first
    for valor, texto in reales(opciones('select[name="campo_0"]')[0]):
        try:
            combo.select_option(valor, timeout=5_000)
        except Exception as e:
            datos["error_campo_0"] = str(e).splitlines()[0][:200]
            break
        sub = []
        for _ in range(8):                  # campo_0_0 se puebla un tick despues
            page.wait_for_timeout(400)
            ops = opciones('select[name="campo_0_0"]')
            sub = reales(ops[0]) if ops else []
            if sub:
                break
        datos["areas"][valor] = {"label": texto, "subcampos": dict(sub)}
    try:
        page.click('input[type="submit"][value="Volver"]', timeout=10_000)
    except Exception:
        pass
    return datos


def parsear(page, paginas: list) -> dict:
    secciones: dict = {}
    for html in paginas:
        for s in page.evaluate(PARSER, html):
            destino = secciones.setdefault(s["seccion"], {})
            for r in s["registros"]:
                destino.setdefault(r["href"] or " | ".join(r["campos"]), r)
    return {"publicaciones": [{"seccion": k, "registros": list(v.values())}
                              for k, v in secciones.items()]}


def actualizar(page) -> dict:
    """Relee la lista y reescribe inventario.json desde una sesion abierta."""
    HTML.mkdir(exist_ok=True)
    paginas = bajar_listas(page)
    for i, html in enumerate(paginas, 1):
        (HTML / f"lista-{i:02d}.html").write_text(html, encoding="utf-8")
    inventario = parsear(page, paginas)
    INVENTARIO.write_text(json.dumps(inventario, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    C.log(f"-> {INVENTARIO}")
    resumen(inventario)
    return inventario


def resumen(inventario: dict) -> None:
    for s in inventario["publicaciones"]:
        C.log(f"  {len(s['registros']):>4}  {s['seccion'][:80]}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--offline", action="store_true",
                   help="no entra a SIGEVA: re-parsea el HTML guardado en html/")
    p.add_argument("--sin-areas", action="store_true",
                   help="no releva los combos del área del conocimiento")
    p.add_argument("--sin-catalogo", action="store_true",
                   help="no cosecha los IDs de revistas e instituciones")
    a = p.parse_args()

    with sync_playwright() as pw:
        if a.offline:
            navegador = pw.chromium.launch(headless=True)
            page = navegador.new_page()
            paginas = [f.read_text(encoding="utf-8")
                       for f in sorted(HTML.glob("lista-*.html"))]
            if not paginas:
                sys.exit(f"No hay HTML guardado en {HTML}")
        else:
            # contexto limpio: SIGEVA se traba con estado de sesion acumulado
            navegador = pw.chromium.launch(headless=False)
            page = navegador.new_context(
                viewport={"width": 1400, "height": 1000}).new_page()
            esperar_login(page)
            C.entrar_banco_datos(page)

            HTML.mkdir(exist_ok=True)
            paginas = bajar_listas(page)
            for i, html in enumerate(paginas, 1):
                (HTML / f"lista-{i:02d}.html").write_text(html, encoding="utf-8")
            (HTML / "indice.html").write_text(bajar_indice(page), encoding="utf-8")
            C.log(f"{len(paginas)} páginas de la lista guardadas en {HTML}")

        inventario = parsear(page, paginas)
        INVENTARIO.write_text(json.dumps(inventario, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        C.log(f"-> {INVENTARIO}")
        resumen(inventario)

        if not a.offline and not a.sin_catalogo:
            try:
                cosechar.cosechar_en(page)
            except Exception as e:
                C.log(f"No pude armar el catálogo: {str(e).splitlines()[0][:100]}")
        if not a.offline and not a.sin_areas:
            try:
                datos = relevar_formulario(page)
                AREAS.write_text(json.dumps(datos, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
                C.log(f"-> {AREAS} ({len(datos['areas'])} campos, "
                      f"{len(datos['paises'].get('paisEvento', {}))} países)")
            except Exception as e:
                C.log(f"No pude relevar el formulario: {str(e).splitlines()[0][:100]}")
        navegador.close()


if __name__ == "__main__":
    main()
