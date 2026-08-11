"""Tests de la ordenación de resultados (`orden.py`).

Lo que se protege aquí, además de que ordene bien:

- que reordenar sea **local** (cero consultas a PubMed),
- que **no invalide la caché** de resúmenes de la Fase 2,
- que el desempate por fecha sea **estable y reproducible**, no el azar de
  la entrada.
"""

from __future__ import annotations

import pytest

from paper_search import (
    ORDEN_FECHA,
    ORDEN_RELEVANCIA,
    Paper,
    buscar_y_resumir,
    clave_fecha,
    ordenar_papers,
)
from paper_search.orden import OrdenDesconocidoError, normalizar_orden


def paper(pmid, fecha, relevancia):
    return Paper(
        pmid=pmid,
        titulo=f"Articulo {pmid}",
        fecha=fecha,
        abstract="Contenido.",
        orden_relevancia=relevancia,
    )


# PubMed los devolvió en este orden (relevancia 0, 1, 2, 3); las fechas no
# siguen ese orden, que es justo lo que hace interesante el test.
PAPERS = (
    paper("1", "2020-05-10", 0),
    paper("2", "2024-03-15", 1),
    paper("3", "2022-01-01", 2),
    paper("4", "2024-11-02", 3),
)


# ----------------------------------------------------------- clave de fecha


@pytest.mark.parametrize(
    "fecha,esperado",
    [
        ("2024-03-15", (2024, 3, 15)),
        ("2024-03", (2024, 3, 0)),
        ("2024", (2024, 0, 0)),
        ("", (0, 0, 0)),
        ("sin fecha", (0, 0, 0)),
        ("2023 Nov-Dec", (2023, 11, 0)),  # MedlineDate en texto libre
        ("2023 Jan", (2023, 1, 0)),
    ],
)
def test_clave_de_fecha_admite_la_granularidad_variable_de_pubmed(fecha, esperado):
    assert clave_fecha(fecha) == esperado


def test_un_paper_sin_fecha_queda_al_final_no_al_principio():
    papers = (paper("1", "", 5), paper("2", "2010-01-01", 0))

    orden = ordenar_papers(papers, ORDEN_FECHA)

    assert [p.pmid for p in orden] == ["2", "1"]


# --------------------------------------------------------------- ordenación


def test_orden_por_fecha_de_mas_reciente_a_mas_antiguo():
    orden = ordenar_papers(PAPERS, ORDEN_FECHA)

    assert [p.pmid for p in orden] == ["4", "2", "3", "1"]


def test_orden_por_fecha_es_el_de_por_defecto():
    assert ordenar_papers(PAPERS) == ordenar_papers(PAPERS, ORDEN_FECHA)


def test_orden_por_relevancia_respeta_lo_que_dijo_pubmed():
    orden = ordenar_papers(PAPERS, ORDEN_RELEVANCIA)

    assert [p.pmid for p in orden] == ["1", "2", "3", "4"]


def test_ordenar_no_modifica_la_entrada():
    original = list(PAPERS)

    ordenar_papers(PAPERS, ORDEN_FECHA)

    assert list(PAPERS) == original


def test_ordenar_no_pierde_ni_duplica_papers():
    for criterio in (ORDEN_FECHA, ORDEN_RELEVANCIA):
        orden = ordenar_papers(PAPERS, criterio)
        assert sorted(p.pmid for p in orden) == ["1", "2", "3", "4"]


def test_un_criterio_desconocido_es_un_error():
    with pytest.raises(OrdenDesconocidoError):
        ordenar_papers(PAPERS, "por_color")


def test_normalizar_orden_tolera_basura_del_formulario():
    assert normalizar_orden("relevancia") == ORDEN_RELEVANCIA
    assert normalizar_orden("  FECHA  ") == ORDEN_FECHA
    assert normalizar_orden("cualquier-cosa") == ORDEN_FECHA
    assert normalizar_orden(None) == ORDEN_FECHA
    assert normalizar_orden("") == ORDEN_FECHA


# ------------------------------------------------------- empate en la fecha


def test_empate_en_fecha_desempata_por_relevancia():
    """Tres artículos del mismo día: manda el orden de PubMed, no el azar."""
    papers = (
        paper("a", "2024-03-15", 2),
        paper("b", "2024-03-15", 0),
        paper("c", "2024-03-15", 1),
    )

    orden = ordenar_papers(papers, ORDEN_FECHA)

    assert [p.pmid for p in orden] == ["b", "c", "a"]


