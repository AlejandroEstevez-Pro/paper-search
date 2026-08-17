"""Tests del icono de la aplicación.

El SVG (`static/iconos/paper-search-icon.svg`) es la fuente y los PNG son
derivados. Lo que se protege aquí es que no se separen, que el icono siga
usando los tokens del sistema de diseño, y las dos propiedades geométricas que
hacen que se vea bien donde se usa: que quepa dentro de la máscara circular de
Android/PWA y que el `maskable` vaya a sangre.

Los PNG se comparan regenerándolos, no por su contenido concreto: si alguien
retoca el SVG y no ejecuta `herramientas/generar_iconos.py`, estos tests lo
dicen en vez de dejar iconos viejos en el manifest.
"""

from __future__ import annotations

import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import app as web

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "static" / "iconos"
SVG = CARPETA / "paper-search-icon.svg"
SVG_TRANSPARENTE = CARPETA / "paper-search-icon-transparent.svg"

sys.path.insert(0, str(RAIZ / "herramientas"))

#: Tokens de marca del sistema de diseño (ver `static/classical.css`).
NEGRO = "#201f1d"   # --color-text
ORO = "#b68235"     # --color-accent
HUESO = "#f3f2f2"   # --color-bg

pytest.importorskip("PIL", reason="Pillow solo hace falta para generar iconos")


@pytest.fixture
def cliente():
    web.app.config["TESTING"] = True
    return web.app.test_client()


# --------------------------------------------------------------- la fuente


def test_el_svg_del_icono_existe_y_es_xml_valido():
    raiz = ET.parse(SVG).getroot()

    assert raiz.get("viewBox") == "0 0 512 512"


def test_hay_una_variante_transparente_para_fondos_claros():
    """La del fondo redondeado no sirve sobre papel o sobre la web en claro."""
    raiz = ET.parse(SVG_TRANSPARENTE).getroot()

    assert raiz.get("viewBox") == "0 0 512 512"
    # Sin el rectángulo de fondo: eso es lo que la hace transparente.
    assert b'rx="112"' not in SVG_TRANSPARENTE.read_bytes()


@pytest.mark.parametrize("archivo", [SVG, SVG_TRANSPARENTE])
def test_el_icono_usa_los_tokens_del_sistema_de_diseno(archivo):
    """Si el icono se sale de la paleta, desentona con el resto de la interfaz."""
    contenido = archivo.read_text(encoding="utf-8")
    colores = set(re.findall(r"#[0-9a-f]{6}", contenido))

    assert colores <= {NEGRO, ORO, HUESO}, colores


def test_esos_tokens_son_los_que_declara_el_css():
    """Comprobación cruzada: los colores del icono salen del CSS, no de la nada."""
    css = (RAIZ / "static" / "classical.css").read_text(encoding="utf-8")

    assert f"--color-text: {NEGRO}" in css
    assert f"--color-accent: {ORO}" in css
    assert f"--color-bg: {HUESO}" in css


# ------------------------------------------- los PNG derivan del SVG de verdad


def test_los_png_estan_al_dia_con_el_svg():
    """Si alguien retoca el SVG y no regenera, el manifest serviría lo viejo."""
    from generar_iconos import main

    assert main(["--comprobar"]) == 0, (
        "Ejecuta `python herramientas/generar_iconos.py`"
    )


def test_el_generador_falla_ante_un_primitivo_que_no_sabe_dibujar(tmp_path):
    """Mejor fallar que dibujar de menos en silencio: un icono al que le falta
    un trazo se colaría hasta la barra de tareas sin que nadie lo notase."""
    from generar_iconos import IconoError
    import generar_iconos

    raro = tmp_path / "raro.svg"
    raro.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
        '<path d="M0 0 L512 512" fill="#201f1d"/></svg>',
        encoding="utf-8",
    )
    original = generar_iconos.SVG
    generar_iconos.SVG = raro
    try:
        with pytest.raises(IconoError, match="path"):
            generar_iconos.dibujar(tmp_path / "x.png", 64, True)
    finally:
        generar_iconos.SVG = original


# ------------------------------------------------------ geometría que importa


def _extremo_desde_el_centro(imagen):
    """Distancia del píxel dibujado más lejano al centro, en píxeles."""
    lado = imagen.size[0]
    centro = (lado - 1) / 2
    fondo = imagen.getpixel((1, 1))
    pixeles = list(imagen.getdata())

    lejos = 0.0
    for i, p in enumerate(pixeles):
        if p[3] <= 8:
            continue
        if abs(p[0] - fondo[0]) + abs(p[1] - fondo[1]) + abs(p[2] - fondo[2]) <= 30:
            continue
        x, y = i % lado, i // lado
        lejos = max(lejos, math.hypot(x - centro, y - centro))
    return lejos


def test_el_dibujo_cabe_en_la_mascara_circular(tmp_path):
    """Android y Chrome recortan el icono `maskable` a un círculo del 80 % del
    lado. Lo que se salga de ahí se pierde, y el mango de la lupa es la parte
    más expuesta."""
    from PIL import Image
    from generar_iconos import dibujar

    destino = tmp_path / "m.png"
    dibujar(destino, 192, esquinas_redondeadas=False)
    imagen = Image.open(destino).convert("RGBA")

    radio_seguro = 0.4 * 192
    extremo = _extremo_desde_el_centro(imagen)

    assert extremo < radio_seguro, f"{extremo:.1f} >= {radio_seguro}"
    # Y con holgura de sobra, no rozando el límite.
    assert extremo < radio_seguro * 0.95


def test_el_maskable_va_a_sangre_y_el_normal_lleva_esquinas_redondeadas(cliente):
    """Al `maskable` lo recorta el sistema operativo: si además llevara las
    esquinas redondas del SVG, se recortaría dos veces y quedaría mordido."""
    from PIL import Image
    import io as _io

    def esquina(nombre):
        datos = cliente.get(f"/static/iconos/{nombre}").get_data()
        return Image.open(_io.BytesIO(datos)).convert("RGBA").getpixel((1, 1))

    assert esquina("icono-maskable-512.png")[3] == 255  # opaca, a sangre
    assert esquina("icono-512.png")[3] == 0             # transparente, redondeada


def test_el_trazo_sobrevive_a_tamano_favicon(tmp_path):
    """A 16 px el icono tiene que seguir leyéndose: es el tamaño de la pestaña."""
    from PIL import Image
    from generar_iconos import dibujar

    destino = tmp_path / "16.png"
    dibujar(destino, 16, esquinas_redondeadas=True)
    imagen = Image.open(destino).convert("RGBA")

    dorados = [
        p for p in imagen.getdata()
        if p[3] > 128 and p[0] > 120 and p[1] > 80 and p[2] < 110
    ]

    assert len(dorados) >= 15, f"solo {len(dorados)} píxeles de lupa a 16 px"



def test_ya_no_queda_ningun_icono_placeholder():
    """Los placeholders usaban tonos de la rampa (#2d2b2b, #facb8d) en vez de
    los tokens de marca. Si reaparecen, es que se coló el icono viejo."""
    for archivo in (SVG, SVG_TRANSPARENTE):
        contenido = archivo.read_text(encoding="utf-8").lower()
        assert "#2d2b2b" not in contenido
        assert "#facb8d" not in contenido
