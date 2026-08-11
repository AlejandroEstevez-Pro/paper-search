"""Tests del registro de acciones (auditoría y base del historial de Fase 3).

BD SQLite en memoria y clientes de Anthropic/PubMed mockeados.
"""

from __future__ import annotations

import json

import pytest

from paper_search import buscar_y_resumir
from paper_search.alcance import (
    DENTRO_DE_ALCANCE,
    FUERA_DE_ALCANCE,
    TerminoFueraDeAlcanceError,
    VerificadorAlcance,
)
from paper_search.db import abrir_db
from paper_search.limites import LimiteAlcanzadoError, LimitesUso
from paper_search.models import Paper
from paper_search.pubmed_client import PubMedError
from paper_search.registro import RegistroAcciones
from paper_search.summarizer import Summarizer
from paper_search.verificacion import VerificadorResumen

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="Variantes de SCN1A",
        autores=("Garcia A",),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="42 variantes.",
    ),
    Paper(pmid="38999999", titulo="Historia natural", abstract="Cohorte a 10 años."),
)
RESUMEN = (
    "Variantes nuevas [PMID: 38123456] y evolución a largo plazo [PMID: 38999999]."
)


@pytest.fixture
def db():
    conn = abrir_db(":memory:")
    yield conn
    conn.close()


def acciones(db):
    return db.execute("SELECT * FROM acciones ORDER BY id").fetchall()


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
    def __init__(self, papers=None, error=None):
        self.papers = list(papers or [])
        self.error = error

    def buscar_papers(self, termino, *, max_resultados=15, dias=730):
        if self.error is not None:
            raise self.error
        return self.papers


def respuesta_texto(texto: str) -> RespuestaFalsa:
    return RespuestaFalsa([BloqueTexto(texto)])


def alcance_json(veredicto: str, motivo: str = "motivo") -> RespuestaFalsa:
    return respuesta_texto(json.dumps({"veredicto": veredicto, "motivo": motivo}))


def verificacion_aprobada() -> RespuestaFalsa:
    return respuesta_texto(json.dumps({"aprobado": True, "problemas": []}))


def buscar(db, *, pubmed=None, alcance=None, resumen_respuesta=None, **kwargs):
    return buscar_y_resumir(
        "SCN1A",
        max_resultados=5,
        dias=365,
        db=db,
        client=pubmed if pubmed is not None else ClientPubMedFalso(PAPERS),
        summarizer=Summarizer(
            client=ClientFalso(resumen_respuesta or respuesta_texto(RESUMEN))
        ),
        verificador_alcance=VerificadorAlcance(
            client=ClientFalso(alcance or alcance_json(DENTRO_DE_ALCANCE))
        ),
        verificador_resumen=VerificadorResumen(client=ClientFalso(verificacion_aprobada())),
        **kwargs,
    )


# --------------------------------------------------------- unidad (registro)


def test_registrar_guarda_todos_los_campos(db):
    registro = RegistroAcciones(db, ahora=lambda: "2026-08-10T12:00:00+00:00")

    accion_id = registro.registrar(
        termino="SCN1A",
        resultado="exito",
        max_resultados=5,
        dias=365,
        desde_cache=True,
        llamadas_claude=3,
        pmids=["38123456", "38999999"],
    )

    fila = acciones(db)[0]
    assert fila["id"] == accion_id
    assert fila["timestamp"] == "2026-08-10T12:00:00+00:00"
    assert fila["termino"] == "SCN1A"
    assert (fila["max_resultados"], fila["dias"]) == (5, 365)
    assert fila["resultado"] == "exito"
    assert fila["desde_cache"] == 1
    assert fila["llamadas_claude"] == 3
    assert json.loads(fila["pmids"]) == ["38123456", "38999999"]


def test_un_resultado_desconocido_es_error_de_uso(db):
    with pytest.raises(ValueError, match="Resultado desconocido"):
        RegistroAcciones(db).registrar(termino="x", resultado="inventado")


