"""Citas [PMID: ...] clicables dentro del resumen.

Dos propiedades mandan sobre las demás:

1. **Solo se enlaza lo respaldado.** Un PMID que no esté entre los artículos
   recuperados no se convierte en enlace. La verificación del resumen ya
   impide que llegue ahí, pero si llegara, un enlace le daría exactamente la
   apariencia de legitimidad que no tiene.
2. **El enlazado no abre la puerta a inyectar marcado.** El resumen lo escribe
   un modelo; si trae `<script>` o comillas, tiene que verse como texto. Por
   eso Python devuelve datos y el HTML lo monta la plantilla, con el escapado
   de Jinja: no hay ningún `|safe` en el camino.

Y una tercera, de no-regresión: el texto que se exporta a NotebookLM no cambia.
"""

from __future__ import annotations

import re

import pytest

import app as web
from paper_search import (
    Paper,
    ResultadoBusqueda,
    abrir_db,
    segmentar_resumen,
    texto_para_notebooklm,
    url_de_pmid,
)

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="SCN1A variants in Dravet syndrome",
        autores=("Garcia A",),
        revista="Epilepsia",
        fecha="2024-03-15",
        orden_relevancia=0,
    ),
    Paper(
        pmid="38999999",
        titulo="Historia natural de una encefalopatia epileptica",
        autores=("Lopez B",),
        revista="Orphanet J Rare Dis",
        fecha="2023",
        orden_relevancia=1,
    ),
)
PMIDS = [p.pmid for p in PAPERS]


@pytest.fixture
def cliente(monkeypatch):
    web.app.config["TESTING"] = True
    monkeypatch.setattr(web, "abrir_db", lambda: abrir_db(":memory:"))
    return web.app.test_client()


def pagina_con(monkeypatch, cliente, resumen, papers=PAPERS):
    monkeypatch.setattr(
        web,
        "buscar_y_resumir",
        lambda termino, **kw: ResultadoBusqueda(
            query="SCN1A", papers=papers, resumen=resumen, dias=365
        ),
    )
    return cliente.post("/buscar", data={"termino": "SCN1A"}).get_data(as_text=True)


def partes_de_la_cita(resumen, pmids=PMIDS):
    """Las partes del primer segmento de cita."""
    for parrafo in segmentar_resumen(resumen, pmids):
        for seg in parrafo:
            if seg.es_cita:
                return seg.partes
    raise AssertionError("no se encontró ninguna cita en: %r" % resumen)


# ------------------------------------------- un PMID de la lista se enlaza


def test_un_pmid_recuperado_se_convierte_en_enlace():
    partes = partes_de_la_cita("Hallazgo [PMID: 38123456].")

    enlaces = [p for p in partes if p.es_enlace]
    assert len(enlaces) == 1
    assert enlaces[0].texto == "38123456"
    assert enlaces[0].url == "https://pubmed.ncbi.nlm.nih.gov/38123456/"


def test_el_enlace_apunta_a_la_url_canonica_de_pubmed():
    partes = partes_de_la_cita("Hallazgo [PMID: 38123456].")

    assert partes[1].url == url_de_pmid("38123456")


def test_en_la_pagina_el_enlace_sale_completo(cliente, monkeypatch):
    cuerpo = pagina_con(monkeypatch, cliente, "Hallazgo [PMID: 38123456].")

    assert (
        '<a href="https://pubmed.ncbi.nlm.nih.gov/38123456/" '
        'target="_blank" rel="noopener">38123456</a>' in cuerpo
    )


def test_el_enlace_abre_en_pestana_nueva_y_sin_opener(cliente, monkeypatch):
    """`rel="noopener"` evita que la pestaña abierta pueda tocar la nuestra."""
    cuerpo = pagina_con(monkeypatch, cliente, "Hallazgo [PMID: 38123456].")

    enlace = re.search(r'<span class="pmid">.*?(<a [^>]+>)', cuerpo, re.S).group(1)
    assert 'target="_blank"' in enlace
    assert 'rel="noopener"' in enlace


def test_la_cita_sigue_resaltada_por_fuera(cliente, monkeypatch):
    """Enlazar no sustituye al resalte: la cita sigue distinguiéndose."""
    cuerpo = pagina_con(monkeypatch, cliente, "Hallazgo [PMID: 38123456].")

    assert '<span class="pmid">[PMID: <a' in cuerpo


# ---------------------------------- un PMID que NO está en la lista no se enlaza


