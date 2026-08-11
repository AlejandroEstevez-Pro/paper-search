"""Tests del service worker y de su política de caché.

**Qué se prueba y qué no.** El `sw.js` es JavaScript y esta suite no tiene
navegador ni Node, así que su mecánica (`caches.match`, `fetch`) no se ejecuta
aquí. Por eso la parte que DECIDE —qué estrategia le toca a cada petición y qué
se precachea— vive en `pwa.py`, en Python, y es la que se prueba de verdad; el
`sw.js` se limita a aplicarla.

Lo que queda sin cubrir por esta suite, dicho claramente: que el navegador
registre el worker y que `caches` se comporte como se espera. Eso hay que
mirarlo a mano en las herramientas de desarrollo del navegador.
"""

from __future__ import annotations

import json
import re

import pytest

import app as web
from paper_search.pwa import (
    ESTRATEGIA_ESTATICO,
    ESTRATEGIA_RED_PRIMERO,
    ESTRATEGIA_SIN_CACHE,
    RUTA_ESTADO,
    RUTA_OFFLINE,
    VERSION_CACHE,
    estrategia_para,
    politica,
    recursos_a_precachear,
)


@pytest.fixture
def cliente():
    web.app.config["TESTING"] = True
    return web.app.test_client()


def texto(respuesta) -> str:
    return respuesta.get_data(as_text=True)


# ------------------------------------------------- la regla que manda: POST