def test_el_desempate_no_depende_del_orden_de_entrada():
    """Mismo conjunto, entrada barajada: la salida debe ser idéntica."""
    papers = (
        paper("a", "2024", 2),
        paper("b", "2024", 0),
        paper("c", "2024", 1),
    )

    desde_un_orden = ordenar_papers(papers, ORDEN_FECHA)
    desde_otro = ordenar_papers(tuple(reversed(papers)), ORDEN_FECHA)

    assert [p.pmid for p in desde_un_orden] == [p.pmid for p in desde_otro]


def test_empate_de_papers_sin_relevancia_no_revienta():
    papers = (Paper(pmid="x", titulo="X", fecha="2024"), Paper(pmid="y", titulo="Y", fecha="2024"))

    orden = ordenar_papers(papers, ORDEN_FECHA)

    assert len(orden) == 2


# --------------------------------------------- integración con la búsqueda


class ClientPubMedFalso:
    """Devuelve siempre los mismos papers y cuenta cuántas veces le preguntan."""

    def __init__(self, papers):
        self.papers = list(papers)
        self.llamadas: list[dict] = []

    def buscar_papers(self, termino, *, max_resultados, dias):
        self.llamadas.append({"termino": termino})
        return list(self.papers)


def buscar(orden, client=None):
    client = client or ClientPubMedFalso(PAPERS)
    resultado = buscar_y_resumir(
        "SCN1A",
        orden=orden,
        resumir=False,
        verificar_alcance=False,
        client=client,
    )
    return resultado, client


def test_la_busqueda_devuelve_los_papers_ya_ordenados():
    resultado, _ = buscar(ORDEN_FECHA)

    assert [p.pmid for p in resultado.papers] == ["4", "2", "3", "1"]
    assert resultado.orden == ORDEN_FECHA


def test_la_busqueda_por_relevancia_usa_el_orden_de_pubmed():
    resultado, _ = buscar(ORDEN_RELEVANCIA)

    assert [p.pmid for p in resultado.papers] == ["1", "2", "3", "4"]
    assert resultado.orden == ORDEN_RELEVANCIA


def test_reordenar_no_vuelve_a_consultar_pubmed():
    """El punto de la tarea: cambiar el criterio es una operación local."""
    _, client = buscar(ORDEN_FECHA)
    consultas_tras_buscar = len(client.llamadas)

    # Reordenar lo ya obtenido: ni una consulta más.
    resultado, _ = buscar(ORDEN_FECHA, client=client)
    ordenados = ordenar_papers(resultado.papers, ORDEN_RELEVANCIA)

    assert [p.pmid for p in ordenados] == ["1", "2", "3", "4"]
    assert consultas_tras_buscar == 1
    # La segunda búsqueda del test sí consultó; el reordenado posterior, no.
    assert len(client.llamadas) == 2


def test_el_orden_no_invalida_la_cache_de_resumenes():
    """La clave de caché es (término, PMIDs ordenados): el orden no la toca."""
    from paper_search import abrir_db
    from paper_search.cache import CacheResumenes

    db = abrir_db(":memory:")
    try:
        cache = CacheResumenes(db)
        pmids_por_fecha = [p.pmid for p in ordenar_papers(PAPERS, ORDEN_FECHA)]
        pmids_por_relevancia = [p.pmid for p in ordenar_papers(PAPERS, ORDEN_RELEVANCIA)]
        assert pmids_por_fecha != pmids_por_relevancia  # el orden sí cambia

        cache.guardar("SCN1A", pmids_por_fecha, "Resumen [PMID: 1].", "modelo-x")

        # Se busca con el otro orden y aun así hay acierto.
        cacheado = cache.buscar("SCN1A", pmids_por_relevancia)
        assert cacheado is not None
        assert cacheado.resumen == "Resumen [PMID: 1]."
    finally:
        db.close()


def test_el_json_expone_el_orden_aplicado():
    resultado, _ = buscar(ORDEN_RELEVANCIA)

    datos = resultado.to_dict()
    assert datos["orden"] == ORDEN_RELEVANCIA
    assert datos["papers"][0]["orden_relevancia"] == 0
