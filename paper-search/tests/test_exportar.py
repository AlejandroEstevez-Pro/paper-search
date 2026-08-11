"""Tests del texto de exportación para NotebookLM.

Dos cosas se protegen con especial cuidado:

- Que **no se cuele nada de la página** (etiquetas, clases, botones): el texto
  va a pegarse como fuente en otra herramienta, y el marcado ahí es ruido que
  el modelo se comería como si fuera contenido.
- Que **el contenido no se pierda**: término, resumen, PMIDs y aviso médico.
  El aviso viaja con el texto justamente porque el texto se va de aquí.
"""

from __future__ import annotations

import pytest

from paper_search import Criterios, Paper, ResultadoBusqueda, texto_para_notebooklm
from paper_search.models import AVISO_NO_DIAGNOSTICO

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="SCN1A variants in Dravet syndrome",
        autores=("García A", "Smith JR"),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="Cohorte de 42 pacientes.",
        orden_relevancia=0,
    ),
    Paper(
        pmid="38999999",
        titulo="Historia natural de una encefalopatía epiléptica",
        autores=("Lopez B",),
        revista="Orphanet J Rare Dis",
        fecha="2023",
        abstract="Seguimiento de 20 pacientes.",
        orden_relevancia=1,
    ),
)

RESUMEN = (
    "Se han descrito variantes nuevas [PMID: 38123456].\n\n"
    "La historia natural sigue siendo poco conocida [PMID: 38999999]."
)


def resultado(**kwargs):
    base = dict(
        query="SCN1A",
        papers=PAPERS,
        resumen=RESUMEN,
        dias=365,
        criterios=Criterios.de("SCN1A"),
    )
    base.update(kwargs)
    return ResultadoBusqueda(**base)


# ------------------------------------------------------------- contenido


def test_incluye_el_termino_de_busqueda_como_contexto():
    texto = texto_para_notebooklm(resultado())

    assert "Término: SCN1A" in texto
    # Y va arriba: es lo que da contexto a la fuente pegada.
    assert texto.index("Término: SCN1A") < texto.index("RESUMEN")


def test_incluye_el_resumen_integro():
    texto = texto_para_notebooklm(resultado())

    assert "Se han descrito variantes nuevas" in texto
    assert "La historia natural sigue siendo poco conocida" in texto


def test_conserva_las_citas_pmid_del_resumen():
    texto = texto_para_notebooklm(resultado())

    assert "[PMID: 38123456]" in texto
    assert "[PMID: 38999999]" in texto


def test_incluye_las_referencias_con_enlace_verificable():
    texto = texto_para_notebooklm(resultado())

    for paper in PAPERS:
        assert paper.titulo in texto
        assert f"PMID {paper.pmid}" in texto
        assert f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/" in texto


def test_incluye_el_disclaimer_medico():
    """Viaja con el texto: fuera de esta interfaz nada lo recordaría."""
    texto = texto_para_notebooklm(resultado())

    assert AVISO_NO_DIAGNOSTICO in texto
    assert "no es una herramienta de diagnóstico" in texto.lower()


def test_incluye_los_avisos_de_alcance_y_de_idioma_si_los_hay():
    texto = texto_para_notebooklm(
        resultado(
            aviso_alcance="El término «CDG» es ambiguo.",
            aviso_idioma="Parece estar escrito en español.",
        )
    )

    assert "AVISO DE ALCANCE: El término «CDG» es ambiguo." in texto
    assert "AVISO DE IDIOMA: Parece estar escrito en español." in texto


def test_los_criterios_avanzados_salen_en_la_cabecera():
    texto = texto_para_notebooklm(
        resultado(
            query='(Dravet) AND ("Scheffer IE"[AU])',
            criterios=Criterios.de("Dravet", autor="Scheffer IE"),
        )
    )

    assert "Término: Dravet" in texto
    assert "Autor: Scheffer IE" in texto
    # La consulta real también, porque explica por qué salieron estos papers.
    assert 'Consulta enviada a PubMed: (Dravet) AND ("Scheffer IE"[AU])' in texto