def test_guardar_papers_hace_upsert(db):
    registro = RegistroAcciones(db)
    registro.guardar_papers(PAPERS)
    actualizado = Paper(pmid="38123456", titulo="Título corregido", abstract="a")
    registro.guardar_papers([actualizado])

    filas = db.execute("SELECT * FROM papers ORDER BY pmid").fetchall()
    assert len(filas) == 2  # sin duplicar
    assert filas[0]["titulo"] == "Título corregido"
    assert json.loads(filas[1]["autores"]) == []


# ------------------------------------------- orquestación (buscar_y_resumir)


def test_se_registra_una_busqueda_exitosa(db):
    buscar(db)

    fila = acciones(db)[0]
    assert fila["resultado"] == "exito"
    assert fila["termino"] == "SCN1A"
    assert fila["desde_cache"] == 0
    assert fila["llamadas_claude"] == 3  # alcance + resumen + verificación
    assert json.loads(fila["pmids"]) == ["38123456", "38999999"]
    assert fila["cache_id"] is not None  # el resumen quedó cacheado
    # Los papers quedaron en su tabla para el historial de Fase 3.
    assert db.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"] == 2


def test_se_registra_un_bloqueo_por_alcance(db):
    with pytest.raises(TerminoFueraDeAlcanceError):
        buscar(db, alcance=alcance_json(FUERA_DE_ALCANCE, "enfermedad común"))

    fila = acciones(db)[0]
    assert fila["resultado"] == "bloqueada_alcance"
    assert fila["detalle"] == "enfermedad común"
    assert fila["llamadas_claude"] == 1  # solo la llamada del guardarraíl
    assert fila["pmids"] is None  # nunca se llegó a PubMed


def test_se_registra_un_error_de_resumen(db):
    with_error = Summarizer(client=ClientFalso(RuntimeError("API caída")))
    resultado = buscar_y_resumir(
        "SCN1A",
        db=db,
        verificar_alcance=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=with_error,
        verificador_resumen=VerificadorResumen(client=ClientFalso(verificacion_aprobada())),
    )

    assert resultado.error_resumen is not None
    fila = acciones(db)[0]
    assert fila["resultado"] == "error_resumen"
    assert "API caída" in fila["detalle"]
    # Los papers reales sí se obtuvieron y quedan referenciados.
    assert json.loads(fila["pmids"]) == ["38123456", "38999999"]


def test_se_registra_una_busqueda_servida_desde_cache(db):
    buscar(db)  # genera y cachea
    buscar(db)  # hit

    filas = acciones(db)
    assert len(filas) == 2
    assert filas[1]["resultado"] == "exito"
    assert filas[1]["desde_cache"] == 1
    assert filas[1]["llamadas_claude"] == 0  # veredicto y resumen cacheados
    assert filas[1]["cache_id"] == filas[0]["cache_id"]  # mismo resumen


def test_se_registra_un_bloqueo_por_limite(db):
    limites = LimitesUso(db, max_busquedas=1, max_llamadas=100)
    buscar(db, limites=limites)

    with pytest.raises(LimiteAlcanzadoError):
        buscar(db, limites=limites)

    filas = acciones(db)
    assert filas[1]["resultado"] == "bloqueada_limite"
    assert "búsquedas" in filas[1]["detalle"]
    assert filas[1]["llamadas_claude"] == 0


def test_se_registra_una_busqueda_sin_resultados(db):
    buscar(db, pubmed=ClientPubMedFalso([]))

    fila = acciones(db)[0]
    assert fila["resultado"] == "sin_resultados"
    assert fila["pmids"] is None


def test_se_registra_un_error_de_pubmed(db):
    with pytest.raises(PubMedError):
        buscar(db, pubmed=ClientPubMedFalso(error=PubMedError("PubMed 503")))

    fila = acciones(db)[0]
    assert fila["resultado"] == "error_pubmed"
    assert "PubMed 503" in fila["detalle"]


def test_sin_db_no_se_registra_nada(db):
    # `db` solo se usa aquí para comprobar que la OTRA búsqueda (sin db) no
    # escribió nada en ninguna parte.
    buscar(None)

    assert acciones(db) == []
