"""Maquetación en pantalla pequeña.

Sin navegador no se puede medir el renderizado, así que aquí se comprueban las
condiciones que SÍ se pueden verificar y que son las que rompen de verdad en un
móvil: que exista la declaración de viewport, que ninguna clase de las
plantillas se quede sin estilo (eso dejaba botones de ~20 px imposibles de
tocar), y que estén las reglas concretas que evitan el zoom automático de iOS y
el desbordamiento horizontal.

Lo que queda sin cubrir: el aspecto real. Eso hay que mirarlo en el móvil o en
el modo dispositivo del navegador.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import app as web
from paper_search import abrir_db

RAIZ = Path(__file__).resolve().parents[1]
CSS = (RAIZ / "static" / "paper-search.css").read_text(encoding="utf-8")
CSS_BASE = (RAIZ / "static" / "classical.css").read_text(encoding="utf-8")

PAGINAS = ["/", "/favoritos", "/offline"]

#: Ancho de referencia. Un móvil pequeño en uso normal.
ANCHO_MOVIL = 360

#: Mínimo recomendado para tocar con el dedo sin fallar.
TOQUE_MINIMO = 44


@pytest.fixture
def cliente(monkeypatch):
    web.app.config["TESTING"] = True
    monkeypatch.setattr(web, "abrir_db", lambda: abrir_db(":memory:"))
    return web.app.test_client()


def texto(respuesta) -> str:
    return respuesta.get_data(as_text=True)


# ------------------------------------------------------------- viewport


@pytest.mark.parametrize("ruta", PAGINAS)
def test_cada_pagina_declara_el_viewport(cliente, ruta):
    """Sin esto el móvil renderiza a 980 px y encoge: todo sale ilegible."""
    cuerpo = texto(cliente.get(ruta))

    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in cuerpo


@pytest.mark.parametrize("ruta", PAGINAS)
def test_ninguna_pagina_impide_el_zoom(cliente, ruta):
    """`user-scalable=no` o un maximum-scale bajo son un problema de
    accesibilidad: quien necesita ampliar no puede."""
    cuerpo = texto(cliente.get(ruta))

    assert "user-scalable=no" not in cuerpo
    assert "maximum-scale=1" not in cuerpo


# ---------------------------------- ninguna clase de plantilla sin estilo


def _clases_de(html: str) -> set[str]:
    clases = set()
    for grupo in re.findall(r'class="([^"{}]+)"', html):
        clases.update(grupo.split())
    return {c for c in clases if c.startswith("ps-")}


@pytest.mark.parametrize("ruta", PAGINAS)
def test_toda_clase_ps_de_las_paginas_tiene_estilo(cliente, ruta):
    """El fallo que esto caza ya ocurrió: ocho clases añadidas en las fases
    3-5 se quedaron sin ninguna regla, y en el móvil eran botones sin tamaño.

    Se excluyen las que son solo gancho para el JavaScript y no pintan nada.
    """
    solo_gancho = {"ps-num"}
    hoja = CSS + CSS_BASE

    sin_estilo = [
        clase for clase in _clases_de(texto(cliente.get(ruta)))
        if clase not in solo_gancho and f".{clase}" not in hoja
    ]

    assert sin_estilo == []


# --------------------------------------- reglas concretas que arreglan móvil


def test_hay_un_bloque_para_pantallas_pequenas():
    assert re.search(r"@media\s*\(max-width:\s*\d+px\)", CSS)


def test_los_campos_llegan_a_16px_en_movil():
    """Safari en iOS hace zoom al enfocar un campo de menos de 16 px y deja la
    página descuadrada. Es el detalle que más se nota al usarlo de verdad."""
    bloque = _bloque_movil()

    assert re.search(r"\.input[^{]*\{[^}]*font-size:\s*16px", bloque)


def test_el_resumen_deja_de_ir_justificado_en_movil():
    """El texto justificado en una columna estrecha abre ríos enormes, y más
    con términos médicos que no se parten."""
    bloque = _bloque_movil()

    assert re.search(r"\.ps-summary p[^{]*\{[^}]*text-align:\s*left", bloque)


def test_los_botones_tactiles_llegan_al_minimo_recomendado():
    for selector in (".ps-fav", ".ps-exportar .btn"):
        patron = re.escape(selector) + r"[^{]*\{[^}]*min-height:\s*(\d+)px"
        encontrado = re.search(patron, CSS)
        assert encontrado, selector
        assert int(encontrado.group(1)) >= TOQUE_MINIMO, selector


def test_los_campos_numericos_dejan_de_reservar_ancho_fijo_en_movil():
    """Con `flex: 0 0 130px` los dos campos se comían la fila y el botón de
    buscar se quedaba sin sitio en 360 px."""
    bloque = _bloque_movil()

    assert re.search(r"\.ps-field-num[^{]*\{[^}]*flex:\s*1 1", bloque)


def test_los_titulos_largos_no_desbordan():
    """Un término médico largo sin espacios sacaría la página de la pantalla."""
    assert re.search(r"overflow-wrap:\s*anywhere", CSS)


def _bloque_movil() -> str:
    """El contenido del @media de pantalla pequeña."""
    inicio = CSS.index("@media (max-width: 640px)")
    return CSS[inicio:]


# ------------------------------------- nada de esto cambia el escritorio


def test_las_reglas_de_movil_viven_dentro_del_media_query():
    """Si se colaran fuera, cambiarían también el escritorio, que ya funciona.

    Se mira selector por selector y no por substring: `.ps-summary p` ya
    llevaba `font-size: 16px` de antes para el cuerpo del resumen, y eso no
    tiene nada que ver con la regla de móvil que sube los CAMPOS a 16 px.
    """
    fuera = CSS[: CSS.index("@media (max-width: 640px)")]

    # La subida de los campos a 16px es solo para evitar el zoom de iOS.
    assert not re.search(r"\.input[^{]*\{[^}]*font-size:\s*16px", fuera)
    # Y el resumen sigue justificado en escritorio, como estaba.
    assert re.search(r"\.ps-summary p[^{]*\{[^}]*text-align:\s*justify", fuera)
    assert not re.search(r"\.ps-summary p[^{]*\{[^}]*text-align:\s*left", fuera)


def test_el_ancho_maximo_de_la_columna_sigue_intacto():
    """En escritorio la columna sigue siendo la de siempre."""
    assert ".ps-wrap { max-width: 760px" in CSS


def test_el_texto_del_portapapeles_no_asume_teclado():
    """Sobre la red local el portapapeles queda bloqueado y este es el mensaje
    que sale; en un móvil, «Ctrl+C» no significa nada."""
    from paper_search import traducir

    for idioma, pista in (("es", "pulsado"), ("en", "hold")):
        assert pista in traducir("exp_fallo", idioma).lower()
