"""Tests del generador de resúmenes.

El cliente de Anthropic está siempre mockeado: la suite no hace llamadas reales
ni necesita una clave de API.
"""

from __future__ import annotations

import pytest

from paper_search import buscar_y_resumir
from paper_search.models import Paper, ResultadoBusqueda
from paper_search.summarizer import (
    FaltaAPIKeyError,
    ResumenError,
    Summarizer,
    construir_prompt,
)

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="Variantes de SCN1A en el sindrome de Dravet",
        autores=("Garcia A", "Smith JR"),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="Se identificaron 42 variantes nuevas en una cohorte de 300 pacientes.",
    ),
    Paper(
        pmid="38999999",
        titulo="Historia natural de una encefalopatia epileptica",
        autores=("Lopez B",),
        revista="Orphanet J Rare Dis",
        fecha="2023",
        abstract="",
    ),
)


# ------------------------------------------------------------------- dobles


class BloqueTexto:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class RespuestaFalsa:
    def __init__(self, bloques, stop_reason="end_turn", stop_details=None):
        self.content = bloques
        self.stop_reason = stop_reason
        self.stop_details = stop_details


class MessagesFalso:
    def __init__(self, respuesta):
        self._respuesta = respuesta
        self.llamadas: list[dict] = []

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        if isinstance(self._respuesta, Exception):
            raise self._respuesta
        return self._respuesta


class ClientFalso:
    def __init__(self, respuesta):
        self.messages = MessagesFalso(respuesta)


def summarizer_con(respuesta) -> tuple[Summarizer, ClientFalso]:
    client = ClientFalso(respuesta)
    return Summarizer(client=client), client


# ------------------------------------------------------------------- resumen


def test_devuelve_el_texto_del_modelo_tal_cual():
    texto = "Los estudios recientes describen nuevas variantes [PMID: 38123456]."
    summarizer, _ = summarizer_con(RespuestaFalsa([BloqueTexto(texto)]))

    assert summarizer.resumir("SCN1A", PAPERS) == texto


def test_concatena_varios_bloques_de_texto():
    summarizer, _ = summarizer_con(
        RespuestaFalsa([BloqueTexto("Primera parte."), BloqueTexto("Segunda parte.")])
    )

    assert summarizer.resumir("SCN1A", PAPERS) == "Primera parte.\nSegunda parte."


def test_manda_el_modelo_y_el_system_prompt_esperados():
    summarizer, client = summarizer_con(RespuestaFalsa([BloqueTexto("ok")]))

    summarizer.resumir("SCN1A", PAPERS)

    kwargs = client.messages.llamadas[0]
    assert kwargs["model"] == summarizer.modelo
    assert "PMID" in kwargs["system"]
    # El resumen no puede dar consejo médico ni salirse de los abstracts.
    assert "NO des consejo médico" in kwargs["system"]
    assert "ÚNICAMENTE" in kwargs["system"]
    assert kwargs["messages"][0]["role"] == "user"


def test_resumir_sin_papers_es_un_error_de_uso():
    summarizer, client = summarizer_con(RespuestaFalsa([BloqueTexto("ok")]))

    with pytest.raises(ValueError):
        summarizer.resumir("SCN1A", [])

    assert client.messages.llamadas == []


# -------------------------------------------------------------------- prompt


def test_el_prompt_lleva_pmid_y_abstract_de_cada_paper():
    prompt = construir_prompt("SCN1A", PAPERS)

    for paper in PAPERS:
        assert f"PMID: {paper.pmid}" in prompt
        assert paper.titulo in prompt
    assert "42 variantes nuevas" in prompt
    assert "SCN1A" in prompt


def test_el_prompt_marca_los_papers_sin_abstract():
    prompt = construir_prompt("SCN1A", PAPERS)

    assert "(sin abstract disponible)" in prompt


def test_el_prompt_trunca_abstracts_desmesurados():
    paper = Paper(pmid="1", titulo="t", abstract="x" * 20000)

    prompt = construir_prompt("t", [paper])

    assert "abstract truncado" in prompt
    assert len(prompt) < 10000


# -------------------------------------------------------------------- fallos


def test_sin_ANTHROPIC_API_KEY_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    summarizer = Summarizer()  # sin cliente inyectado: lo crea al usarlo

    with pytest.raises(FaltaAPIKeyError) as excinfo:
        summarizer.resumir("SCN1A", PAPERS)

    mensaje = str(excinfo.value)
    assert "ANTHROPIC_API_KEY" in mensaje
    assert "export" in mensaje  # dice cómo arreglarlo


