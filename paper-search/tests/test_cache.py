"""Tests de la caché local de resúmenes y veredictos de alcance.

Toda la persistencia va contra una BD SQLite en memoria y el cliente de
Anthropic está siempre mockeado.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from paper_search import buscar_y_resumir
from paper_search.alcance import (
    AMBIGUO,
    DENTRO_DE_ALCANCE,
    FUERA_DE_ALCANCE,
    NO_CONCLUYENTE,
    TerminoFueraDeAlcanceError,
    VeredictoAlcance,
    VerificadorAlcance,
)
from paper_search.cache import (
    TTL_DIAS_POR_DEFECTO,
    CacheResumenes,
    CacheVeredictos,
    ttl_dias_configurado,
)
from paper_search.db import abrir_db
from paper_search.models import Paper
from paper_search.summarizer import Summarizer
from paper_search.verificacion import VerificadorResumen

PAPERS = (
    Paper(pmid="38123456", titulo="Variantes de SCN1A", abstract="42 variantes."),
    Paper(pmid="38999999", titulo="Historia natural", abstract="Cohorte a 10 años."),
)
PMIDS = ["38123456", "38999999"]
RESUMEN = (
    "Variantes nuevas [PMID: 38123456] y evolución a largo plazo [PMID: 38999999]."
)


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

    def buscar_papers(self, termino, *, max_resultados=15, dias=730):
        return self.papers


def respuesta_texto(texto: str) -> RespuestaFalsa:
    return RespuestaFalsa([BloqueTexto(texto)])


def veredicto_json(veredicto: str, motivo: str = "motivo") -> RespuestaFalsa:
    return respuesta_texto(json.dumps({"veredicto": veredicto, "motivo": motivo}))


def aprobado_json() -> RespuestaFalsa:
    return respuesta_texto(json.dumps({"aprobado": True, "problemas": []}))


def resumidor_y_verificador():
    """Summarizer y verificador de resumen mockeados, con sus clientes."""
    cliente_resumen = ClientFalso(respuesta_texto(RESUMEN))
    cliente_verif = ClientFalso(aprobado_json())
    return (
        Summarizer(client=cliente_resumen),
        VerificadorResumen(client=cliente_verif),
        cliente_resumen,
        cliente_verif,
    )


def busqueda(db, *, forzar=False, verificar_alcance=False, verificador_alcance=None):
    summarizer, verificador, cliente_resumen, cliente_verif = resumidor_y_verificador()
    resultado = buscar_y_resumir(
        "SCN1A",
        db=db,
        forzar=forzar,
        verificar_alcance=verificar_alcance,
        verificador_alcance=verificador_alcance,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer,
        verificador_resumen=verificador,
    )
    return resultado, cliente_resumen, cliente_verif


# ------------------------------------------------- CacheResumenes (unidad)


def test_guardar_y_recuperar(db):
    cache = CacheResumenes(db)
    cache.guardar("SCN1A", PMIDS, RESUMEN, "claude-opus-5")

    cacheado = cache.buscar("  scn1a  ", PMIDS)  # término normalizado

    assert cacheado is not None
    assert cacheado.resumen == RESUMEN
    assert cacheado.modelo == "claude-opus-5"
    assert cacheado.creado_en  # fecha para mostrar al usuario


def test_el_orden_de_los_pmids_no_importa(db):
    cache = CacheResumenes(db)
    cache.guardar("SCN1A", PMIDS, RESUMEN, "m")

    assert cache.buscar("SCN1A", list(reversed(PMIDS))) is not None


def test_un_conjunto_de_pmids_distinto_es_miss(db):
    cache = CacheResumenes(db)
    cache.guardar("SCN1A", PMIDS, RESUMEN, "m")

    assert cache.buscar("SCN1A", PMIDS + ["11111111"]) is None
    assert cache.buscar("otro término", PMIDS) is None


def test_una_entrada_caducada_es_miss(db):
    despues_del_ttl = datetime.now(timezone.utc) + timedelta(
        days=TTL_DIAS_POR_DEFECTO, hours=1
    )
    cache = CacheResumenes(db, ahora=lambda: despues_del_ttl)
    cache.guardar("SCN1A", PMIDS, RESUMEN, "m")

    assert cache.buscar("SCN1A", PMIDS) is None


def test_guardar_de_nuevo_renueva_la_entrada(db):
    cache = CacheResumenes(db)
    cache.guardar("SCN1A", PMIDS, RESUMEN, "m")
    cache.guardar("SCN1A", PMIDS, "resumen nuevo [PMID: 38123456]", "m")

    filas = db.execute("SELECT COUNT(*) AS n FROM resumenes_cache").fetchone()
    assert filas["n"] == 1  # upsert, no duplicado
    assert cache.buscar("SCN1A", PMIDS).resumen == "resumen nuevo [PMID: 38123456]"


def test_ttl_configurable_por_entorno(monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_CACHE_DIAS", "7")
    assert ttl_dias_configurado() == 7

    monkeypatch.setenv("PAPER_SEARCH_CACHE_DIAS", "no-es-un-numero")
    assert ttl_dias_configurado() == TTL_DIAS_POR_DEFECTO


# ------------------------------------------------- CacheVeredictos (unidad)


def test_veredicto_se_guarda_y_recupera(db):
    cache = CacheVeredictos(db)
    cache.guardar("SCN1A", VeredictoAlcance(veredicto=DENTRO_DE_ALCANCE, motivo="gen"))

    veredicto = cache.buscar("scn1a")
    assert veredicto is not None
    assert veredicto.veredicto == DENTRO_DE_ALCANCE
    assert veredicto.motivo == "gen"


def test_no_concluyente_no_se_cachea(db):
    cache = CacheVeredictos(db)
    cache.guardar("SCN1A", VeredictoAlcance(veredicto=NO_CONCLUYENTE, motivo="timeout"))

    assert cache.buscar("SCN1A") is None


def test_veredicto_caducado_es_miss(db):
    despues_del_ttl = datetime.now(timezone.utc) + timedelta(
        days=TTL_DIAS_POR_DEFECTO, hours=1
    )
    cache = CacheVeredictos(db, ahora=lambda: despues_del_ttl)
    cache.guardar("SCN1A", VeredictoAlcance(veredicto=DENTRO_DE_ALCANCE, motivo="gen"))

    assert cache.buscar("SCN1A") is None


# ----------------------------------- orquestación: caché de resúmenes


def test_cache_hit_no_llama_a_la_api(db):
    busqueda(db)  # primera búsqueda: genera y cachea

    resultado, cliente_resumen, cliente_verif = busqueda(db)  # segunda: hit

    assert resultado.desde_cache is True
    assert resultado.cache_creado_en is not None
    assert resultado.resumen == RESUMEN
    assert cliente_resumen.messages.llamadas == []  # ni resumen...
    assert cliente_verif.messages.llamadas == []  # ...ni verificación


def test_cache_miss_genera_y_guarda(db):
    resultado, cliente_resumen, cliente_verif = busqueda(db)

    assert resultado.desde_cache is False
    assert resultado.cache_creado_en is None
    assert len(cliente_resumen.messages.llamadas) == 1
    assert len(cliente_verif.messages.llamadas) == 1
    assert CacheResumenes(db).buscar("SCN1A", PMIDS) is not None


def test_cache_caducada_regenera(db):
    busqueda(db)
    hace_mucho = (
        datetime.now(timezone.utc) - timedelta(days=TTL_DIAS_POR_DEFECTO, hours=1)
    ).isoformat(timespec="seconds")
    db.execute("UPDATE resumenes_cache SET creado_en = ?", (hace_mucho,))
    db.commit()

    resultado, cliente_resumen, _ = busqueda(db)

    assert resultado.desde_cache is False
    assert len(cliente_resumen.messages.llamadas) == 1  # se regeneró
    # La entrada quedó renovada: la siguiente búsqueda vuelve a ser un hit.
    assert CacheResumenes(db).buscar("SCN1A", PMIDS) is not None


def test_forzar_regenera_aunque_la_cache_este_vigente(db):
    busqueda(db)

    resultado, cliente_resumen, _ = busqueda(db, forzar=True)

    assert resultado.desde_cache is False
    assert len(cliente_resumen.messages.llamadas) == 1  # regeneró de verdad


def test_el_json_expone_desde_cache_y_fecha(db):
    busqueda(db)
    resultado, _, _ = busqueda(db)

    datos = resultado.to_dict()
    assert datos["desde_cache"] is True
    assert datos["cache_creado_en"] == resultado.cache_creado_en


def test_un_resumen_sin_verificar_no_se_cachea(db):
    summarizer = Summarizer(client=ClientFalso(respuesta_texto("Sin citas.")))

    buscar_y_resumir(
        "SCN1A",
        db=db,
        verificar_alcance=False,
        verificar_resumen=False,
        client=ClientPubMedFalso(PAPERS),
        summarizer=summarizer,
    )

    assert CacheResumenes(db).buscar("SCN1A", PMIDS) is None


# ----------------------------------- orquestación: caché de veredictos


def test_el_veredicto_de_alcance_se_cachea(db):
    cliente_alcance = ClientFalso(veredicto_json(DENTRO_DE_ALCANCE))
    verificador = VerificadorAlcance(client=cliente_alcance)

    busqueda(db, verificar_alcance=True, verificador_alcance=verificador)
    busqueda(db, verificar_alcance=True, verificador_alcance=verificador)

    # La segunda búsqueda usó el veredicto cacheado: una sola llamada.
    assert len(cliente_alcance.messages.llamadas) == 1


def test_un_bloqueo_cacheado_bloquea_sin_llamar(db):
    cliente_alcance = ClientFalso(veredicto_json(FUERA_DE_ALCANCE, "enfermedad común"))
    verificador = VerificadorAlcance(client=cliente_alcance)

    with pytest.raises(TerminoFueraDeAlcanceError):
        busqueda(db, verificar_alcance=True, verificador_alcance=verificador)
    with pytest.raises(TerminoFueraDeAlcanceError):
        busqueda(db, verificar_alcance=True, verificador_alcance=verificador)

    assert len(cliente_alcance.messages.llamadas) == 1


def test_un_veredicto_ambiguo_cacheado_conserva_su_aviso(db):
    cliente_alcance = ClientFalso(veredicto_json(AMBIGUO, "sigla ambigua"))
    verificador = VerificadorAlcance(client=cliente_alcance)

    busqueda(db, verificar_alcance=True, verificador_alcance=verificador)
    resultado, _, _ = busqueda(db, verificar_alcance=True, verificador_alcance=verificador)

    assert len(cliente_alcance.messages.llamadas) == 1
    assert "sigla ambigua" in resultado.aviso_alcance


def test_un_no_concluyente_se_reintenta_en_la_siguiente_busqueda(db):
    cliente_alcance = ClientFalso(
        RuntimeError("timeout"), veredicto_json(DENTRO_DE_ALCANCE)
    )
    verificador = VerificadorAlcance(client=cliente_alcance)

    resultado_1, _, _ = busqueda(db, verificar_alcance=True, verificador_alcance=verificador)
    resultado_2, _, _ = busqueda(db, verificar_alcance=True, verificador_alcance=verificador)

    assert "No se ha podido comprobar" in resultado_1.aviso_alcance
    assert resultado_2.aviso_alcance is None  # el segundo intento sí verificó
    assert len(cliente_alcance.messages.llamadas) == 2


def test_forzar_ignora_tambien_el_veredicto_cacheado(db):
    cliente_alcance = ClientFalso(veredicto_json(DENTRO_DE_ALCANCE))
    verificador = VerificadorAlcance(client=cliente_alcance)

    busqueda(db, verificar_alcance=True, verificador_alcance=verificador)
    busqueda(db, verificar_alcance=True, verificador_alcance=verificador, forzar=True)

    assert len(cliente_alcance.messages.llamadas) == 2


def test_sin_db_no_hay_cache_ni_persistencia():
    resultado_1, cliente_1, _ = busqueda(None)
    resultado_2, cliente_2, _ = busqueda(None)

    assert resultado_1.desde_cache is False
    assert resultado_2.desde_cache is False
    assert len(cliente_1.messages.llamadas) == 1
    assert len(cliente_2.messages.llamadas) == 1  # cada búsqueda genera de nuevo
