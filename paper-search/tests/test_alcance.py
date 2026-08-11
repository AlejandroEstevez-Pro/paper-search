"""Tests del guardarraíl de alcance (solo enfermedades raras).

El cliente de Anthropic está siempre mockeado: la suite no hace llamadas reales
ni necesita una clave de API.
"""

from __future__ import annotations

import json

import pytest

from paper_search import buscar_y_resumir
from paper_search.alcance import (
    AMBIGUO,
    DENTRO_DE_ALCANCE,
    FUERA_DE_ALCANCE,
    NO_CONCLUYENTE,
    TerminoFueraDeAlcanceError,
    VerificadorAlcance,
)
from paper_search.models import Paper
from paper_search.summarizer import ResumenError, Summarizer

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="Variantes de SCN1A en el sindrome de Dravet",
        autores=("Garcia A",),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="Se identificaron 42 variantes nuevas.",
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
        self.opciones: list[dict] = []

    def with_options(self, **kwargs):
        self.opciones.append(kwargs)
        return self


class ClientPubMedFalso:
    def __init__(self, papers):
        self.papers = list(papers)
        self.llamadas: list[dict] = []

    def buscar_papers(self, termino, *, max_resultados=15, dias=730):
        self.llamadas.append(
            {"termino": termino, "max_resultados": max_resultados, "dias": dias}
        )
        return self.papers


def respuesta_json(veredicto: str, motivo: str = "motivo de prueba") -> RespuestaFalsa:
    return RespuestaFalsa(
        [BloqueTexto(json.dumps({"veredicto": veredicto, "motivo": motivo}))]
    )


def verificador_con(respuesta) -> tuple[VerificadorAlcance, ClientFalso]:
    client = ClientFalso(respuesta)
    return VerificadorAlcance(client=client), client


def summarizer_ok() -> Summarizer:
    return Summarizer(
        client=ClientFalso(RespuestaFalsa([BloqueTexto("Resumen [PMID: 38123456].")]))
    )


# ------------------------------------------------------------ verificar()


def test_termino_dentro_de_alcance():
    verificador, _ = verificador_con(respuesta_json(DENTRO_DE_ALCANCE))

    veredicto = verificador.verificar("SCN1A")

    assert veredicto.veredicto == DENTRO_DE_ALCANCE
    assert not veredicto.bloquea
    assert veredicto.aviso("SCN1A") is None


def test_termino_fuera_de_alcance():
    verificador, _ = verificador_con(
        respuesta_json(FUERA_DE_ALCANCE, "es una enfermedad común")
    )

    veredicto = verificador.verificar("gripe")

    assert veredicto.bloquea
    mensaje = veredicto.mensaje_bloqueo("gripe")
    assert "gripe" in mensaje
    assert "enfermedades raras" in mensaje
    assert "es una enfermedad común" in mensaje
    assert "PubMed" in mensaje  # deja claro que no se llegó a buscar


def test_termino_ambiguo_no_bloquea_pero_avisa():
    verificador, _ = verificador_con(respuesta_json(AMBIGUO, "sigla con varios usos"))

    veredicto = verificador.verificar("CDG")

    assert not veredicto.bloquea
    aviso = veredicto.aviso("CDG")
    assert "CDG" in aviso
    assert "sigla con varios usos" in aviso


def test_manda_modelo_prompt_esquema_y_timeout():
    verificador, client = verificador_con(respuesta_json(DENTRO_DE_ALCANCE))

    verificador.verificar("SCN1A")

    assert client.opciones == [{"timeout": verificador.timeout}]
    kwargs = client.messages.llamadas[0]
    assert kwargs["model"] == verificador.modelo
    assert "enfermedades raras" in kwargs["system"]
    formato = kwargs["output_config"]["format"]
    assert formato["type"] == "json_schema"
    assert set(formato["schema"]["required"]) == {"veredicto", "motivo"}
    assert kwargs["messages"][0]["role"] == "user"
    assert '"SCN1A"' in kwargs["messages"][0]["content"]


# ----------------------------------------------- fallos → no concluyente


def test_fallo_de_la_api_es_no_concluyente():
    verificador, _ = verificador_con(RuntimeError("timeout"))

    veredicto = verificador.verificar("SCN1A")

    assert veredicto.veredicto == NO_CONCLUYENTE
    assert not veredicto.bloquea
    assert "No se ha podido comprobar" in veredicto.aviso("SCN1A")