def test_error_de_la_api_se_convierte_en_ResumenError():
    summarizer, _ = summarizer_con(RuntimeError("503 overloaded_error"))

    with pytest.raises(ResumenError) as excinfo:
        summarizer.resumir("SCN1A", PAPERS)

    assert "503 overloaded_error" in str(excinfo.value)


def test_respuesta_vacia_se_convierte_en_ResumenError():
    summarizer, _ = summarizer_con(RespuestaFalsa([]))

    with pytest.raises(ResumenError, match="vacía"):
        summarizer.resumir("SCN1A", PAPERS)


def test_un_rechazo_del_modelo_no_produce_resumen():
    class Detalles:
        explanation = "contenido no permitido"

    summarizer, _ = summarizer_con(
        RespuestaFalsa([], stop_reason="refusal", stop_details=Detalles())
    )

    with pytest.raises(ResumenError, match="declinó"):
        summarizer.resumir("SCN1A", PAPERS)


# ------------------------------------------------- orquestación (buscar_y_resumir)


class ClientPubMedFalso:
    def __init__(self, papers):
        self.papers = list(papers)
        self.llamadas: list[dict] = []

    def buscar_papers(self, termino, *, max_resultados=15, dias=730):
        self.llamadas.append(
            {"termino": termino, "max_resultados": max_resultados, "dias": dias}
        )
        return self.papers


def test_buscar_y_resumir_devuelve_papers_y_resumen():
    summarizer, _ = summarizer_con(RespuestaFalsa([BloqueTexto("Resumen [PMID: 38123456].")]))

    resultado = buscar_y_resumir(
        "SCN1A",
        max_resultados=5,
        dias=365,
        verificar_resumen=False,  # la verificación tiene sus propios tests
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer,
    )

    assert isinstance(resultado, ResultadoBusqueda)
    assert resultado.total == 2
    assert resultado.resumen == "Resumen [PMID: 38123456]."
    assert resultado.error_resumen is None
    assert resultado.dias == 365


def test_sin_resultados_no_se_pide_resumen():
    summarizer, client = summarizer_con(RespuestaFalsa([BloqueTexto("no deberia usarse")]))

    resultado = buscar_y_resumir(
        "termino-inexistente", client=ClientPubMedFalso([]), summarizer=summarizer
    )

    assert resultado.total == 0
    assert resultado.resumen is None
    assert resultado.error_resumen is None
    assert client.messages.llamadas == []


def test_si_falla_el_resumen_se_conservan_los_papers_y_se_explica_el_motivo():
    """Nunca se inventa un resumen: o hay resumen real o hay motivo explícito."""
    summarizer, _ = summarizer_con(RuntimeError("la API se cayó"))

    resultado = buscar_y_resumir(
        "SCN1A", client=ClientPubMedFalso(PAPERS), summarizer=summarizer
    )

    assert resultado.resumen is None
    assert "la API se cayó" in resultado.error_resumen
    assert [p.pmid for p in resultado.papers] == ["38123456", "38999999"]


def test_falta_de_api_key_no_descarta_los_papers_ya_obtenidos(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    resultado = buscar_y_resumir("SCN1A", client=ClientPubMedFalso(PAPERS))

    assert resultado.resumen is None
    assert "ANTHROPIC_API_KEY" in resultado.error_resumen
    assert resultado.total == 2


def test_se_puede_pedir_solo_la_busqueda_sin_resumen():
    summarizer, client = summarizer_con(RespuestaFalsa([BloqueTexto("no deberia usarse")]))

    resultado = buscar_y_resumir(
        "SCN1A", resumir=False, client=ClientPubMedFalso(PAPERS), summarizer=summarizer
    )

    assert resultado.total == 2
    assert resultado.resumen is None
    assert client.messages.llamadas == []


# ------------------------------------------------------ serialización estable


def test_el_json_expone_el_contrato_documentado():
    resultado = buscar_y_resumir(
        "SCN1A",
        verificar_resumen=False,  # la verificación tiene sus propios tests
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer_con(RespuestaFalsa([BloqueTexto("r")]))[0],
    )

    datos = resultado.to_dict()

    assert set(datos) >= {"query", "resumen", "papers"}
    assert set(datos["papers"][0]) == {
        "pmid",
        "titulo",
        "autores",
        "revista",
        "fecha",
        "abstract",
        "url",
        "orden_relevancia",
    }
    assert datos["papers"][0]["url"].endswith("/38123456/")
    assert "no es una herramienta de diagnóstico" in datos["aviso"].lower()
