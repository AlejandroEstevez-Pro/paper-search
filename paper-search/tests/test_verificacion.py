"""Tests de la verificación automática del resumen.

El cliente de Anthropic está siempre mockeado: la suite no hace llamadas reales
ni necesita una clave de API.
"""

from __future__ import annotations

import json

import pytest

from paper_search import buscar_y_resumir
from paper_search.models import Paper
from paper_search.summarizer import ResumenError, Summarizer
from paper_search.verificacion import (
    APROBADO,
    MAX_INTENTOS,
    NO_CONCLUYENTE,
    RECHAZADO,
    VerificadorResumen,
    problemas_deterministas,
    resumir_con_verificacion,
)

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="Variantes de SCN1A en el sindrome de Dravet",
        autores=("Garcia A",),
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
        abstract="Cohorte de seguimiento a diez años.",
    ),
)

RESUMEN_LIMPIO = (
    "Los estudios recientes describen variantes nuevas [PMID: 38123456] y la "
    "evolución de la enfermedad a largo plazo [PMID: 38999999]."
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
    """Devuelve las respuestas en orden; la última se repite si hay más llamadas."""

    def __init__(self, respuestas):
        self._respuestas = list(respuestas)
        self.llamadas: list[dict] = []

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        respuesta = (
            self._respuestas.pop(0) if len(self._respuestas) > 1 else self._respuestas[0]
        )
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


class ClientFalso:
    def __init__(self, *respuestas):
        self.messages = MessagesFalso(respuestas)
        self.opciones: list[dict] = []

    def with_options(self, **kwargs):
        self.opciones.append(kwargs)
        return self


def respuesta_texto(texto: str) -> RespuestaFalsa:
    return RespuestaFalsa([BloqueTexto(texto)])


def veredicto_aprobado() -> RespuestaFalsa:
    return respuesta_texto(json.dumps({"aprobado": True, "problemas": []}))


def veredicto_rechazado(tipo: str, fragmento: str, detalle: str) -> RespuestaFalsa:
    return respuesta_texto(
        json.dumps(
            {
                "aprobado": False,
                "problemas": [
                    {"tipo": tipo, "fragmento": fragmento, "detalle": detalle}
                ],
            }
        )
    )


def summarizer_con(*respuestas) -> tuple[Summarizer, ClientFalso]:
    client = ClientFalso(*respuestas)
    return Summarizer(client=client), client


def verificador_con(*respuestas) -> tuple[VerificadorResumen, ClientFalso]:
    client = ClientFalso(*respuestas)
    return VerificadorResumen(client=client), client


# ----------------------------------------------- comprobación determinista


def test_resumen_con_pmids_validos_pasa_la_comprobacion_local():
    assert problemas_deterministas(RESUMEN_LIMPIO, ("38123456", "38999999")) == ()


def test_pmid_desconocido_se_detecta_sin_llamar_a_la_api():
    resumen = "Un hallazgo importante [PMID: 11111111]."

    problemas = problemas_deterministas(resumen, ("38123456",))

    assert len(problemas) == 1
    assert problemas[0].tipo == "pmid_desconocido"
    assert "11111111" in problemas[0].detalle


def test_resumen_sin_citas_se_rechaza_en_local():
    problemas = problemas_deterministas("Un resumen sin ninguna cita.", ("38123456",))

    assert len(problemas) == 1
    assert problemas[0].tipo == "sin_citas"


def test_cita_multiple_valida_cada_pmid():
    resumen = "Hallazgo doble [PMID: 38123456, 22222222]."

    problemas = problemas_deterministas(resumen, ("38123456", "38999999"))

    assert [p.tipo for p in problemas] == ["pmid_desconocido"]
    assert "22222222" in problemas[0].detalle


# ------------------------------------------------------------ verificar()


def test_resumen_limpio_se_aprueba():
    verificador, client = verificador_con(veredicto_aprobado())

    resultado = verificador.verificar(RESUMEN_LIMPIO, ("38123456", "38999999"))

    assert resultado.estado == APROBADO
    kwargs = client.messages.llamadas[0]
    assert kwargs["model"] == verificador.modelo
    assert "SIN CONSEJO MÉDICO" in kwargs["system"]
    assert "TRAZABILIDAD" in kwargs["system"]
    formato = kwargs["output_config"]["format"]
    assert formato["type"] == "json_schema"
    assert set(formato["schema"]["required"]) == {"aprobado", "problemas"}
    contenido = kwargs["messages"][0]["content"]
    assert "38123456, 38999999" in contenido
    assert RESUMEN_LIMPIO in contenido
    assert client.opciones == [{"timeout": verificador.timeout}]


def test_rechazo_trae_los_problemas():
    verificador, _ = verificador_con(
        veredicto_rechazado("consejo_medico", "consulte a su médico", "se dirige al lector")
    )

    resultado = verificador.verificar(RESUMEN_LIMPIO, ("38123456",))

    assert resultado.estado == RECHAZADO
    assert resultado.problemas[0].tipo == "consejo_medico"
    assert resultado.problemas[0].fragmento == "consulte a su médico"


def test_fallo_de_la_api_es_no_concluyente():
    verificador, _ = verificador_con(RuntimeError("timeout"))

    resultado = verificador.verificar(RESUMEN_LIMPIO, ("38123456",))

    assert resultado.estado == NO_CONCLUYENTE


def test_sin_api_key_es_no_concluyente(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    verificador = VerificadorResumen()  # sin cliente inyectado: lo crea al usarlo

    resultado = verificador.verificar(RESUMEN_LIMPIO, ("38123456",))

    assert resultado.estado == NO_CONCLUYENTE


def test_un_fallo_que_no_es_la_clave_no_se_atribuye_a_la_clave(monkeypatch):
    """Mismo arreglo que en `alcance.py`: el motivo debe ser el real."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    def crear_roto():
        raise ResumenError("Falta el paquete 'anthropic'. Instálalo con pip.")

    monkeypatch.setattr("paper_search.verificacion._crear_client", crear_roto)
    verificador = VerificadorResumen()

    resultado = verificador.verificar(RESUMEN_LIMPIO, ("38123456",))

    assert resultado.estado == NO_CONCLUYENTE
    assert "falta la clave de la API" not in resultado.motivo
    assert "anthropic" in resultado.motivo


def test_json_invalido_es_no_concluyente():
    verificador, _ = verificador_con(respuesta_texto("esto no es JSON"))

    assert verificador.verificar(RESUMEN_LIMPIO, ("1",)).estado == NO_CONCLUYENTE


def test_rechazo_del_modelo_es_no_concluyente():
    verificador, _ = verificador_con(RespuestaFalsa([], stop_reason="refusal"))

    assert verificador.verificar(RESUMEN_LIMPIO, ("1",)).estado == NO_CONCLUYENTE


# --------------------------------------------- resumir_con_verificacion()


def test_resumen_limpio_pasa_a_la_primera():
    summarizer, cliente_resumen = summarizer_con(respuesta_texto(RESUMEN_LIMPIO))
    verificador, cliente_verif = verificador_con(veredicto_aprobado())

    verificado = resumir_con_verificacion(
        "SCN1A", PAPERS, summarizer=summarizer, verificador=verificador
    )

    assert verificado == RESUMEN_LIMPIO
    assert len(cliente_resumen.messages.llamadas) == 1
    assert len(cliente_verif.messages.llamadas) == 1


def test_afirmacion_sin_pmid_fuerza_regeneracion_con_feedback():
    resumen_malo = "Hay muchas variantes nuevas. Además [PMID: 38123456]."
    summarizer, cliente_resumen = summarizer_con(
        respuesta_texto(resumen_malo), respuesta_texto(RESUMEN_LIMPIO)
    )
    verificador, _ = verificador_con(
        veredicto_rechazado(
            "afirmacion_sin_pmid",
            "Hay muchas variantes nuevas.",
            "afirmación factual sin cita",
        ),
        veredicto_aprobado(),
    )

    verificado = resumir_con_verificacion(
        "SCN1A", PAPERS, summarizer=summarizer, verificador=verificador
    )

    assert verificado == RESUMEN_LIMPIO
    # La regeneración lleva el feedback del verificador en el prompt.
    segundo_prompt = cliente_resumen.messages.llamadas[1]["messages"][0]["content"]
    assert "afirmacion_sin_pmid" in segundo_prompt
    assert "Hay muchas variantes nuevas." in segundo_prompt
    assert "sin introducir información nueva" in segundo_prompt


def test_consejo_medico_fuerza_regeneracion():
    resumen_malo = "Se recomienda tomar valproato [PMID: 38123456]."
    summarizer, _ = summarizer_con(
        respuesta_texto(resumen_malo), respuesta_texto(RESUMEN_LIMPIO)
    )
    verificador, _ = verificador_con(
        veredicto_rechazado(
            "consejo_medico", "Se recomienda tomar valproato", "recomendación al lector"
        ),
        veredicto_aprobado(),
    )

    verificado = resumir_con_verificacion(
        "SCN1A", PAPERS, summarizer=summarizer, verificador=verificador
    )

    assert verificado == RESUMEN_LIMPIO


def test_pmid_desconocido_se_rechaza_sin_gastar_llamada_de_verificacion():
    resumen_malo = "Hallazgo inventado [PMID: 11111111]."
    summarizer, cliente_resumen = summarizer_con(
        respuesta_texto(resumen_malo), respuesta_texto(RESUMEN_LIMPIO)
    )
    verificador, cliente_verif = verificador_con(veredicto_aprobado())

    verificado = resumir_con_verificacion(
        "SCN1A", PAPERS, summarizer=summarizer, verificador=verificador
    )

    assert verificado == RESUMEN_LIMPIO
    assert len(cliente_resumen.messages.llamadas) == 2
    # El primer intento se rechazó en local: el verificador solo vio el segundo.
    assert len(cliente_verif.messages.llamadas) == 1
    assert "11111111" in cliente_resumen.messages.llamadas[1]["messages"][0]["content"]


def test_reintentos_agotados_fallan_de_forma_visible():
    resumen_malo = "Se recomienda tomar valproato [PMID: 38123456]."
    summarizer, cliente_resumen = summarizer_con(respuesta_texto(resumen_malo))
    verificador, _ = verificador_con(
        veredicto_rechazado(
            "consejo_medico", "Se recomienda tomar valproato", "recomendación al lector"
        )
    )

    with pytest.raises(ResumenError) as excinfo:
        resumir_con_verificacion(
            "SCN1A", PAPERS, summarizer=summarizer, verificador=verificador
        )

    mensaje = str(excinfo.value)
    assert str(MAX_INTENTOS) in mensaje
    assert "consejo_medico" in mensaje
    assert "Se recomienda tomar valproato" in mensaje
    assert len(cliente_resumen.messages.llamadas) == MAX_INTENTOS


def test_fallo_del_verificador_cuenta_como_intento_fallido():
    """Fail-closed: sin verificación completada, el resumen no se entrega."""
    summarizer, cliente_resumen = summarizer_con(respuesta_texto(RESUMEN_LIMPIO))
    verificador, _ = verificador_con(RuntimeError("la API se cayó"))

    with pytest.raises(ResumenError) as excinfo:
        resumir_con_verificacion(
            "SCN1A", PAPERS, summarizer=summarizer, verificador=verificador
        )

    mensaje = str(excinfo.value)
    assert "no_verificado" in mensaje
    assert "no se pudo verificar" in mensaje
    assert len(cliente_resumen.messages.llamadas) == MAX_INTENTOS


def test_fallo_puntual_del_verificador_se_recupera_en_el_reintento():
    summarizer, cliente_resumen = summarizer_con(respuesta_texto(RESUMEN_LIMPIO))
    verificador, _ = verificador_con(RuntimeError("timeout"), veredicto_aprobado())

    verificado = resumir_con_verificacion(
        "SCN1A", PAPERS, summarizer=summarizer, verificador=verificador
    )

    assert verificado == RESUMEN_LIMPIO
    assert len(cliente_resumen.messages.llamadas) == 2
    # La regeneración explica que el intento anterior no se pudo verificar.
    segundo_prompt = cliente_resumen.messages.llamadas[1]["messages"][0]["content"]
    assert "no_verificado" in segundo_prompt
    assert "no se pudo verificar" in segundo_prompt


def test_rechazo_sin_problemas_detallados_tambien_regenera():
    summarizer, cliente_resumen = summarizer_con(
        respuesta_texto(RESUMEN_LIMPIO), respuesta_texto(RESUMEN_LIMPIO)
    )
    verificador, _ = verificador_con(
        respuesta_texto(json.dumps({"aprobado": False, "problemas": []})),
        veredicto_aprobado(),
    )

    verificado = resumir_con_verificacion(
        "SCN1A", PAPERS, summarizer=summarizer, verificador=verificador
    )

    assert verificado == RESUMEN_LIMPIO
    assert len(cliente_resumen.messages.llamadas) == 2


# ------------------------------------------- orquestación (buscar_y_resumir)


class ClientPubMedFalso:
    def __init__(self, papers):
        self.papers = list(papers)

    def buscar_papers(self, termino, *, max_resultados=15, dias=730):
        return self.papers


def test_buscar_y_resumir_entrega_el_resumen_verificado():
    summarizer, _ = summarizer_con(respuesta_texto(RESUMEN_LIMPIO))
    verificador, _ = verificador_con(veredicto_aprobado())

    resultado = buscar_y_resumir(
        "SCN1A",
        verificar_alcance=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer,
        verificador_resumen=verificador,
    )

    assert resultado.resumen == RESUMEN_LIMPIO
    assert resultado.error_resumen is None


def test_buscar_y_resumir_con_reintentos_agotados_conserva_los_papers():
    resumen_malo = "Consulte a su médico [PMID: 38123456]."
    summarizer, _ = summarizer_con(respuesta_texto(resumen_malo))
    verificador, _ = verificador_con(
        veredicto_rechazado("consejo_medico", "Consulte a su médico", "se dirige al lector")
    )

    resultado = buscar_y_resumir(
        "SCN1A",
        verificar_alcance=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer,
        verificador_resumen=verificador,
    )

    assert resultado.resumen is None
    assert "no superó la verificación automática" in resultado.error_resumen
    assert "consejo_medico" in resultado.error_resumen
    assert [p.pmid for p in resultado.papers] == ["38123456", "38999999"]


def test_buscar_y_resumir_descarta_el_resumen_si_no_se_pudo_verificar():
    """Fail-closed: el fallo del verificador nunca cuela un resumen sin verificar."""
    summarizer, _ = summarizer_con(respuesta_texto(RESUMEN_LIMPIO))
    verificador, _ = verificador_con(RuntimeError("timeout"))

    resultado = buscar_y_resumir(
        "SCN1A",
        verificar_alcance=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer,
        verificador_resumen=verificador,
    )

    assert resultado.resumen is None
    assert "no se pudo verificar" in resultado.error_resumen
    assert [p.pmid for p in resultado.papers] == ["38123456", "38999999"]


def test_se_puede_desactivar_la_verificacion_del_resumen():
    summarizer, _ = summarizer_con(respuesta_texto("Sin citas, pero da igual."))
    verificador, cliente_verif = verificador_con(veredicto_aprobado())

    resultado = buscar_y_resumir(
        "SCN1A",
        verificar_alcance=False,
        verificar_resumen=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer,
        verificador_resumen=verificador,
    )

    assert resultado.resumen == "Sin citas, pero da igual."
    assert cliente_verif.messages.llamadas == []
