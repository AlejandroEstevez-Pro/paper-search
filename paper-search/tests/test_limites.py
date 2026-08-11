"""Tests de los límites de uso diarios (búsquedas y llamadas a Claude).

BD SQLite en memoria, cliente de Anthropic mockeado y reloj inyectado: nada
depende del día real ni de APIs externas. El rate limit hacia PubMed es otra
cosa y tiene sus tests en `test_pubmed_client.py`.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from paper_search import buscar_y_resumir
from paper_search.alcance import DENTRO_DE_ALCANCE, VerificadorAlcance
from paper_search.db import abrir_db
from paper_search.limites import (
    LIMITE_BUSQUEDAS_POR_DEFECTO,
    LIMITE_LLAMADAS_POR_DEFECTO,
    LimiteAlcanzadoError,
    LimitesUso,
    limite_configurado,
)
from paper_search.models import Paper
from paper_search.summarizer import Summarizer
from paper_search.verificacion import VerificadorResumen

PAPERS = (
    Paper(pmid="38123456", titulo="Variantes de SCN1A", abstract="42 variantes."),
)
RESUMEN = "Variantes nuevas [PMID: 38123456]."


@pytest.fixture
def db():
    conn = abrir_db(":memory:")
    yield conn
    conn.close()


# ------------------------------------------------------------------- dobles


class BloqueTexto:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class RespuestaFalsa:
    def __init__(self, bloques, stop_reason="end_turn"):
        self.content = bloques
        self.stop_reason = stop_reason
        self.stop_details = None


class MessagesFalso:
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

    def with_options(self, **kwargs):
        return self


class ClientPubMedFalso:
    def __init__(self, papers):
        self.papers = list(papers)
        self.llamadas: list[dict] = []

    def buscar_papers(self, termino, *, max_resultados=15, dias=730):
        self.llamadas.append({"termino": termino})
        return self.papers


def respuesta_texto(texto: str) -> RespuestaFalsa:
    return RespuestaFalsa([BloqueTexto(texto)])


def alcance_ok() -> RespuestaFalsa:
    return respuesta_texto(
        json.dumps({"veredicto": DENTRO_DE_ALCANCE, "motivo": "gen"})
    )


def verificacion_aprobada() -> RespuestaFalsa:
    return respuesta_texto(json.dumps({"aprobado": True, "problemas": []}))


def verificacion_rechazada() -> RespuestaFalsa:
    return respuesta_texto(
        json.dumps(
            {
                "aprobado": False,
                "problemas": [
                    {
                        "tipo": "afirmacion_sin_pmid",
                        "fragmento": "x",
                        "detalle": "sin cita",
                    }
                ],
            }
        )
    )


def busqueda_completa(db, limites, *, respuestas_verificacion=None):
    """Búsqueda con alcance + resumen + verificación, todo mockeado."""
    cliente_alcance = ClientFalso(alcance_ok())
    respuestas = respuestas_verificacion or [verificacion_aprobada()]
    return buscar_y_resumir(
        "SCN1A",
        db=db,
        limites=limites,
        client=ClientPubMedFalso(PAPERS),
        summarizer=Summarizer(client=ClientFalso(respuesta_texto(RESUMEN))),
        verificador_alcance=VerificadorAlcance(client=cliente_alcance),
        verificador_resumen=VerificadorResumen(client=ClientFalso(*respuestas)),
    )


# --------------------------------------------------------- unidad (LimitesUso)


def test_por_debajo_del_limite_no_pasa_nada(db):
    limites = LimitesUso(db, max_busquedas=2, max_llamadas=10)
    limites.registrar_busqueda()

    limites.comprobar()  # no lanza

    assert limites.uso_de_hoy() == (1, 0)


def test_limite_de_busquedas_alcanzado(db):
    limites = LimitesUso(db, max_busquedas=2, max_llamadas=100, hoy=lambda: date(2026, 8, 10))
    limites.registrar_busqueda()
    limites.registrar_busqueda()

    with pytest.raises(LimiteAlcanzadoError) as excinfo:
        limites.comprobar()

    mensaje = str(excinfo.value)
    assert "búsquedas" in mensaje
    assert "2 de 2" in mensaje
    assert "2026-08-11" in mensaje  # cuándo se resetea
    assert "PAPER_SEARCH_MAX_BUSQUEDAS_DIA" in mensaje


def test_limite_de_llamadas_alcanzado(db):
    limites = LimitesUso(db, max_busquedas=100, max_llamadas=3, hoy=lambda: date(2026, 8, 10))
    for _ in range(3):
        limites.registrar_llamada_claude()

    with pytest.raises(LimiteAlcanzadoError) as excinfo:
        limites.comprobar()

    mensaje = str(excinfo.value)
    assert "Claude" in mensaje
    assert "3 de 3" in mensaje
    assert "2026-08-11" in mensaje


def test_el_cambio_de_dia_resetea_los_contadores(db):
    dia_actual = [date(2026, 8, 10)]
    limites = LimitesUso(db, max_busquedas=1, max_llamadas=1, hoy=lambda: dia_actual[0])
    limites.registrar_busqueda()
    limites.registrar_llamada_claude()
    with pytest.raises(LimiteAlcanzadoError):
        limites.comprobar()

    dia_actual[0] = date(2026, 8, 11)  # medianoche: cambia el día

    limites.comprobar()  # no lanza: contadores a cero
    assert limites.uso_de_hoy() == (0, 0)
    # El uso del día anterior queda como histórico, no se borra.
    fila = db.execute(
        "SELECT busquedas, llamadas_claude FROM uso_diario WHERE dia = '2026-08-10'"
    ).fetchone()
    assert (fila["busquedas"], fila["llamadas_claude"]) == (1, 1)


def test_limites_configurables_por_entorno(monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_MAX_BUSQUEDAS_DIA", "5")
    assert limite_configurado("PAPER_SEARCH_MAX_BUSQUEDAS_DIA", 50) == 5

    monkeypatch.setenv("PAPER_SEARCH_MAX_BUSQUEDAS_DIA", "-1")
    assert limite_configurado("PAPER_SEARCH_MAX_BUSQUEDAS_DIA", 50) == 50

    monkeypatch.delenv("PAPER_SEARCH_MAX_BUSQUEDAS_DIA", raising=False)
    assert (
        limite_configurado("PAPER_SEARCH_MAX_BUSQUEDAS_DIA", LIMITE_BUSQUEDAS_POR_DEFECTO)
        == LIMITE_BUSQUEDAS_POR_DEFECTO
    )
    assert (
        limite_configurado("PAPER_SEARCH_MAX_LLAMADAS_DIA", LIMITE_LLAMADAS_POR_DEFECTO)
        == LIMITE_LLAMADAS_POR_DEFECTO
    )


# ------------------------------------------- orquestación (buscar_y_resumir)


def test_una_busqueda_con_resumen_cuenta_cada_llamada(db):
    limites = LimitesUso(db, max_busquedas=10, max_llamadas=10)

    busqueda_completa(db, limites)

    # alcance (1) + resumen (1) + verificación (1) = 3, no "una por búsqueda".
    assert limites.uso_de_hoy() == (1, 3)


def test_los_reintentos_de_verificacion_tambien_cuentan(db):
    limites = LimitesUso(db, max_busquedas=10, max_llamadas=10)

    busqueda_completa(
        db,
        limites,
        respuestas_verificacion=[verificacion_rechazada(), verificacion_aprobada()],
    )

    # alcance (1) + resumen (2 intentos) + verificación (2) = 5.
    assert limites.uso_de_hoy() == (1, 5)


def test_limite_de_busquedas_bloquea_antes_de_tocar_nada(db):
    limites = LimitesUso(db, max_busquedas=1, max_llamadas=100)
    busqueda_completa(db, limites)  # consume la única búsqueda del día

    pubmed = ClientPubMedFalso(PAPERS)
    cliente_alcance = ClientFalso(alcance_ok())
    with pytest.raises(LimiteAlcanzadoError, match="búsquedas"):
        buscar_y_resumir(
            "MECP2",
            db=db,
            limites=limites,
            client=pubmed,
            verificador_alcance=VerificadorAlcance(client=cliente_alcance),
        )

    assert pubmed.llamadas == []  # ni PubMed...
    assert cliente_alcance.messages.llamadas == []  # ...ni Claude


def test_limite_de_llamadas_bloquea_la_siguiente_busqueda(db):
    limites = LimitesUso(db, max_busquedas=100, max_llamadas=3)
    busqueda_completa(db, limites)  # consume las 3 llamadas del día

    with pytest.raises(LimiteAlcanzadoError, match="Claude"):
        busqueda_completa(db, limites)


def test_una_busqueda_en_marcha_termina_aunque_cruce_el_limite(db):
    # Con límite 2, la búsqueda (que consume 3) arranca porque al inicio va
    # por debajo, y se termina entera: nunca se aborta trabajo a medias.
    limites = LimitesUso(db, max_busquedas=10, max_llamadas=2)

    resultado = busqueda_completa(db, limites)

    assert resultado.resumen == RESUMEN
    assert limites.uso_de_hoy() == (1, 3)
    with pytest.raises(LimiteAlcanzadoError):
        limites.comprobar()  # la siguiente ya no arranca


def test_un_cache_hit_no_consume_llamadas(db):
    limites = LimitesUso(db, max_busquedas=10, max_llamadas=10)
    busqueda_completa(db, limites)  # genera y cachea (resumen + veredicto)

    busqueda_completa(db, limites)  # todo desde caché

    busquedas, llamadas = limites.uso_de_hoy()
    assert busquedas == 2  # la búsqueda sí cuenta
    assert llamadas == 3  # pero no ha habido ninguna llamada nueva a Claude


def test_sin_db_ni_limites_no_se_limita_nada():
    for _ in range(3):
        resultado = buscar_y_resumir(
            "SCN1A",
            client=ClientPubMedFalso(PAPERS),
            summarizer=Summarizer(client=ClientFalso(respuesta_texto(RESUMEN))),
            verificar_alcance=False,
            verificar_resumen=False,
        )
    assert resultado.resumen == RESUMEN
