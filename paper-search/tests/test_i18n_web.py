"""La web en dos idiomas: conmutación, persistencia y degradación.

Se comprueba lo que pidió la especificación: que cambiar de idioma se refleje
en los textos correctos, y que un texto que falte en un idioma no rompa la
página. Lo segundo se prueba con una fuente incompleta de verdad, no de
palabra: se sustituye el cargador y se pide la página real.
"""

from __future__ import annotations

import re

import pytest

import app as web
from paper_search import Paper, ResultadoBusqueda, abrir_db
from paper_search import i18n as mod

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="SCN1A variants in Dravet syndrome",
        autores=("Garcia A",),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="Cohorte de 42 pacientes.",
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


def buscar_falsa(monkeypatch, resultado=None):
    resultado = resultado or ResultadoBusqueda(
        query="SCN1A", papers=PAPERS, resumen="Hallazgo [PMID: 38123456].", dias=365
    )
    monkeypatch.setattr(web, "buscar_y_resumir", lambda termino, **kw: resultado)


# -------------------------------------------------------- cambio de idioma


def test_por_defecto_la_web_sale_en_espanol(cliente):
    cuerpo = texto(cliente.get("/"))

    assert '<html lang="es"' in cuerpo
    assert 'id="boton">Buscar</button>' in cuerpo
    assert "Gen, síndrome o término" in cuerpo


def test_el_parametro_de_url_cambia_el_idioma(cliente):
    cuerpo = texto(cliente.get("/?idioma=en"))

    assert '<html lang="en"' in cuerpo
    assert 'id="boton">Search</button>' in cuerpo
    assert "Gene, syndrome or term" in cuerpo
    assert "Gen, síndrome o término" not in cuerpo


def test_el_cambio_alcanza_titulo_avisos_y_navegacion(cliente):
    cuerpo = texto(cliente.get("/?idioma=en"))

    assert "<title>paper-search — PubMed in plain language</title>" in cuerpo
    assert "This is not a diagnostic tool" in cuerpo
    assert "My favourites" in cuerpo
    assert "Advanced search" in cuerpo


def test_la_vista_de_favoritos_tambien_cambia(cliente):
    cuerpo = texto(cliente.get("/favoritos?idioma=en"))

    assert "<h1>My favourites</h1>" in cuerpo
    assert "You have not saved any papers yet" in cuerpo


def test_los_resultados_de_una_busqueda_salen_traducidos(cliente, monkeypatch):
    buscar_falsa(monkeypatch)

    cuerpo = texto(cliente.post("/buscar?idioma=en", data={"termino": "SCN1A"}))

    assert ">Summary<" in cuerpo
    assert ">References<" in cuerpo
    assert "Copy for NotebookLM" in cuerpo
    assert "Save to favourites" in cuerpo
    assert "Sort by" in cuerpo


def test_los_errores_de_formulario_salen_traducidos(cliente):
    respuesta = cliente.post(
        "/buscar?idioma=en", data={"termino": "SCN1A", "max_resultados": "cero"}
    )

    assert respuesta.status_code == 400
    assert "must be a whole number" in texto(respuesta)
    assert "The maximum number of results" in texto(respuesta)


def test_el_error_de_criterios_vacios_sale_traducido(cliente):
    respuesta = cliente.post("/buscar?idioma=en", data={"termino": ""})

    assert "Enter a gene, syndrome or search term" in texto(respuesta)


def test_los_textos_del_javascript_viajan_traducidos(cliente, monkeypatch):
    """El JS no lleva literales: los recibe del servidor en JSON."""
    buscar_falsa(monkeypatch)

    cuerpo = texto(cliente.post("/buscar?idioma=en", data={"termino": "SCN1A"}))

    assert "var PS_TEXTOS =" in cuerpo
    assert "Searching\\u2026" in cuerpo or "Searching…" in cuerpo
    assert "Copied!" in cuerpo
    assert "of $total$ results shown" in cuerpo  # con su placeholder intacto


def test_el_conmutador_de_idioma_esta_en_la_pagina(cliente):
    cuerpo = texto(cliente.get("/"))

    assert 'href="?idioma=en"' in cuerpo
    # El idioma activo se marca y no se ofrece como enlace.
    assert "<strong>ES</strong>" in cuerpo


# ------------------------------------------------- persistencia del idioma


def test_el_idioma_se_recuerda_en_una_cookie(cliente):
    respuesta = cliente.get("/?idioma=en")

    galletas = respuesta.headers.getlist("Set-Cookie")
    assert any("idioma=en" in g for g in galletas)


def test_una_peticion_posterior_sin_parametro_mantiene_el_idioma(cliente):
    cliente.get("/?idioma=en")

    cuerpo = texto(cliente.get("/"))

    assert 'id="boton">Search</button>' in cuerpo


def test_el_idioma_sobrevive_a_un_post(cliente, monkeypatch):
    """El motivo de usar cookie: /buscar es POST y no arrastra la query."""
    buscar_falsa(monkeypatch)
    cliente.get("/?idioma=en")

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert ">Summary<" in cuerpo


def test_el_idioma_sobrevive_a_un_redirect(cliente):
    """Y el otro motivo: favoritos redirige tras guardar."""
    cliente.get("/?idioma=en")

    cuerpo = texto(cliente.get("/favoritos"))

    assert "<h1>My favourites</h1>" in cuerpo


