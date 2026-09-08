"""Tests de la interfaz web local.

Nunca se llama a PubMed ni a Anthropic: se sustituye `buscar_y_resumir` en el
módulo `app` por un doble que devuelve un `ResultadoBusqueda` ya montado. Lo que
se comprueba aquí es el renderizado (los estados del diseño) y los códigos de
respuesta, no la búsqueda, que ya tiene sus propios tests.
"""

from __future__ import annotations

import pytest

import app as web
from paper_search import Paper, PaperSearchError, ResultadoBusqueda, abrir_db

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="Variantes de SCN1A en el sindrome de Dravet",
        autores=("Garcia A", "Smith JR"),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="Se identificaron 42 variantes nuevas.",
    ),
    Paper(
        pmid="38999999",
        titulo="Historia natural de una encefalopatia epileptica",
        autores=("Lopez B",),
        revista="Orphanet J Rare Dis",
        fecha="2023",
    ),
)

RESUMEN = (
    "Se han descrito variantes nuevas [PMID: 38123456].\n\n"
    "La historia natural sigue siendo poco conocida [PMID: 38999999]."
)


@pytest.fixture
def cliente():
    web.app.config["TESTING"] = True
    return web.app.test_client()


@pytest.fixture(autouse=True)
def db_en_memoria(monkeypatch):
    """Que las peticiones de test no creen la BD real del repo en `datos/`."""
    monkeypatch.setattr(web, "abrir_db", lambda: abrir_db(":memory:"))


def responder_con(monkeypatch, resultado=None, error=None):
    """Sustituye la búsqueda real por un doble."""

    def falsa(termino, *, max_resultados, dias, **kwargs):
        if error is not None:
            raise error
        return resultado

    monkeypatch.setattr(web, "buscar_y_resumir", falsa)


def texto(respuesta) -> str:
    return respuesta.get_data(as_text=True)


# ------------------------------------------------------------------ formulario


def test_la_portada_avisa_de_que_no_es_diagnostica(cliente):
    cuerpo = texto(cliente.get("/"))

    assert "No es una herramienta de diagnóstico" in cuerpo
    assert "classical.css" in cuerpo  # el sistema de diseño está enlazado


def test_la_portada_empieza_en_el_estado_vacio(cliente):
    cuerpo = texto(cliente.get("/"))

    assert "pulsa «Buscar»" in cuerpo
    assert "Referencias" not in cuerpo


def test_un_maximo_invalido_no_llega_a_buscar(cliente, monkeypatch):
    def no_deberia_llamarse(*args, **kwargs):  # pragma: no cover - debe fallar antes
        raise AssertionError("no se debería haber buscado")

    monkeypatch.setattr(web, "buscar_y_resumir", no_deberia_llamarse)

    respuesta = cliente.post("/buscar", data={"termino": "SCN1A", "max_resultados": "0"})

    assert respuesta.status_code == 400
    assert "mayor que 0" in texto(respuesta)


def test_un_termino_vacio_no_llega_a_buscar(cliente):
    respuesta = cliente.post("/buscar", data={"termino": "   "})

    assert respuesta.status_code == 400
    assert "Escribe un gen" in texto(respuesta)


# --------------------------------------------------------------- resultados


def test_muestra_el_resumen_con_las_citas_resaltadas(cliente, monkeypatch):
    responder_con(
        monkeypatch,
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen=RESUMEN, dias=365),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    # La cita sigue resaltada, y desde la Fase 6 el PMID de dentro es un
    # enlace al artículo (ver test_citas_enlazadas.py).
    assert '<span class="pmid">[PMID: <a href=' in cuerpo
    assert ">38123456</a>]</span>" in cuerpo
    assert "Se han descrito variantes nuevas" in cuerpo


def test_el_boton_de_copiar_sale_con_el_texto_ya_montado(cliente, monkeypatch):
    responder_con(
        monkeypatch,
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen=RESUMEN, dias=365),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert 'id="copiar-notebooklm"' in cuerpo
    assert "Copiar para NotebookLM" in cuerpo
    # El texto viaja ya hecho desde el servidor, dentro del textarea.
    assert 'id="texto-notebooklm"' in cuerpo
    assert "BÚSQUEDA EN PUBMED" in cuerpo
    assert "Término: SCN1A" in cuerpo
    assert "PMID 38123456" in cuerpo
    assert "no es una herramienta de diagnóstico" in cuerpo.lower()


def test_hay_alternativa_visible_si_falla_el_portapapeles(cliente, monkeypatch):
    """No se falla en silencio: el cuadro seleccionable ya está en la página."""
    responder_con(
        monkeypatch,
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen=RESUMEN, dias=365),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert 'id="fallo-copiar"' in cuerpo
    assert "Ctrl+C" in cuerpo
    assert "navigator.clipboard" in cuerpo
    # El textarea nace oculto y solo se enseña si la copia falla.
    assert "<textarea id=\"texto-notebooklm\"" in cuerpo