def test_sin_api_key_es_no_concluyente(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    verificador = VerificadorAlcance()  # sin cliente inyectado: lo crea al usarlo

    veredicto = verificador.verificar("SCN1A")

    assert veredicto.veredicto == NO_CONCLUYENTE


def test_un_fallo_que_no_es_la_clave_no_se_atribuye_a_la_clave(monkeypatch):
    """Con la clave puesta pero sin el paquete `anthropic`, el motivo era
    «falta la clave de la API» y mandaba a revisar algo que estaba bien."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    def crear_roto():
        raise ResumenError("Falta el paquete 'anthropic'. Instálalo con pip.")

    monkeypatch.setattr("paper_search.alcance._crear_client", crear_roto)
    verificador = VerificadorAlcance()

    veredicto = verificador.verificar("SCN1A")

    assert veredicto.veredicto == NO_CONCLUYENTE
    assert "falta la clave de la API" not in veredicto.motivo
    assert "anthropic" in veredicto.motivo


def test_json_invalido_es_no_concluyente():
    verificador, _ = verificador_con(RespuestaFalsa([BloqueTexto("esto no es JSON")]))

    assert verificador.verificar("SCN1A").veredicto == NO_CONCLUYENTE


def test_veredicto_desconocido_es_no_concluyente():
    verificador, _ = verificador_con(respuesta_json("quien_sabe"))

    assert verificador.verificar("SCN1A").veredicto == NO_CONCLUYENTE


def test_respuesta_vacia_es_no_concluyente():
    verificador, _ = verificador_con(RespuestaFalsa([]))

    assert verificador.verificar("SCN1A").veredicto == NO_CONCLUYENTE


def test_rechazo_del_modelo_es_no_concluyente():
    verificador, _ = verificador_con(RespuestaFalsa([], stop_reason="refusal"))

    assert verificador.verificar("SCN1A").veredicto == NO_CONCLUYENTE


# ------------------------------------------- orquestación (buscar_y_resumir)


def test_termino_valido_busca_sin_aviso():
    verificador, _ = verificador_con(respuesta_json(DENTRO_DE_ALCANCE))
    pubmed = ClientPubMedFalso(PAPERS)

    resultado = buscar_y_resumir(
        "SCN1A",
        verificar_resumen=False,  # la verificación del resumen tiene sus propios tests
        client=pubmed,
        summarizer=summarizer_ok(),
        verificador_alcance=verificador,
    )

    assert resultado.aviso_alcance is None
    assert resultado.resumen == "Resumen [PMID: 38123456]."
    assert len(pubmed.llamadas) == 1


def test_termino_fuera_de_alcance_bloquea_antes_de_pubmed():
    verificador, _ = verificador_con(
        respuesta_json(FUERA_DE_ALCANCE, "es una enfermedad común")
    )
    pubmed = ClientPubMedFalso(PAPERS)

    with pytest.raises(TerminoFueraDeAlcanceError) as excinfo:
        buscar_y_resumir(
            "gripe",
            client=pubmed,
            summarizer=summarizer_ok(),
            verificador_alcance=verificador,
        )

    assert "enfermedades raras" in str(excinfo.value)
    assert pubmed.llamadas == []  # PubMed no se llega a tocar


def test_termino_ambiguo_busca_con_aviso():
    verificador, _ = verificador_con(respuesta_json(AMBIGUO, "sigla con varios usos"))

    resultado = buscar_y_resumir(
        "CDG",
        verificar_resumen=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer_ok(),
        verificador_alcance=verificador,
    )

    assert "sigla con varios usos" in resultado.aviso_alcance
    assert resultado.resumen == "Resumen [PMID: 38123456]."


def test_fallo_de_verificacion_deja_pasar_con_aviso():
    """Fail-open documentado en docs/decisions.md: el fallo no bloquea."""
    verificador, _ = verificador_con(RuntimeError("la API se cayó"))
    pubmed = ClientPubMedFalso(PAPERS)

    resultado = buscar_y_resumir(
        "SCN1A",
        verificar_resumen=False,
        client=pubmed,
        summarizer=summarizer_ok(),
        verificador_alcance=verificador,
    )

    assert "No se ha podido comprobar" in resultado.aviso_alcance
    assert len(pubmed.llamadas) == 1
    assert resultado.resumen == "Resumen [PMID: 38123456]."


def test_se_puede_desactivar_la_verificacion():
    verificador, client = verificador_con(respuesta_json(FUERA_DE_ALCANCE))

    resultado = buscar_y_resumir(
        "gripe",
        verificar_alcance=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer_ok(),
        verificador_alcance=verificador,
    )

    assert client.messages.llamadas == []  # el verificador ni se usa
    assert resultado.aviso_alcance is None


def test_el_aviso_sobrevive_a_un_fallo_del_resumen():
    """El aviso de alcance y el error del resumen son independientes."""
    verificador, _ = verificador_con(respuesta_json(AMBIGUO, "término general"))
    summarizer_roto = Summarizer(client=ClientFalso(RuntimeError("API caída")))

    resultado = buscar_y_resumir(
        "epilepsia",
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer_roto,
        verificador_alcance=verificador,
    )

    assert "término general" in resultado.aviso_alcance
    assert resultado.resumen is None
    assert "API caída" in resultado.error_resumen


def test_el_json_del_resultado_incluye_el_aviso_de_alcance():
    verificador, _ = verificador_con(respuesta_json(AMBIGUO, "término general"))

    resultado = buscar_y_resumir(
        "epilepsia",
        verificar_resumen=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer_ok(),
        verificador_alcance=verificador,
    )

    datos = resultado.to_dict()
    assert "aviso_alcance" in datos
    assert "término general" in datos["aviso_alcance"]
