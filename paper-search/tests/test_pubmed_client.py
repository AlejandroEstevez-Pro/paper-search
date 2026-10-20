"""Tests del cliente de PubMed.

Todas las respuestas están mockeadas/grabadas: la suite nunca golpea la API
real, así es rápida y no depende de que PubMed esté disponible.
"""

from __future__ import annotations

import json

import pytest
import requests

from paper_search.pubmed_client import (
    LIMITE_CON_API_KEY,
    LIMITE_SIN_API_KEY,
    PubMedClient,
    PubMedError,
    RateLimiter,
    RespuestaInvalidaError,
    parsear_articulos,
)

# --------------------------------------------------------------- respuestas
# Respuestas grabadas con la forma real de la API de NCBI E-utilities.

XML_DOS_ARTICULOS = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE" Owner="NLM">
      <PMID Version="1">38123456</PMID>
      <Article PubModel="Print-Electronic">
        <Journal>
          <ISOAbbreviation>Epilepsia</ISOAbbreviation>
          <Title>Epilepsia</Title>
          <JournalIssue CitedMedium="Internet">
            <Volume>65</Volume>
            <PubDate><Year>2024</Year><Month>Mar</Month><Day>15</Day></PubDate>
          </JournalIssue>
        </Journal>
        <ArticleTitle>Variantes de <i>SCN1A</i> en el sindrome de Dravet</ArticleTitle>
        <Abstract>
          <AbstractText Label="OBJECTIVE">Describir el espectro de variantes.</AbstractText>
          <AbstractText Label="RESULTS">Se identificaron 42 variantes nuevas.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Garcia</LastName><ForeName>Ana</ForeName><Initials>A</Initials>
          </Author>
          <Author ValidYN="Y">
            <LastName>Smith</LastName><ForeName>John R</ForeName><Initials>JR</Initials>
          </Author>
          <Author ValidYN="Y">
            <CollectiveName>Dravet Syndrome Working Group</CollectiveName>
          </Author>
          <Author ValidYN="Y">
            <LastName>Rossi</LastName><ForeName>Marco</ForeName><Initials>M</Initials>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation Status="PubMed-not-MEDLINE" Owner="NLM">
      <PMID Version="1">38999999</PMID>
      <Article PubModel="Electronic">
        <Journal>
          <Title>Orphanet Journal of Rare Diseases</Title>
          <JournalIssue CitedMedium="Internet">
            <PubDate><MedlineDate>2023 Winter</MedlineDate></PubDate>
          </JournalIssue>
        </Journal>
        <ArticleTitle>Historia natural de una encefalopatia epileptica</ArticleTitle>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Lopez</LastName><ForeName>Beatriz</ForeName><Initials>B</Initials>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

XML_SIN_PMID = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE">
      <Article><ArticleTitle>Registro sin PMID</ArticleTitle></Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

XML_VACIO = '<?xml version="1.0"?>\n<PubmedArticleSet></PubmedArticleSet>\n'


def esearch_json(pmids: list[str], total: int | None = None) -> str:
    return json.dumps(
        {
            "header": {"type": "esearch", "version": "0.3"},
            "esearchresult": {
                "count": str(total if total is not None else len(pmids)),
                "retmax": str(len(pmids)),
                "retstart": "0",
                "idlist": pmids,
                "translationset": [],
            },
        }
    )


# ------------------------------------------------------------------- dobles