def test_el_texto_sobrevive_intacto_al_escapado_html(cliente, monkeypatch):
    """Lo que copia el navegador debe ser exactamente lo que probamos.

    Jinja escapa `&` y `<` dentro del textarea, y `textarea.value` los
    desescapa: el round-trip tiene que ser exacto, y un `<b>` de un título no
    puede escaparse del textarea y convertirse en marcado de la página.
    """
    import html
    import re

    from paper_search import texto_para_notebooklm

    papers = (
        Paper(
            pmid="38123456",
            titulo='Sturge-Weber & "R<S>" syndrome <b>bold</b>',
            autores=("García A",),
            revista="Epilepsia",
            fecha="2024-03-15",
        ),
    )
    resultado = ResultadoBusqueda(
        query="SCN1A", papers=papers, resumen="Hallazgo [PMID: 38123456].", dias=365
    )
    responder_con(monkeypatch, resultado)

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    crudo = re.search(
        r'<textarea id="texto-notebooklm".*?>(.*?)</textarea>', cuerpo, re.S
    ).group(1)
    assert "<b>bold</b>" not in crudo  # no se ha escapado del textarea
    assert html.unescape(crudo) == texto_para_notebooklm(resultado)


def test_sin_resumen_no_se_ofrece_copiar(cliente, monkeypatch):
    """Sin resumen no hay nada que exportar a NotebookLM."""
    responder_con(
        monkeypatch,
        ResultadoBusqueda(
            query="SCN1A",
            papers=PAPERS,
            dias=365,
            error_resumen="La API de Anthropic falló.",
        ),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert 'id="copiar-notebooklm"' not in cuerpo


def test_el_texto_copiado_es_el_mismo_venga_de_cache_o_no(cliente, monkeypatch):
    def cuerpo_con(desde_cache):
        responder_con(
            monkeypatch,
            ResultadoBusqueda(
                query="SCN1A",
                papers=PAPERS,
                resumen=RESUMEN,
                dias=365,
                desde_cache=desde_cache,
                cache_creado_en="2026-08-01T10:00:00+00:00" if desde_cache else None,
            ),
        )
        return texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    def extraer(cuerpo):
        inicio = cuerpo.index("BÚSQUEDA EN PUBMED")
        return cuerpo[inicio : cuerpo.index("</textarea>", inicio)]

    assert extraer(cuerpo_con(False)) == extraer(cuerpo_con(True))


def test_el_formulario_avanzado_manda_autor_y_patogeno(cliente, monkeypatch):
    recibidos = {}

    def falsa(termino, *, max_resultados, dias, **kwargs):
        recibidos.update({"termino": termino, **kwargs})
        return ResultadoBusqueda(query=termino, papers=PAPERS, dias=dias)

    monkeypatch.setattr(web, "buscar_y_resumir", falsa)

    cliente.post(
        "/buscar",
        data={
            "termino": "toxoplasmosis",
            "autor": "Lopez B",
            "patogeno": "Toxoplasma gondii",
        },
    )

    assert recibidos["autor"] == "Lopez B"
    assert recibidos["patogeno"] == "Toxoplasma gondii"


def test_se_puede_buscar_solo_por_autor_desde_la_web(cliente, monkeypatch):
    recibidos = {}

    def falsa(termino, *, max_resultados, dias, **kwargs):
        recibidos.update({"termino": termino, **kwargs})
        return ResultadoBusqueda(query='"Scheffer IE"[AU]', papers=PAPERS, dias=dias)

    monkeypatch.setattr(web, "buscar_y_resumir", falsa)

    respuesta = cliente.post("/buscar", data={"termino": "", "autor": "Scheffer IE"})

    assert respuesta.status_code == 200
    assert recibidos["autor"] == "Scheffer IE"


def test_sin_ningun_criterio_la_web_lo_dice(cliente):
    respuesta = cliente.post("/buscar", data={"termino": ""})

    assert respuesta.status_code == 400
    assert "búsqueda avanzada" in texto(respuesta)


def test_los_filtros_de_pantalla_dicen_n_de_m(cliente, monkeypatch):
    """No un contador a secas: filtrar no es buscar, y debe verse."""
    responder_con(
        monkeypatch,
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen=RESUMEN, dias=365),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert 'id="filtro-autor"' in cuerpo
    assert 'id="filtro-patogeno"' in cuerpo
    assert "2 de 2 resultados mostrados" in cuerpo
    assert "no vuelve a consultar PubMed" in cuerpo
    # Los datos con los que filtra el navegador viajan en cada fila.
    assert 'data-autores="garcia a smith jr"' in cuerpo


def test_el_formulario_conserva_autor_y_patogeno_tras_un_error(cliente):
    respuesta = cliente.post(
        "/buscar",
        data={"termino": "SCN1A", "max_resultados": "cero", "autor": "Smith J"},
    )

    assert respuesta.status_code == 400
    assert 'value="Smith J"' in texto(respuesta)


def test_el_selector_de_orden_trae_los_datos_para_reordenar_en_local(
    cliente, monkeypatch
):
    """El reordenado del navegador no vuelve al servidor: necesita los datos
    de orden en cada fila."""
    responder_con(
        monkeypatch,
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen=RESUMEN, dias=365),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert '<select class="input" id="orden">' in cuerpo
    assert 'value="fecha"' in cuerpo
    assert 'value="relevancia"' in cuerpo
    # Cada fila lleva su clave de fecha y su posición de relevancia.
    assert 'data-fecha="2024-03-15"' in cuerpo
    assert 'data-relevancia=' in cuerpo


def test_el_orden_elegido_llega_a_la_busqueda(cliente, monkeypatch):
    recibidos = {}

    def falsa(termino, *, max_resultados, dias, **kwargs):
        recibidos.update(kwargs)
        return ResultadoBusqueda(query=termino, papers=PAPERS, dias=dias)

    monkeypatch.setattr(web, "buscar_y_resumir", falsa)

    cliente.post("/buscar", data={"termino": "SCN1A", "orden": "relevancia"})

    assert recibidos["orden"] == "relevancia"


def test_un_orden_invalido_del_formulario_cae_al_de_por_defecto(cliente, monkeypatch):
    """Es una preferencia de visualización: no debe romper la búsqueda."""
    recibidos = {}

    def falsa(termino, *, max_resultados, dias, **kwargs):
        recibidos.update(kwargs)
        return ResultadoBusqueda(query=termino, papers=PAPERS, dias=dias)

    monkeypatch.setattr(web, "buscar_y_resumir", falsa)

    respuesta = cliente.post("/buscar", data={"termino": "SCN1A", "orden": "por_color"})

    assert respuesta.status_code == 200
    assert recibidos["orden"] == "fecha"


def test_el_aviso_de_idioma_se_muestra_y_no_impide_el_resultado(cliente, monkeypatch):
    """La web avisa igual que la CLI, y el resultado se enseña completo."""
    responder_con(
        monkeypatch,
        ResultadoBusqueda(
            query="síndrome de Dravet",
            papers=PAPERS,
            resumen=RESUMEN,
            dias=365,
            aviso_idioma=(
                "El término «síndrome de Dravet» parece estar escrito en español "
                "o en una lengua cooficial. Prueba a reescribirlo en inglés."
            ),
        ),
    )

    respuesta = cliente.post("/buscar", data={"termino": "síndrome de Dravet"})
    cuerpo = texto(respuesta)

    assert respuesta.status_code == 200  # avisa, no bloquea
    assert "Aviso de idioma." in cuerpo
    assert "reescribirlo en inglés" in cuerpo
    assert "38123456" in cuerpo  # las referencias se muestran igual


def test_sin_aviso_de_idioma_no_se_pinta_la_tarjeta(cliente, monkeypatch):
    responder_con(
        monkeypatch,
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen=RESUMEN, dias=365),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert "Aviso de idioma." not in cuerpo


def test_cada_referencia_enlaza_a_su_pmid_en_pubmed(cliente, monkeypatch):
    responder_con(
        monkeypatch,
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen=RESUMEN, dias=365),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    for paper in PAPERS:
        assert f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/" in cuerpo
        assert paper.titulo in cuerpo
    # El número va en su propio <span> para que el reordenado del navegador
    # pueda renumerar sin tocar el resto de la línea.
    assert '<span class="ps-num">01</span> · PMID: 38123456' in cuerpo


def test_sin_resumen_se_explica_el_motivo_y_se_listan_los_papers(cliente, monkeypatch):
    responder_con(
        monkeypatch,
        ResultadoBusqueda(
            query="SCN1A",
            papers=PAPERS,
            dias=365,
            error_resumen="Falta ANTHROPIC_API_KEY, necesaria para generar el resumen",
        ),
    )

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert "No se pudo generar un resumen" in cuerpo
    assert "Falta ANTHROPIC_API_KEY" in cuerpo  # el motivo real, no un genérico
    assert "38123456" in cuerpo  # las referencias reales siguen ahí


def test_una_busqueda_sin_resultados_lo_dice_en_vez_de_inventar(cliente, monkeypatch):
    responder_con(monkeypatch, ResultadoBusqueda(query="xyzzy", papers=(), dias=365))

    cuerpo = texto(cliente.post("/buscar", data={"termino": "xyzzy"}))

    assert "no ha devuelto ningún artículo" in cuerpo
    assert "card-kicker" not in cuerpo  # ninguna referencia renderizada


def test_un_fallo_de_pubmed_se_muestra_con_502(cliente, monkeypatch):
    responder_con(monkeypatch, error=PaperSearchError("PubMed devolvió un 503"))

    respuesta = cliente.post("/buscar", data={"termino": "SCN1A"})

    assert respuesta.status_code == 502
    assert "PubMed devolvió un 503" in texto(respuesta)


def test_el_formulario_conserva_lo_que_se_escribio(cliente, monkeypatch):
    responder_con(monkeypatch, ResultadoBusqueda(query="SCN1A", papers=PAPERS, dias=90))

    cuerpo = texto(
        cliente.post(
            "/buscar", data={"termino": "SCN1A", "max_resultados": "5", "dias": "90"}
        )
    )

    assert 'value="SCN1A"' in cuerpo
    assert 'value="5"' in cuerpo
    assert 'value="90"' in cuerpo
