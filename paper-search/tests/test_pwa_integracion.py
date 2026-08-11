"""Integración de la PWA en las páginas ya traducidas.

Se comprueba que las páginas declaran el manifest y el tema, que registran el
service worker, y —lo que más importa— que **los avisos de sin conexión pasan
por el sistema de traducción** del punto 5.1 en vez de ser literales sueltos.
"""

from __future__ import annotations

import json
import re

import pytest

import app as web
from paper_search import Paper, ResultadoBusqueda, abrir_db, traducir
from paper_search.pwa import RUTA_ESTADO

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="SCN1A variants in Dravet syndrome",
        autores=("Garcia A",),
        revista="Epilepsia",
        fecha="2024-03-15",
        orden_relevancia=0,
    ),
)


@pytest.fixture
def cliente(monkeypatch):
    web.app.config["TESTING"] = True
    monkeypatch.setattr(web, "abrir_db", lambda: abrir_db(":memory:"))
    return web.app.test_client()


def texto(respuesta) -> str:
    return respuesta.get_data(as_text=True)


PAGINAS = ["/", "/favoritos"]


# --------------------------------------------------- manifest y tema


@pytest.mark.parametrize("ruta", PAGINAS + ["/offline"])
def test_cada_pagina_enlaza_el_manifest(cliente, ruta):
    """Sin `<link rel="manifest">` el navegador no ofrece instalar nada."""
    cuerpo = texto(cliente.get(ruta))

    assert '<link rel="manifest" href="/manifest.json">' in cuerpo


@pytest.mark.parametrize("ruta", PAGINAS)
def test_cada_pagina_declara_el_color_de_tema(cliente, ruta):
    cuerpo = texto(cliente.get(ruta))

    assert re.search(r'<meta name="theme-color" content="#[0-9a-f]{6}">', cuerpo)


@pytest.mark.parametrize("ruta", PAGINAS)
def test_cada_pagina_declara_su_icono(cliente, ruta):
    assert 'rel="icon"' in texto(cliente.get(ruta))


# ------------------------------------------------ registro del service worker


@pytest.mark.parametrize("ruta", PAGINAS)
def test_las_paginas_registran_el_service_worker(cliente, ruta):
    cuerpo = texto(cliente.get(ruta))

    assert "conexion.js" in cuerpo


def test_el_registro_apunta_a_la_raiz_y_no_falla_si_no_hay_soporte(cliente):
    """Un navegador sin service workers debe seguir funcionando igual."""
    fuente = texto(cliente.get("/static/conexion.js"))

    assert "'serviceWorker' in navigator" in fuente
    assert "navigator.serviceWorker.register('/sw.js', { scope: '/' })" in fuente
    assert ".catch(" in fuente


# ------------------------------- los avisos pasan por el sistema de traducción


@pytest.mark.parametrize("ruta", PAGINAS)
def test_los_avisos_de_conexion_estan_en_la_pagina_pero_ocultos(cliente, ruta):
    """Nacen ocultos: solo se encienden si de verdad hay un problema."""
    cuerpo = texto(cliente.get(ruta))

    assert 'id="ps-aviso-copia" hidden' in cuerpo
    assert 'id="ps-aviso-internet" hidden' in cuerpo


def textos_js_de(cliente, ruta):
    """Extrae y decodifica el PS_TEXTOS incrustado en la página.

    Se parsea en vez de buscar el substring crudo porque `tojson` escapa los
    no-ASCII (`conexión` → `conexi\u00f3n`): lo que se quiere comprobar es el
    dato, no cómo viene escapado.
    """
    cuerpo = texto(cliente.get(ruta))
    crudo = re.search(r"var PS_TEXTOS = (\{.*?\});", cuerpo, re.S).group(1)
    return json.loads(crudo)


@pytest.mark.parametrize("ruta", PAGINAS)
def test_los_textos_de_conexion_viajan_traducidos(cliente, ruta):
    """Requisito explícito: nada de un texto suelto fijo en un idioma."""
    es = textos_js_de(cliente, f"{ruta}?idioma=es")
    en = textos_js_de(cliente, f"{ruta}?idioma=en")

    assert "Sin conexión a internet" in es["off_sin_internet"]
    assert "No internet connection" in en["off_sin_internet"]
    assert es["off_sin_internet"] != en["off_sin_internet"]


