"""Tests de la extensión de Chrome.

La extensión es JavaScript y esta suite no tiene navegador, así que aquí no se
ejecuta: lo que se comprueba es su **contrato estático**, que es donde están
los errores que de verdad duelen —un manifest que Chrome rechaza al cargar, un
icono que no existe, una cadena escrita a mano que se salta el sistema de
traducción, o un permiso de más.

Lo que queda sin cubrir, dicho claramente: que el menú contextual aparezca y
que la pestaña se abra. Eso hay que probarlo cargando la extensión sin empaquetar
en `chrome://extensions` (ver el README).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from paper_search.i18n import IDIOMAS, claves_disponibles
from paper_search.locales import comprobar_al_dia

RAIZ_REPO = Path(__file__).resolve().parents[2]
EXT = RAIZ_REPO / "extension"
MANIFEST = EXT / "manifest.json"

#: Los .js de la extensión que escribimos nosotros.
FUENTES_JS = ("background.js", "popup.js", "comun.js")


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------- manifest v3


def test_el_manifest_existe_y_es_json_valido(manifest):
    assert isinstance(manifest, dict)


def test_es_manifest_v3(manifest):
    """MV2 ya no se carga en Chrome."""
    assert manifest["manifest_version"] == 3


@pytest.mark.parametrize(
    "campo", ["manifest_version", "name", "version", "icons", "default_locale"]
)
def test_estan_los_campos_que_chrome_exige(campo, manifest):
    assert campo in manifest
    assert manifest[campo]


def test_la_version_tiene_formato_de_version(manifest):
    """Chrome rechaza el paquete si `version` no son de 1 a 4 números."""
    assert re.fullmatch(r"\d+(\.\d+){0,3}", manifest["version"])


def test_el_service_worker_declarado_existe(manifest):
    ruta = EXT / manifest["background"]["service_worker"]

    assert ruta.is_file()
    # Como usa `import`, tiene que declararse como módulo o Chrome no lo carga.
    assert manifest["background"]["type"] == "module"


def test_el_popup_declarado_existe(manifest):
    assert (EXT / manifest["action"]["default_popup"]).is_file()


# ------------------------------------------------------------------ iconos


def test_los_iconos_declarados_existen(manifest):
    for tamano, relativa in manifest["icons"].items():
        assert (EXT / relativa).is_file(), relativa


def test_estan_los_tres_tamanos_que_pide_chrome(manifest):
    """16 para la barra, 48 para la página de extensiones, 128 para la tienda."""
    assert set(manifest["icons"]) == {"16", "48", "128"}


def test_cada_icono_mide_lo_que_declara(manifest):
    """Se lee la cabecera IHDR del PNG, no el nombre del archivo."""
    import struct

    for tamano, relativa in manifest["icons"].items():
        datos = (EXT / relativa).read_bytes()
        assert datos[:8] == b"\x89PNG\r\n\x1a\n", relativa
        ancho, alto = struct.unpack(">II", datos[16:24])
        assert (ancho, alto) == (int(tamano), int(tamano)), relativa


def test_los_iconos_de_la_extension_salen_del_mismo_svg():
    """Si alguien retoca el SVG y no regenera, la extensión llevaría el viejo."""
    import sys

    sys.path.insert(0, str(RAIZ_REPO / "paper-search" / "herramientas"))
    from generar_iconos import main

    assert main(["--comprobar"]) == 0


# ------------------------------------------------------------- permisos


def test_no_pide_acceso_a_todas_las_urls(manifest):
    """`<all_urls>` en una herramienta médica es inaceptable: daría acceso a
    todo lo que el usuario lee."""
    todos = manifest.get("permissions", []) + manifest.get("host_permissions", [])

    assert "<all_urls>" not in todos
    assert not any("*://*/*" in p for p in todos)


def test_los_permisos_son_los_minimos_justificados(manifest):
    """Cada permiso tiene que tener un motivo escrito en decisions.md."""
    assert manifest["permissions"] == ["contextMenus"]
    assert manifest["host_permissions"] == ["http://127.0.0.1:5000/*"]


def test_el_host_permitido_es_solo_el_servidor_local(manifest):
    for host in manifest["host_permissions"]:
        assert host.startswith("http://127.0.0.1:")


def test_no_lee_el_contenido_de_las_paginas(manifest):
    """`contexts:["selection"]` entrega el texto seleccionado sin tocar la
    página, así que no hacen falta content scripts ni acceso a la pestaña."""
    assert "content_scripts" not in manifest
    for permiso in ("activeTab", "scripting", "tabs", "webNavigation", "history"):
        assert permiso not in manifest.get("permissions", []), permiso


# ------------------------------------------------ i18n: nada escrito a mano


def test_el_default_locale_tiene_su_carpeta(manifest):
    ruta = EXT / "_locales" / manifest["default_locale"] / "messages.json"

    assert ruta.is_file()


def test_hay_un_messages_json_por_idioma():
    for idioma in IDIOMAS:
        assert (EXT / "_locales" / idioma / "messages.json").is_file()


def test_los_locales_estan_al_dia_con_la_fuente():
    """Salen de la fuente única, no son traducciones propias de la extensión."""
    assert comprobar_al_dia() == []


def test_los_locales_llevan_las_mismas_claves_que_la_fuente():
    generado = json.loads(
        (EXT / "_locales" / "es" / "messages.json").read_text(encoding="utf-8")
    )

    assert set(generado) == claves_disponibles()


def test_el_manifest_localiza_su_nombre_y_su_descripcion(manifest):
    """Sin `__MSG_...__` el nombre quedaría fijo en un idioma."""
    for campo in ("name", "description"):
        assert re.fullmatch(r"__MSG_[a-z][a-z0-9_]*__", manifest[campo]), campo


def test_las_claves_que_usa_el_manifest_existen(manifest):
    for campo in ("name", "description"):
        clave = manifest[campo].strip("_")[4:]
        assert clave in claves_disponibles(), clave



def _sin_comentarios(fuente: str) -> str:
    """Quita los comentarios de un .js, respetando las cadenas.

    Hace falta porque varios comentarios explican precisamente lo que NO se
    hace —«navigator.onLine no sirve aquí», «no se apunta a /buscar»— y un
    test que mirase el archivo entero los confundiría con el propio código.
    Cuidado con partir por `//` a lo bruto: `http://127.0.0.1` lo contiene.
    """
    salida = []
    i, n = 0, len(fuente)
    comilla = None
    while i < n:
        c = fuente[i]
        if comilla:
            salida.append(c)
            if c == "\\":
                if i + 1 < n:
                    salida.append(fuente[i + 1])
                i += 2
                continue
            if c == comilla:
                comilla = None
            i += 1
            continue
        if c in "\"'`":
            comilla = c
            salida.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and fuente[i + 1] == "*":
            fin = fuente.find("*/", i + 2)
            i = n if fin == -1 else fin + 2
            continue
        if c == "/" and i + 1 < n and fuente[i + 1] == "/":
            fin = fuente.find("\n", i)
            i = n if fin == -1 else fin
            continue
        salida.append(c)
        i += 1
    return "".join(salida)


def _codigo(nombre: str) -> str:
    return _sin_comentarios((EXT / nombre).read_text(encoding="utf-8"))


def _claves_usadas(fuente: str) -> set[str]:
    return set(re.findall(r'texto\(\s*"([a-z][a-z0-9_]*)"', fuente)) | set(
        re.findall(r'getMessage\(\s*"([a-z][a-z0-9_]*)"', fuente)
    )


def test_todas_las_claves_que_pide_el_javascript_existen():
    """Una clave mal escrita saldría en pantalla como `ext_lo_que_sea`."""
    faltan = {}
    for nombre in FUENTES_JS:
        usadas = _claves_usadas(_codigo(nombre))
        sin_definir = usadas - claves_disponibles()
        if sin_definir:
            faltan[nombre] = sorted(sin_definir)

    assert faltan == {}


def test_el_javascript_de_la_extension_no_lleva_texto_traducible():
    """Mismo test que prohíbe literales en conexion.js: si un mensaje se
    escribe aquí, se salta la fuente única y no se traduce nunca."""
    prohibidos = (
        "paper-search no", "is not running", "Sin conexión", "No internet",
        "run.bat", "Buscar en", "Search for", "Escribe un", "Type a",
        "Comprobando", "Checking",
    )
    for nombre in FUENTES_JS:
        fuente = (EXT / nombre).read_text(encoding="utf-8")
        # Se miran solo las cadenas literales, no los comentarios: estos
        # explican el porqué y sí pueden nombrar «run.bat».
        literales = re.findall(r'"([^"\n]*)"', fuente) + re.findall(r"'([^'\n]*)'", fuente)
        for literal in literales:
            for prohibido in prohibidos:
                assert prohibido not in literal, f"{nombre}: {literal!r}"


def test_el_popup_no_trae_texto_escrito_en_el_html():
    """Los elementos nacen vacíos y los rellena popup.js desde _locales."""
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    textos = [t.strip() for t in re.findall(r">([^<>]+)<", sin_comentarios)]

    assert [t for t in textos if t] == []


# --------------------------------- respeta lo que ya hace el servidor


def test_la_extension_apunta_a_la_portada_y_no_a_buscar():
    """La búsqueda tiene que seguir siendo el POST del servidor: un GET a
    /buscar gastaría cuota y llamadas de verdad al recargarse o precargarse."""
    comun = _codigo("comun.js")

    assert 'new URL(SERVIDOR + "/")' in comun
    # En el código, no en los comentarios: varios explican por qué NO se
    # apunta ahí, y nombrarlo no es lo mismo que usarlo.
    assert "/buscar" not in comun


def test_la_extension_no_reimplementa_los_guardarrailes():
    """El alcance y el aviso de idioma son del servidor. Si aparecieran aquí,
    habría dos implementaciones de la misma regla."""
    for nombre in FUENTES_JS:
        fuente = _codigo(nombre)
        for señal in ("alc_aviso", "idi_aviso", "detectar_idioma", "enfermedades raras"):
            assert señal not in fuente, f"{nombre}: {señal}"


def test_usa_el_mismo_endpoint_de_estado_que_la_pwa():
    """Una sola forma de saber si el servidor vive, no dos."""
    from paper_search.pwa import RUTA_ESTADO

    comun = _codigo("comun.js")

    assert f'RUTA_ESTADO = "{RUTA_ESTADO}"' in comun
    # No aparece en el código; sí en un comentario, explicando por qué no vale.
    assert "navigator.onLine" not in comun


def test_el_host_del_manifest_coincide_con_el_del_javascript(manifest):
    """Si no coinciden, el ping fallaría por permisos y parecería un servidor
    caído: el peor de los fallos, porque miente sobre la causa."""
    comun = _codigo("comun.js")
    servidor = re.search(r'SERVIDOR = "([^"]+)"', comun).group(1)

    assert any(host.startswith(servidor) for host in manifest["host_permissions"])