@pytest.mark.parametrize("metodo", ["POST", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("ruta", ["/", "/buscar", "/favoritos", "/static/x.css"])
def test_nada_que_no_sea_get_se_cachea_jamas(metodo, ruta):
    """Un POST servido de caché sería inventar un resultado.

    Da igual la ruta: una búsqueda que no se hizo o una nota que no se guardó
    no se sirven nunca desde caché, ni cuando el fallo es de red.
    """
    assert estrategia_para(ruta, metodo) == ESTRATEGIA_SIN_CACHE


def test_las_rutas_que_cambian_estado_no_se_cachean():
    for ruta in ("/buscar", "/favoritos/alternar", "/favoritos/nota", "/favoritos/quitar"):
        assert estrategia_para(ruta, "POST") == ESTRATEGIA_SIN_CACHE


# ------------------------------------------------------------- estrategias


@pytest.mark.parametrize(
    "ruta",
    [
        "/static/classical.css",
        "/static/paper-search.css",
        "/static/iconos/icono-192.png",
        "/manifest.json",
    ],
)
def test_los_estaticos_van_a_cache_primero(ruta):
    """Es lo que hace que un recurso cacheado se sirva sin red."""
    assert estrategia_para(ruta) == ESTRATEGIA_ESTATICO


@pytest.mark.parametrize("ruta", ["/", "/favoritos", RUTA_OFFLINE])
def test_las_navegaciones_van_a_red_primero(ruta):
    """Manda el servidor; la copia guardada es solo la reserva."""
    assert estrategia_para(ruta) == ESTRATEGIA_RED_PRIMERO


def test_el_endpoint_de_estado_nunca_se_cachea():
    """Una respuesta guardada diría que el servidor vive cuando está apagado."""
    assert estrategia_para(RUTA_ESTADO) == ESTRATEGIA_SIN_CACHE


def test_una_ruta_desconocida_no_se_cachea():
    """Ante la duda, no se guarda: se prefiere fallar a servir algo viejo."""
    assert estrategia_para("/algo/que/no/existe") == ESTRATEGIA_SIN_CACHE


def test_la_query_no_cambia_la_estrategia():
    assert estrategia_para("/?idioma=en") == ESTRATEGIA_RED_PRIMERO
    assert estrategia_para("/static/a.css?v=2") == ESTRATEGIA_ESTATICO


# ------------------------------------------ un recurso cacheado se sirve sin red


def test_todo_lo_precacheado_existe_de_verdad(cliente):
    """Si una ruta del precache da 404, `cache.addAll` falla y NO se instala
    el service worker: se queda sin caché entera, no solo sin ese recurso."""
    for ruta in recursos_a_precachear():
        assert cliente.get(ruta).status_code == 200, ruta


def test_lo_precacheado_es_justo_lo_que_hace_falta_sin_servidor():
    """El CSS, los iconos y la página de reserva. Nada de contenido."""
    precache = set(recursos_a_precachear())

    assert RUTA_OFFLINE in precache
    assert any(r.endswith(".css") for r in precache)
    assert any(r.endswith(".png") for r in precache)
    # Ni resultados ni favoritos: eso solo se guarda al visitarlo de verdad.
    assert "/favoritos" not in precache
    assert not any("buscar" in r for r in precache)


def test_un_estatico_precacheado_se_serviria_sin_red():
    """Las dos condiciones juntas: está guardado y su estrategia es caché
    primero. Es lo que permite que se sirva con el servidor apagado."""
    for ruta in recursos_a_precachear():
        if ruta == RUTA_OFFLINE:
            continue
        assert estrategia_para(ruta) == ESTRATEGIA_ESTATICO, ruta


@pytest.mark.parametrize("ruta", ["/", "/favoritos"])
def test_los_estaticos_que_usan_las_paginas_estan_precacheados(cliente, ruta):
    """Si se añade un CSS o un JS a las plantillas y se olvida en el precache,
    con el servidor apagado la página se vería sin estilos o —peor— sin el
    aviso de que es una copia y con los formularios habilitados."""
    cuerpo = texto(cliente.get(ruta))
    usados = set(re.findall(r'(?:href|src)="(/static/[^"?]+)"', cuerpo))

    assert usados
    assert usados <= set(recursos_a_precachear()), sorted(
        usados - set(recursos_a_precachear())
    )


# -------------------------------------------------------- la ruta /sw.js


def test_el_service_worker_se_sirve(cliente):
    assert cliente.get("/sw.js").status_code == 200


def test_se_sirve_como_javascript(cliente):
    tipo = cliente.get("/sw.js").headers["Content-Type"]

    assert "javascript" in tipo


def test_se_sirve_desde_la_raiz_para_tener_alcance_completo(cliente):
    """Desde /static/ su alcance sería /static/ y no vería ni la portada."""
    respuesta = cliente.get("/sw.js")

    assert respuesta.headers.get("Service-Worker-Allowed") == "/"


def test_el_service_worker_no_se_cachea_en_el_navegador(cliente):
    """Sin esto el navegador podría quedarse con un worker viejo hasta 24 h."""
    assert "no-cache" in cliente.get("/sw.js").headers.get("Cache-Control", "")


def test_la_politica_viaja_dentro_del_service_worker(cliente):
    """Lo que se probó en Python es lo mismo que aplica el JavaScript."""
    cuerpo = texto(cliente.get("/sw.js"))

    crudo = re.search(r"const POLITICA = (\{.*?\});", cuerpo, re.S).group(1)
    incrustada = json.loads(crudo)

    assert incrustada == politica()


def test_el_service_worker_no_intercepta_lo_que_no_debe(cliente):
    """Comprobación estructural: la salida temprana de `sin_cache` sigue ahí."""
    cuerpo = texto(cliente.get("/sw.js"))

    assert "if (estrategia === 'sin_cache') return;" in cuerpo
    assert "peticion.method !== 'GET'" in cuerpo


def test_la_version_de_la_cache_esta_en_el_nombre(cliente):
    """Sin versión en el nombre, subir un CSS dejaría el viejo para siempre."""
    cuerpo = texto(cliente.get("/sw.js"))

    assert VERSION_CACHE in cuerpo
    assert "caches.delete" in cuerpo  # y las viejas se borran al activar


# ------------------------------------------------------- /api/estado


def test_el_endpoint_de_estado_responde(cliente):
    respuesta = cliente.get(RUTA_ESTADO)

    assert respuesta.status_code == 200
    assert respuesta.get_json()["estado"] == "vivo"


def test_el_endpoint_de_estado_pide_no_guardarse(cliente):
    assert "no-store" in cliente.get(RUTA_ESTADO).headers.get("Cache-Control", "")


# --------------------------------------------------------- página offline


def test_la_pagina_offline_se_sirve(cliente):
    assert cliente.get(RUTA_OFFLINE).status_code == 200


def test_la_pagina_offline_lleva_los_dos_idiomas_dentro(cliente):
    """Es la única página que debe funcionar con el servidor apagado, así que
    no puede pedirle la traducción a nadie: la lleva puesta."""
    cuerpo = texto(cliente.get(RUTA_OFFLINE))

    assert "PS_OFFLINE" in cuerpo
    assert "paper-search no está en marcha" in cuerpo
    assert "paper-search is not running" in cuerpo


def test_la_pagina_offline_explica_como_arrancar_el_servidor(cliente):
    """El mensaje útil no es «sin conexión», es «arráncalo con run.bat»."""
    cuerpo = texto(cliente.get(RUTA_OFFLINE))

    assert "run.bat" in cuerpo


def test_los_textos_offline_salen_del_sistema_de_traduccion(cliente):
    """Ni un literal suelto: vienen de i18n/<idioma>.json."""
    from paper_search import traducir

    cuerpo = texto(cliente.get(RUTA_OFFLINE))

    assert traducir("off_titulo", "es") in cuerpo
    assert traducir("off_titulo", "en") in cuerpo


def test_la_pagina_offline_solo_usa_recursos_precacheados(cliente):
    """Si tirase de algo no precacheado, se vería rota justo cuando se usa."""
    cuerpo = texto(cliente.get(RUTA_OFFLINE))
    recursos = set(re.findall(r'(?:href|src)="(/static/[^"]+)"', cuerpo))

    assert recursos <= set(recursos_a_precachear())