@pytest.mark.parametrize(
    "clave",
    ["off_copia_aviso", "off_sin_internet", "off_buscar_sin_conexion", "off_solo_lectura"],
)
def test_cada_texto_de_conexion_sale_de_la_fuente_de_traduccion(cliente, clave):
    textos = textos_js_de(cliente, "/")

    assert clave in textos
    assert textos[clave] == traducir(clave, "es")


def test_el_javascript_de_conexion_no_lleva_literales_de_usuario(cliente):
    """Todos los mensajes salen de PS_TEXTOS; aquí no se escribe ninguno."""
    fuente = texto(cliente.get("/static/conexion.js"))

    for prohibido in ("Sin conexión", "No internet", "run.bat", "Solo lectura"):
        assert prohibido not in fuente


# --------------------------------- la búsqueda sin red avisa y no se cuelga


def test_el_formulario_comprueba_la_conexion_antes_de_enviar(cliente):
    """Sin esto, sin red el usuario se queda mirando el spinner hasta que el
    navegador se rinde y enseña su propia página de error."""
    fuente = texto(cliente.get("/static/conexion.js"))

    assert "navigator.onLine === false" in fuente
    assert "evento.preventDefault()" in fuente
    assert "off_buscar_sin_conexion" in fuente


def test_el_guard_corre_antes_que_el_spinner(cliente):
    """Se registra en captura para adelantarse al handler que enciende el
    estado «Buscando…»: si no, se vería el spinner y luego el aviso."""
    fuente = texto(cliente.get("/static/conexion.js"))

    assert "stopImmediatePropagation" in fuente
    assert re.search(r"\}, true\);\s*//.*captura", fuente)


def test_el_aviso_de_buscar_sin_red_explica_que_los_favoritos_si_van():
    """El mensaje honesto: lo que falla es PubMed, no toda la app."""
    es = traducir("off_buscar_sin_conexion", "es")
    en = traducir("off_buscar_sin_conexion", "en")

    assert "favoritos" in es.lower()
    assert "favourites" in en.lower()
    assert "PubMed" in es and "PubMed" in en


# -------------------------------- la copia guardada se marca y no se edita


def test_las_paginas_llevan_la_marca_de_cuando_se_generaron(cliente):
    """Es la única pista de la antigüedad cuando la sirve el service worker."""
    cuerpo = texto(cliente.get("/"))

    marca = re.search(r'<meta name="ps-generado" content="([^"]+)">', cuerpo)
    assert marca
    assert marca.group(1).startswith("20")  # ISO


def test_la_copia_guardada_deshabilita_lo_que_escribe(cliente):
    """Con el servidor apagado, un formulario habilitado fallaría en silencio."""
    fuente = texto(cliente.get("/static/conexion.js"))

    assert "campo.disabled = true" in fuente
    assert "off_copia_aviso" in fuente


def test_la_deteccion_no_se_fia_solo_de_navigator_online(cliente):
    """`navigator.onLine` dice si hay internet, no si Flask está vivo: se
    equivocaría en los dos sentidos. Hace falta preguntar al servidor."""
    fuente = texto(cliente.get("/static/conexion.js"))

    assert "PS_RUTA_ESTADO" in fuente
    assert "AbortController" in fuente  # con timeout, para no esperar eternamente


@pytest.mark.parametrize("ruta", PAGINAS)
def test_las_paginas_saben_a_donde_preguntar_por_el_servidor(cliente, ruta):
    cuerpo = texto(cliente.get(ruta))

    assert f'PS_RUTA_ESTADO = "{RUTA_ESTADO}"' in cuerpo


# ---------------------------------------- nada de esto rompe lo que ya había


def test_la_busqueda_sigue_funcionando(cliente, monkeypatch):
    monkeypatch.setattr(
        web,
        "buscar_y_resumir",
        lambda termino, **kw: ResultadoBusqueda(
            query=termino, papers=PAPERS, resumen="Hallazgo [PMID: 38123456].", dias=365
        ),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert "38123456" in cuerpo
    assert ">Resumen<" in cuerpo