def test_el_parametro_manda_sobre_la_cookie(cliente):
    cliente.get("/?idioma=en")

    cuerpo = texto(cliente.get("/?idioma=es"))

    assert 'id="boton">Buscar</button>' in cuerpo


def test_una_cookie_con_basura_no_rompe_la_pagina(cliente):
    cliente.set_cookie("idioma", "klingon")

    respuesta = cliente.get("/")

    assert respuesta.status_code == 200
    assert 'id="boton">Buscar</button>' in texto(respuesta)


def test_un_idioma_desconocido_en_la_url_cae_al_de_referencia(cliente):
    respuesta = cliente.get("/?idioma=fr")

    assert respuesta.status_code == 200
    assert '<html lang="es"' in texto(respuesta)


# ------------------------------------ una traducción a medias no rompe nada


def test_una_clave_sin_traducir_cae_al_espanol_y_la_pagina_sigue_entera(
    cliente, monkeypatch
):
    """Fallback documentado, comprobado sobre la página real."""
    completo = dict(mod.cargar_idioma("es"))
    incompleto = dict(mod.cargar_idioma("en"))
    del incompleto["form_boton_buscar"]  # se queda sin traducir
    monkeypatch.setattr(
        mod,
        "cargar_idioma",
        lambda idioma: incompleto if idioma == "en" else completo,
    )

    respuesta = cliente.get("/?idioma=en")
    cuerpo = texto(respuesta)

    assert respuesta.status_code == 200
    # La clave que falta sale en español, no vacía ni como error.
    assert 'id="boton">Buscar</button>' in cuerpo
    # Y el resto de la página sigue en inglés.
    assert "Gene, syndrome or term" in cuerpo


def test_una_clave_que_no_existe_en_ningun_idioma_no_tumba_la_pagina(
    cliente, monkeypatch
):
    """Peor caso: la fuente entera vacía. Se ven las claves, pero se sirve."""
    monkeypatch.setattr(mod, "cargar_idioma", lambda idioma: {})

    respuesta = cliente.get("/")
    cuerpo = texto(respuesta)

    assert respuesta.status_code == 200
    # En vez de un hueco mudo, la clave señala qué falta y dónde.
    assert "form_boton_buscar" in cuerpo


def test_un_placeholder_sin_valor_no_rompe_el_renderizado(cliente, monkeypatch):
    fuente = dict(mod.cargar_idioma("es"))
    fuente["fil_contador"] = "$visibles$ de $total$ y un $sobrante$"
    monkeypatch.setattr(mod, "cargar_idioma", lambda idioma: fuente)
    buscar_falsa(monkeypatch)

    respuesta = cliente.post("/buscar", data={"termino": "SCN1A"})

    assert respuesta.status_code == 200
    assert "$sobrante$" in texto(respuesta)  # visible, no reventado


# --------------------------------------------- el idioma llega a la búsqueda


def test_el_idioma_se_pasa_a_buscar_y_resumir(cliente, monkeypatch):
    """Los avisos de alcance e idioma los construye el paquete: necesita saberlo."""
    recibidos = {}

    def falsa(termino, **kwargs):
        recibidos.update(kwargs)
        return ResultadoBusqueda(query=termino, papers=PAPERS, dias=365)

    monkeypatch.setattr(web, "buscar_y_resumir", falsa)

    cliente.post("/buscar?idioma=en", data={"termino": "SCN1A"})

    assert recibidos["idioma"] == "en"


def test_el_aviso_de_alcance_sale_en_el_idioma_activo(cliente, monkeypatch):
    from paper_search.alcance import AMBIGUO, VeredictoAlcance

    veredicto = VeredictoAlcance(veredicto=AMBIGUO, motivo="siglas ambiguas.")
    buscar_falsa(
        monkeypatch,
        ResultadoBusqueda(
            query="CDG",
            papers=PAPERS,
            resumen="Hallazgo [PMID: 38123456].",
            dias=365,
            aviso_alcance=veredicto.aviso("CDG", "en"),
        ),
    )

    cuerpo = texto(cliente.post("/buscar?idioma=en", data={"termino": "CDG"}))

    assert "could not be confidently classified" in cuerpo
    assert "Scope notice." in cuerpo


def test_el_aviso_de_idioma_sale_en_el_idioma_activo(cliente, monkeypatch):
    from paper_search.idioma import aviso_de_idioma

    buscar_falsa(
        monkeypatch,
        ResultadoBusqueda(
            query="síndrome de Dravet",
            papers=PAPERS,
            resumen="Hallazgo [PMID: 38123456].",
            dias=365,
            aviso_idioma=aviso_de_idioma("síndrome de Dravet", "en"),
        ),
    )

    cuerpo = texto(cliente.post("/buscar?idioma=en", data={"termino": "x"}))

    assert "appears to be written in Spanish" in cuerpo
    assert "Language notice." in cuerpo


def test_los_errores_de_favoritos_salen_en_el_idioma_activo(cliente):
    respuesta = cliente.post(
        "/favoritos/alternar?idioma=en", json={"pmid": "99999999"}
    )

    assert respuesta.status_code == 400
    assert "is not in the local database" in respuesta.get_json()["error"]
