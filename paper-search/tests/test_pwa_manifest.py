"""Tests del manifest de la PWA.

Se comprueba lo que los navegadores exigen de verdad para ofrecer instalar la
app, no una lista de campos inventada: nombre, icono de 192 y de 512, un
`display` que no sea `browser`, y un `start_url` dentro del `scope`.
"""

from __future__ import annotations

import json

import pytest

import app as web

#: Campos sin los cuales Chrome no ofrece instalar.
CAMPOS_MINIMOS = ("name", "icons", "start_url", "display")

#: `display` que cuentan como aplicación instalable ("browser" no vale).
DISPLAYS_INSTALABLES = ("standalone", "fullscreen", "minimal-ui")


@pytest.fixture
def cliente():
    web.app.config["TESTING"] = True
    return web.app.test_client()


@pytest.fixture
def manifest(cliente):
    return cliente.get("/manifest.json").get_json()


# ------------------------------------------------------------------ formato


def test_el_manifest_se_sirve(cliente):
    assert cliente.get("/manifest.json").status_code == 200


def test_es_json_valido(cliente):
    crudo = cliente.get("/manifest.json").get_data(as_text=True)

    datos = json.loads(crudo)

    assert isinstance(datos, dict)


def test_se_sirve_con_el_tipo_de_contenido_de_la_especificacion(cliente):
    respuesta = cliente.get("/manifest.json")

    assert "application/manifest+json" in respuesta.headers["Content-Type"]


# -------------------------------------------------- requisitos de instalación


@pytest.mark.parametrize("campo", CAMPOS_MINIMOS)
def test_estan_los_campos_minimos(campo, manifest):
    assert campo in manifest
    assert manifest[campo]


def test_el_display_permite_instalar(manifest):
    """Con `browser` el navegador no ofrece instalar nada."""
    assert manifest["display"] in DISPLAYS_INSTALABLES


def test_hay_un_icono_de_192_y_otro_de_512(manifest):
    """Los dos tamaños que pide Chrome para el icono de la app instalada."""
    tamanos = {icono["sizes"] for icono in manifest["icons"]}

    assert "192x192" in tamanos
    assert "512x512" in tamanos


def test_hay_un_icono_maskable(manifest):
    """Sin `maskable`, Android recorta el icono y se come el dibujo."""
    propositos = {icono.get("purpose") for icono in manifest["icons"]}

    assert "maskable" in propositos


def test_los_iconos_declaran_tipo_y_ruta(manifest):
    for icono in manifest["icons"]:
        assert icono["type"] == "image/png"
        assert icono["src"].startswith("/static/")


def test_el_start_url_esta_dentro_del_scope(manifest):
    assert manifest["start_url"].startswith(manifest["scope"])


def test_tiene_colores_de_tema_y_de_fondo(manifest):
    for campo in ("theme_color", "background_color"):
        assert manifest[campo].startswith("#")
        assert len(manifest[campo]) == 7


# ------------------------------------------------------- los iconos existen


@pytest.mark.parametrize(
    "nombre", ["icono-192.png", "icono-512.png", "icono-maskable-512.png"]
)
def test_cada_icono_se_sirve_de_verdad(cliente, nombre):
    """Un manifest que apunta a un icono que no existe no instala nada."""
    respuesta = cliente.get(f"/static/iconos/{nombre}")

    assert respuesta.status_code == 200
    assert respuesta.headers["Content-Type"].startswith("image/png")


def test_los_iconos_son_png_del_tamano_declarado(cliente, manifest):
    """Se comprueba la cabecera PNG y las dimensiones reales, no el nombre."""
    import struct

    for icono in manifest["icons"]:
        datos = cliente.get(icono["src"]).get_data()
        assert datos[:8] == b"\x89PNG\r\n\x1a\n", icono["src"]
        # La cabecera IHDR trae ancho y alto en los bytes 16..24.
        ancho, alto = struct.unpack(">II", datos[16:24])
        esperado = int(icono["sizes"].split("x")[0])
        assert (ancho, alto) == (esperado, esperado), icono["src"]


# ------------------------------------------------------------ traducción


def test_el_manifest_pasa_por_el_sistema_de_traduccion(cliente):
    """La descripción que se ve al instalar no debe quedar fija en un idioma."""
    es = cliente.get("/manifest.json?idioma=es").get_json()
    en = cliente.get("/manifest.json?idioma=en").get_json()

    assert es["lang"] == "es"
    assert en["lang"] == "en"
    assert es["description"] != en["description"]
    assert "rare diseases" in en["description"]
