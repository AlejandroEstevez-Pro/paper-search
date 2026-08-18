"""Tests de la extensión de Chrome.

La extensión es JavaScript y esta suite no tiene navegador, así que aquí no se
ejecuta: lo que se comprueba es su **contrato estático**, que es donde están
los errores que de verdad duelen —un manifest que Chrome rechaza al cargar, un
icono que no existe, una cadena escrita a mano que se salta el sistema de
traducción, o un permiso de más.

Este commit cubre el manifest: que Chrome lo acepte, que los iconos declarados
existan y midan lo que dicen, y que no se cuele ningún permiso de más. Lo que
la extensión hace llega en el commit siguiente, con sus propios tests.
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