def test_un_pmid_ajeno_no_se_enlaza():
    """Enlazarlo le daría apariencia de cita legítima justo cuando no lo es."""
    partes = partes_de_la_cita("Afirmación sin respaldo [PMID: 99999999].")

    assert [p for p in partes if p.es_enlace] == []


def test_el_pmid_ajeno_sigue_viéndose_como_texto(cliente, monkeypatch):
    """No se borra ni se oculta: se muestra tal cual, sin enlace. Ocultarlo
    escondería que el resumen citó algo que no se recuperó."""
    cuerpo = pagina_con(monkeypatch, cliente, "Sin respaldo [PMID: 99999999].")

    assert "99999999" in cuerpo
    assert 'href="https://pubmed.ncbi.nlm.nih.gov/99999999/"' not in cuerpo


def test_sin_lista_de_pmids_no_se_enlaza_nada():
    """El valor por defecto es el seguro: quien no pase la lista no publica
    enlaces que no puede respaldar."""
    partes = partes_de_la_cita("Hallazgo [PMID: 38123456].", pmids=[])

    assert [p for p in partes if p.es_enlace] == []


def test_el_defecto_de_la_funcion_tampoco_enlaza():
    parrafos = segmentar_resumen("Hallazgo [PMID: 38123456].")

    cita = parrafos[0][1]
    assert cita.es_cita
    assert [p for p in cita.partes if p.es_enlace] == []


# ------------------------------------------ varios PMID en una misma cita


def test_una_cita_con_varios_pmid_genera_un_enlace_por_cada_uno():
    partes = partes_de_la_cita("Ambos coinciden [PMID: 38123456, 38999999].")

    enlaces = [p for p in partes if p.es_enlace]
    assert [p.texto for p in enlaces] == ["38123456", "38999999"]
    assert [p.url for p in enlaces] == [
        url_de_pmid("38123456"),
        url_de_pmid("38999999"),
    ]


def test_en_una_cita_mixta_solo_se_enlaza_el_respaldado():
    partes = partes_de_la_cita("Mezcla [PMID: 38123456, 99999999].")

    assert [(p.texto, p.es_enlace) for p in partes if p.texto.isdigit()] == [
        ("38123456", True),
        ("99999999", False),
    ]


def test_la_pagina_pinta_los_dos_enlaces(cliente, monkeypatch):
    cuerpo = pagina_con(monkeypatch, cliente, "Ambos [PMID: 38123456, 38999999].")

    cita = re.search(r'<span class="pmid">.*?</span>', cuerpo, re.S).group()
    assert cita.count("<a href=") == 2
    assert ">38123456</a>" in cita and ">38999999</a>" in cita


def test_los_separadores_de_la_cita_se_conservan():
    """La coma y el espacio entre PMIDs no se pierden al trocear."""
    partes = partes_de_la_cita("Ambos [PMID: 38123456, 38999999].")

    assert "".join(p.texto for p in partes) == "[PMID: 38123456, 38999999]"


@pytest.mark.parametrize(
    "cita",
    [
        "[PMID: 38123456]",
        "[PMID:38123456]",
        "[PMID: 38123456, 38999999]",
        "[PMID: 38123456,38999999]",
        "[PMID:  38123456 , 38999999 ]",
    ],
)
def test_trocear_nunca_altera_el_texto_de_la_cita(cita):
    """Invariante: esto marca dónde están los PMID, no reescribe el resumen."""
    partes = partes_de_la_cita(f"Texto {cita}.")

    assert "".join(p.texto for p in partes) == cita


# ------------------------------------------------------ escapado hostil


CONTENIDO_HOSTIL = (
    '<script>alert("xss")</script> y un "atributo" & un <b>bold</b> '
    "[PMID: 38123456]."
)


def test_el_marcado_del_resumen_se_escapa(cliente, monkeypatch):
    """El resumen lo escribe un modelo: si trae etiquetas, se ven como texto."""
    cuerpo = pagina_con(monkeypatch, cliente, CONTENIDO_HOSTIL)

    assert "<script>alert" not in cuerpo
    assert "&lt;script&gt;" in cuerpo
    assert "<b>bold</b>" not in cuerpo
    assert "&lt;b&gt;bold&lt;/b&gt;" in cuerpo


def test_el_enlace_sigue_funcionando_junto_al_marcado_hostil(cliente, monkeypatch):
    """Escapar el texto no puede romper el enlazado de la cita legítima."""
    cuerpo = pagina_con(monkeypatch, cliente, CONTENIDO_HOSTIL)

    assert ">38123456</a>" in cuerpo