def test_el_patogeno_sale_en_la_cabecera():
    texto = texto_para_notebooklm(
        resultado(criterios=Criterios.de("toxoplasmosis", patogeno="Toxoplasma gondii"))
    )

    assert "Patógeno: Toxoplasma gondii" in texto


# --------------------------------------------------- nada de la interfaz


@pytest.mark.parametrize(
    "prohibido",
    [
        "<p>", "</p>", "<div", "<span", "<button", "<section", "<li>",
        "class=", "ps-summary", "ps-notice", "card-body", "pmid\"",
        "url_for", "&nbsp;", "&lt;", "<!doctype",
    ],
)
def test_no_se_cuela_marcado_de_la_pagina(prohibido):
    texto = texto_para_notebooklm(
        resultado(aviso_alcance="Aviso.", aviso_idioma="Aviso.")
    )

    assert prohibido not in texto


def test_no_lleva_texto_de_botones_ni_de_la_interfaz():
    texto = texto_para_notebooklm(resultado())

    for ruido in (
        "Guardar en favoritos",
        "En favoritos",
        "Copiar para NotebookLM",
        "Regenerar el resumen",
        "Ordenar por",
        "resultados mostrados",
    ):
        assert ruido not in texto


def test_el_texto_es_plano_sin_markdown():
    """NotebookLM lo trata como fuente: los `#` o `**` solo serían ruido."""
    texto = texto_para_notebooklm(resultado())

    assert "**" not in texto
    assert not any(linea.startswith("#") for linea in texto.split("\n"))


# ------------------------------------------------ independiente de la caché


def test_el_texto_es_identico_venga_o_no_de_cache():
    """Requisito explícito: exportar no depende de cómo se obtuvo el resumen."""
    recien_generado = texto_para_notebooklm(resultado())
    desde_cache = texto_para_notebooklm(
        resultado(desde_cache=True, cache_creado_en="2026-08-01T10:00:00+00:00")
    )

    assert recien_generado == desde_cache


def test_no_se_filtran_metadatos_de_cache():
    texto = texto_para_notebooklm(
        resultado(desde_cache=True, cache_creado_en="2026-08-01T10:00:00+00:00")
    )

    assert "caché" not in texto.lower()
    assert "2026-08-01" not in texto


def test_el_orden_de_presentacion_no_cambia_el_contenido():
    por_fecha = texto_para_notebooklm(resultado(orden="fecha"))
    por_relevancia = texto_para_notebooklm(resultado(orden="relevancia"))

    # Mismo conjunto de PMIDs citados, aunque el orden de las filas cambiase.
    for pmid in ("38123456", "38999999"):
        assert pmid in por_fecha
        assert pmid in por_relevancia


# ------------------------------------------------------------ casos límite


def test_sin_resumen_se_exporta_el_motivo_y_las_referencias():
    texto = texto_para_notebooklm(
        resultado(resumen=None, error_resumen="La API de Anthropic falló.")
    )

    assert "No se generó resumen" in texto
    assert "La API de Anthropic falló." in texto
    # Las referencias reales siguen valiendo como fuente.
    assert "PMID 38123456" in texto
    assert AVISO_NO_DIAGNOSTICO in texto


def test_sin_resumen_y_sin_motivo_tampoco_deja_un_hueco_mudo():
    texto = texto_para_notebooklm(resultado(resumen=None))

    assert "No se generó resumen" in texto


def test_una_busqueda_sin_resultados_no_revienta():
    texto = texto_para_notebooklm(
        resultado(papers=(), resumen=None, criterios=Criterios.de("zzz"))
    )

    assert "Término: zzz" in texto
    assert "Artículos recuperados: 0" in texto
    assert "REFERENCIAS" not in texto  # no se pinta una sección vacía
    assert AVISO_NO_DIAGNOSTICO in texto


def test_sin_criterios_usa_la_consulta_como_termino():
    """Resultado construido como librería, sin `criterios`."""
    texto = texto_para_notebooklm(
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen=RESUMEN, dias=365)
    )

    assert "Término: SCN1A" in texto


def test_el_texto_termina_en_una_sola_linea_nueva():
    texto = texto_para_notebooklm(resultado())

    assert texto.endswith("\n")
    assert not texto.endswith("\n\n")