class RespuestaFalsa:
    """Imita lo que el cliente usa de una respuesta de `requests`."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)  # lanza ValueError si no es JSON


class SessionFalsa:
    """Devuelve respuestas preprogramadas y registra las llamadas.

    Si se agotan las respuestas, se repite la última: así los tests de "la API
    falla siempre" no tienen que enumerar cada reintento.
    """

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.llamadas.append({"url": url, "params": params or {}, "timeout": timeout})
        respuesta = (
            self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        )
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    @property
    def endpoints(self) -> list[str]:
        return [llamada["url"].rsplit("/", 1)[-1] for llamada in self.llamadas]


def hacer_client(respuestas, **kwargs) -> tuple[PubMedClient, SessionFalsa, list[float]]:
    """Cliente con sesión falsa y sin dormir de verdad.

    La lista devuelta recoge solo las pausas de backoff: el rate limiter se
    sustituye por uno instantáneo para que sus esperas (que se prueban aparte)
    no se mezclen con las de los reintentos.
    """
    session = SessionFalsa(respuestas)
    siestas: list[float] = []
    client = PubMedClient(
        session=session,
        dormir=siestas.append,
        rate_limiter=RateLimiter(1000.0, dormir=lambda _: None),
        pausa_base=0.5,
        email="test@example.org",
        **kwargs,
    )
    return client, session, siestas


# ------------------------------------------------------------------ esearch


def test_buscar_devuelve_los_pmids_y_manda_los_parametros_obligatorios():
    client, session, _ = hacer_client([RespuestaFalsa(text=esearch_json(["1", "2"]))])

    pmids = client.buscar("SCN1A", max_resultados=2, dias=365)

    assert pmids == ["1", "2"]
    params = session.llamadas[0]["params"]
    assert params["db"] == "pubmed"
    assert params["term"] == "SCN1A"
    assert params["retmax"] == "2"
    assert params["reldate"] == "365"
    assert params["datetype"] == "pdat"
    # Se pide por relevancia, no por fecha: el orden por fecha se recalcula en
    # local sobre lo ya traído y el de relevancia no (ver orden.py).
    assert params["sort"] == "relevance"
    # NCBI pide siempre tool + email (docs/api-notes.md).
    assert params["tool"]
    assert params["email"] == "test@example.org"
    assert "api_key" not in params


def test_manda_api_key_cuando_esta_configurada():
    client, session, _ = hacer_client(
        [RespuestaFalsa(text=esearch_json([]))], api_key="clave-secreta"
    )

    client.buscar("SCN1A")

    assert session.llamadas[0]["params"]["api_key"] == "clave-secreta"


def test_la_api_no_devuelve_resultados_lista_vacia_no_error():
    """Caso obligatorio: búsqueda válida sin artículos no es un fallo."""
    client, _, _ = hacer_client([RespuestaFalsa(text=esearch_json([]))])

    assert client.buscar("termino-inexistente-xyz") == []


def test_sin_resultados_no_se_llama_a_efetch():
    client, session, _ = hacer_client([RespuestaFalsa(text=esearch_json([]))])

    papers = client.buscar_papers("termino-inexistente-xyz")

    assert papers == []
    assert session.endpoints == ["esearch.fcgi"]


def test_error_declarado_por_pubmed_se_convierte_en_PubMedError():
    cuerpo = json.dumps({"esearchresult": {"ERROR": "Invalid db name: pubmedd"}})
    client, _, _ = hacer_client([RespuestaFalsa(text=cuerpo)])

    with pytest.raises(PubMedError, match="Invalid db name"):
        client.buscar("SCN1A")


def test_respuesta_de_busqueda_no_json_se_convierte_en_RespuestaInvalidaError():
    client, _, _ = hacer_client([RespuestaFalsa(text="<html>502 Bad Gateway</html>")])

    with pytest.raises(RespuestaInvalidaError):
        client.buscar("SCN1A")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"termino": "   "},
        {"termino": "SCN1A", "max_resultados": 0},
        {"termino": "SCN1A", "dias": 0},
    ],
)
def test_parametros_invalidos(kwargs):
    client, _, _ = hacer_client([RespuestaFalsa(text=esearch_json([]))])
    termino = kwargs.pop("termino")

    with pytest.raises(ValueError):
        client.buscar(termino, **kwargs)


# ------------------------------------------------------- efetch y parseo XML


def test_obtener_detalles_parsea_todos_los_campos():
    client, session, _ = hacer_client([RespuestaFalsa(text=XML_DOS_ARTICULOS)])

    papers = client.obtener_detalles(["38123456", "38999999"])

    assert len(papers) == 2
    primero = papers[0]
    assert primero.pmid == "38123456"
    # El título trae marcado interno (<i>SCN1A</i>) y debe quedar plano.
    assert primero.titulo == "Variantes de SCN1A en el sindrome de Dravet"
    assert primero.revista == "Epilepsia"
    assert primero.fecha == "2024-03-15"
    assert primero.anio == "2024"
    assert primero.autores == (
        "Garcia A",
        "Smith JR",
        "Dravet Syndrome Working Group",
        "Rossi M",
    )
    assert primero.autores_texto.endswith("et al.")
    assert primero.url == "https://pubmed.ncbi.nlm.nih.gov/38123456/"
    # Un solo efetch con todos los IDs separados por coma.
    assert session.llamadas[0]["params"]["id"] == "38123456,38999999"
    assert session.llamadas[0]["params"]["retmode"] == "xml"


def test_abstract_estructurado_conserva_las_etiquetas():
    papers = parsear_articulos(XML_DOS_ARTICULOS)

    assert "OBJECTIVE: Describir el espectro de variantes." in papers[0].abstract
    assert "RESULTS: Se identificaron 42 variantes nuevas." in papers[0].abstract


def test_articulo_sin_abstract_ni_ISOAbbreviation():
    papers = parsear_articulos(XML_DOS_ARTICULOS)

    segundo = papers[1]
    assert segundo.abstract == ""
    assert segundo.revista == "Orphanet Journal of Rare Diseases"
    assert segundo.fecha == "2023 Winter"
    assert segundo.anio == "2023"
    assert segundo.autores_texto == "Lopez B"


def test_articulo_sin_pmid_se_descarta_por_no_ser_trazable():
    assert parsear_articulos(XML_SIN_PMID) == []


def test_xml_malformado_se_convierte_en_RespuestaInvalidaError():
    client, _, _ = hacer_client([RespuestaFalsa(text="<PubmedArticleSet><oops>")])

    with pytest.raises(RespuestaInvalidaError):
        client.obtener_detalles(["38123456"])


def test_obtener_detalles_sin_pmids_no_llama_a_la_api():
    client, session, _ = hacer_client([RespuestaFalsa(text=XML_VACIO)])

    assert client.obtener_detalles([]) == []
    assert session.llamadas == []


def test_resultados_en_el_orden_devuelto_por_esearch():
    """efetch puede reordenar; mandan los PMIDs de esearch (más recientes primero)."""
    client, _, _ = hacer_client([RespuestaFalsa(text=XML_DOS_ARTICULOS)])

    papers = client.obtener_detalles(["38999999", "38123456"])

    assert [p.pmid for p in papers] == ["38999999", "38123456"]


def test_los_pmids_se_piden_en_lotes():
    pmids = [str(n) for n in range(250)]
    client, session, _ = hacer_client([RespuestaFalsa(text=XML_VACIO)])

    client.obtener_detalles(pmids)

    assert session.endpoints == ["efetch.fcgi", "efetch.fcgi"]
    assert len(session.llamadas[0]["params"]["id"].split(",")) == 200
    assert len(session.llamadas[1]["params"]["id"].split(",")) == 50


def test_buscar_papers_encadena_esearch_y_efetch():
    client, session, _ = hacer_client(
        [
            RespuestaFalsa(text=esearch_json(["38123456", "38999999"])),
            RespuestaFalsa(text=XML_DOS_ARTICULOS),
        ]
    )

    papers = client.buscar_papers("SCN1A", max_resultados=2, dias=365)

    assert [p.pmid for p in papers] == ["38123456", "38999999"]
    assert session.endpoints == ["esearch.fcgi", "efetch.fcgi"]


# ------------------------------------------------ errores de la API y reintentos


def test_la_api_falla_siempre_error_claro_tras_agotar_reintentos():
    """Caso obligatorio: la API falla."""
    client, session, siestas = hacer_client(
        [RespuestaFalsa(status_code=500, text="Internal Server Error")],
        max_reintentos=2,
    )

    with pytest.raises(PubMedError) as excinfo:
        client.buscar("SCN1A")

    assert "500" in str(excinfo.value)
    assert "3 intentos" in str(excinfo.value)
    assert len(session.llamadas) == 3  # intento inicial + 2 reintentos
    assert siestas == [0.5, 1.0]  # backoff exponencial


def test_error_transitorio_se_reintenta_y_acaba_funcionando():
    client, session, siestas = hacer_client(
        [
            RespuestaFalsa(status_code=503, text="Service Unavailable"),
            RespuestaFalsa(text=esearch_json(["38123456"])),
        ]
    )

    assert client.buscar("SCN1A") == ["38123456"]
    assert len(session.llamadas) == 2
    assert siestas == [0.5]


def test_429_respeta_la_cabecera_retry_after():
    client, _, siestas = hacer_client(
        [
            RespuestaFalsa(status_code=429, text="", headers={"Retry-After": "4"}),
            RespuestaFalsa(text=esearch_json([])),
        ]
    )

    client.buscar("SCN1A")

    assert siestas == [4.0]


def test_un_400_no_se_reintenta():
    client, session, _ = hacer_client(
        [RespuestaFalsa(status_code=400, text="Bad Request")], max_reintentos=3
    )

    with pytest.raises(PubMedError, match="HTTP 400"):
        client.buscar("SCN1A")

    assert len(session.llamadas) == 1


def test_error_de_red_se_convierte_en_PubMedError():
    client, session, _ = hacer_client(
        [requests.ConnectionError("conexión rechazada")], max_reintentos=1
    )

    with pytest.raises(PubMedError) as excinfo:
        client.buscar("SCN1A")

    assert "error de red" in str(excinfo.value)
    assert len(session.llamadas) == 2


# ------------------------------------------------------------- rate limiting


class RelojFalso:
    def __init__(self) -> None:
        self.ahora = 0.0

    def __call__(self) -> float:
        return self.ahora

    def dormir(self, segundos: float) -> None:
        self.ahora += segundos


def test_rate_limiter_espacia_las_peticiones():
    reloj = RelojFalso()
    siestas: list[float] = []

    def dormir(segundos):
        siestas.append(segundos)
        reloj.dormir(segundos)

    limiter = RateLimiter(3.0, dormir=dormir, reloj=reloj)

    limiter.esperar()  # la primera no espera
    limiter.esperar()
    limiter.esperar()

    assert siestas == [pytest.approx(1 / 3), pytest.approx(1 / 3)]


def test_rate_limiter_no_espera_si_ya_paso_el_intervalo():
    reloj = RelojFalso()
    siestas: list[float] = []
    limiter = RateLimiter(3.0, dormir=siestas.append, reloj=reloj)

    limiter.esperar()
    reloj.ahora += 5.0
    limiter.esperar()

    assert siestas == []


def test_el_limite_por_defecto_depende_de_si_hay_api_key():
    sin_clave = PubMedClient(session=SessionFalsa([]), api_key=None, email="t@example.org")
    con_clave = PubMedClient(session=SessionFalsa([]), api_key="abc", email="t@example.org")

    assert sin_clave.rate_limiter.intervalo_minimo == pytest.approx(1 / LIMITE_SIN_API_KEY)
    assert con_clave.rate_limiter.intervalo_minimo == pytest.approx(1 / LIMITE_CON_API_KEY)


def test_el_cliente_pasa_por_el_rate_limiter_en_cada_peticion():
    class LimiterEspia(RateLimiter):
        def __init__(self):
            super().__init__(1000.0, dormir=lambda _: None)
            self.veces = 0

        def esperar(self):
            self.veces += 1

    limiter = LimiterEspia()
    session = SessionFalsa(
        [
            RespuestaFalsa(text=esearch_json(["38123456"])),
            RespuestaFalsa(text=XML_DOS_ARTICULOS),
        ]
    )
    client = PubMedClient(
        session=session, rate_limiter=limiter, email="t@example.org", dormir=lambda _: None
    )

    client.buscar_papers("SCN1A")

    assert limiter.veces == 2


def test_rate_limiter_rechaza_frecuencias_invalidas():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_la_api_key_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "del-entorno")
    monkeypatch.setenv("NCBI_EMAIL", "yo@example.org")

    client = PubMedClient(session=SessionFalsa([]))

    assert client.api_key == "del-entorno"
    assert client.email == "yo@example.org"