def test_un_intento_de_cerrar_la_etiqueta_desde_la_cita_no_cuela(cliente, monkeypatch):
    """Lo más cercano a una inyección por la vía de la cita: texto pegado al
    PMID que intente salirse del `<a>`."""
    cuerpo = pagina_con(
        monkeypatch, cliente, 'Ver [PMID: 38123456]</a><script>x</script>.'
    )

    assert "<script>x</script>" not in cuerpo
    assert "&lt;script&gt;" in cuerpo

    # Acotado al bloque del resumen: el resto de la página tiene sus propios
    # enlaces (navegación, títulos de los artículos) y contarlos todos no
    # diría nada sobre la inyección.
    resumen = re.search(r'<div class="ps-summary">.*?</div>', cuerpo, re.S).group()
    assert "&lt;/a&gt;" in resumen          # el del texto, escapado
    assert resumen.count("</a>") == 1       # solo el de la cita, de verdad
    assert resumen.count("<a href=") == 1


def test_no_se_usa_safe_ni_markup_en_el_camino():
    """La garantía estructural: si algún día se montara el HTML en Python
    haría falta un `|safe`, y ese sería el agujero."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    modelos = (raiz / "src" / "paper_search" / "models.py").read_text(encoding="utf-8")
    plantilla = (raiz / "templates" / "index.html").read_text(encoding="utf-8")

    assert "Markup" not in modelos
    assert "<a " not in modelos  # el HTML no se monta aquí
    bloque = plantilla[plantilla.index('<span class="pmid">') :][:400]
    assert "|safe" not in bloque and "| safe" not in bloque


def test_la_url_del_enlace_solo_puede_ser_de_pubmed():
    """La URL se construye a partir de un PMID que ya validó el patrón de
    dígitos, así que no puede acabar siendo `javascript:` ni otro dominio."""
    for resumen in (
        "[PMID: 38123456]",
        "[PMID: 38123456, 38999999]",
    ):
        for parte in partes_de_la_cita(resumen):
            if parte.es_enlace:
                assert parte.url.startswith("https://pubmed.ncbi.nlm.nih.gov/")
                assert parte.texto.isdigit()


# --------------------------------- exportar.py NO cambia (no-regresión)


def test_el_texto_exportado_no_cambia_por_esto():
    """Las citas del texto exportado siguen en texto plano, y las referencias
    ya llevaban su enlace. Esta tarea es solo de la web."""
    resultado = ResultadoBusqueda(
        query="SCN1A",
        papers=PAPERS,
        resumen="Hallazgo [PMID: 38123456] y otro [PMID: 38999999].",
        dias=365,
    )

    texto = texto_para_notebooklm(resultado)

    # La cita va tal cual, sin marcado de ningún tipo.
    assert "[PMID: 38123456]" in texto
    assert "<a " not in texto
    assert "href=" not in texto
    # Y las referencias siguen trayendo su enlace, como ya hacían.
    assert "https://pubmed.ncbi.nlm.nih.gov/38123456/" in texto


def test_el_texto_exportado_es_identico_al_de_antes():
    """Se compara contra la salida esperada escrita a mano: si el enlazado se
    colara en el export, este test lo dice."""
    resultado = ResultadoBusqueda(
        query="SCN1A", papers=PAPERS[:1], resumen="Solo esto [PMID: 38123456].", dias=365
    )

    texto = texto_para_notebooklm(resultado)

    assert "RESUMEN\n" + "=" * 60 + "\nSolo esto [PMID: 38123456].\n" in texto


def test_segmentar_no_toca_el_resumen_original():
    """El texto que se exporta sale de `resultado.resumen`, y eso no se muta."""
    resumen = "Hallazgo [PMID: 38123456]."
    copia = str(resumen)

    segmentar_resumen(resumen, PMIDS)

    assert resumen == copia


# -------------------------------------- el enlazado ocurre en el servidor


def test_el_html_llega_enlazado_sin_javascript(cliente, monkeypatch):
    """Requisito explícito: se hace en el servidor, igual que exportar.py, para
    que sea testeable con pytest y no dependa de JS."""
    cuerpo = pagina_con(monkeypatch, cliente, "Hallazgo [PMID: 38123456].")

    # El enlace está en el HTML servido, no lo monta ningún script.
    assert ">38123456</a>" in cuerpo
    assert "pubmed.ncbi.nlm.nih.gov" not in _scripts_de(cuerpo)


def _scripts_de(html: str) -> str:
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S))
