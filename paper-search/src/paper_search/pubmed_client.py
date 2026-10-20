"""Cliente de la API de PubMed (NCBI E-utilities).

Flujo de dos pasos descrito en `docs/api-notes.md` del repo raíz:

1. `esearch.fcgi` — término de búsqueda -> lista de PMIDs.
2. `efetch.fcgi` — lote de PMIDs -> registros completos en XML.

El rate limiting está implementado desde el principio (3 req/s sin API key,
10 req/s con ella), junto con reintentos con backoff exponencial para los
errores transitorios de la API.

Este módulo nunca inventa datos: si la API falla se lanza `PubMedError`, y si
no hay resultados se devuelve una lista vacía. Ambas situaciones se distinguen
siempre desde fuera.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from typing import Any

import requests

from .models import PaperSearchError, Paper

log = logging.getLogger(__name__)

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
NOMBRE_HERRAMIENTA = "rare-disease-paper-search"

#: NCBI pide a quien usa E-utilities un email de contacto real, para poder
#: avisarle si sus peticiones dan problemas antes de bloquearlas. Es
#: obligatorio y NO tiene valor por defecto: un email fijo en el código haría
#: que todo el que clonase el repo hablara con NCBI en nombre del autor.
MENSAJE_FALTA_EMAIL = (
    "Falta NCBI_EMAIL, el email de contacto que se envía a PubMed con cada "
    "búsqueda.\n"
    "NCBI, que mantiene PubMed, pide a todo programa que use su API el email "
    "real de quien lo ejecuta, para poder avisarle si sus peticiones causan "
    "problemas antes de bloquearlas. Pon el tuyo, no el de otra persona, de "
    "una de estas dos formas:\n"
    "  1. En el archivo .env de la carpeta paper-search/ (copia .env.example a "
    ".env y rellena NCBI_EMAIL).\n"
    "  2. Como variable de entorno, que tiene prioridad sobre el .env:\n"
    '       PowerShell:  $env:NCBI_EMAIL = "<tu email>"\n'
    '       bash/zsh:    export NCBI_EMAIL="<tu email>"'
)

#: Límites publicados por NCBI (ver docs/api-notes.md).
LIMITE_SIN_API_KEY = 3.0
LIMITE_CON_API_KEY = 10.0

#: Un solo efetch con muchos IDs es preferible a una petición por artículo,
#: pero NCBI recomienda no pasarse de unos cientos por petición GET.
TAMANO_LOTE = 200

#: Códigos que merecen reintento: rate limiting y errores transitorios.
ESTADOS_REINTENTABLES = frozenset({429, 500, 502, 503, 504})


class PubMedError(PaperSearchError):
    """Fallo al hablar con la API de PubMed (red, HTTP o respuesta ilegible)."""


class RespuestaInvalidaError(PubMedError):
    """La API respondió, pero el cuerpo no se pudo interpretar."""


class FaltaEmailNCBIError(PaperSearchError):
    """Falta `NCBI_EMAIL`, o no parece un email: sin él no se consulta PubMed.

    No hereda de `PubMedError` porque no es un fallo de PubMed sino de la
    configuración local, y se detecta antes de hacer ninguna petición.
    """


class RateLimiter:
    """Limitador sencillo por espaciado mínimo entre peticiones.

    Con 3 req/s de límite es fácil pasarse sin querer dentro de un bucle, así
    que el espaciado se aplica en el propio cliente y no como responsabilidad
    de quien lo llama. Es seguro entre hilos.
    """

    def __init__(
        self,
        peticiones_por_segundo: float,
        *,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if peticiones_por_segundo <= 0:
            raise ValueError("peticiones_por_segundo debe ser mayor que 0")
        self.intervalo_minimo = 1.0 / peticiones_por_segundo
        self._dormir = dormir
        self._reloj = reloj
        self._lock = threading.Lock()
        self._ultima_peticion: float | None = None

    def esperar(self) -> None:
        """Bloquea lo justo para no superar el límite de peticiones."""
        with self._lock:
            ahora = self._reloj()
            if self._ultima_peticion is not None:
                transcurrido = ahora - self._ultima_peticion
                restante = self.intervalo_minimo - transcurrido
                if restante > 0:
                    self._dormir(restante)
                    ahora = self._reloj()
            self._ultima_peticion = ahora


class PubMedClient:
    """Acceso a PubMed con rate limiting, reintentos y parseo de XML."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        email: str | None = None,
        herramienta: str = NOMBRE_HERRAMIENTA,
        session: Any | None = None,
        rate_limiter: RateLimiter | None = None,
        max_reintentos: int = 3,
        pausa_base: float = 1.0,
        timeout: float = 30.0,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("NCBI_API_KEY")
        self.email = (email or os.environ.get("NCBI_EMAIL") or "").strip()
        if "@" not in self.email:
            raise FaltaEmailNCBIError(MENSAJE_FALTA_EMAIL)
        self.herramienta = herramienta
        self.session = session if session is not None else requests.Session()
        self.max_reintentos = max_reintentos
        self.pausa_base = pausa_base
        self.timeout = timeout
        self._dormir = dormir
        if rate_limiter is None:
            limite = LIMITE_CON_API_KEY if self.api_key else LIMITE_SIN_API_KEY
            rate_limiter = RateLimiter(limite, dormir=dormir)
        self.rate_limiter = rate_limiter

    # ---------------------------------------------------------------- público

    def buscar(self, termino: str, *, max_resultados: int = 15, dias: int = 730) -> list[str]:
        """Devuelve los PMIDs más relevantes que coinciden con `termino`.

        El orden de la lista ES el orden de relevancia de PubMed: la API no
        devuelve ninguna puntuación, solo la posición. Se pide `sort=relevance`
        y no `sort=pub_date` porque la ordenación por fecha se puede recalcular
        en local sobre lo ya traído, y la de relevancia no (ver `orden.py` y
        docs/decisions.md). La ventana temporal (`dias`) se sigue aplicando.

        Una lista vacía significa "la API respondió pero no hay artículos", no
        un fallo: los fallos se lanzan como `PubMedError`.
        """
        termino = termino.strip()
        if not termino:
            raise ValueError("El término de búsqueda no puede estar vacío")
        if max_resultados <= 0:
            raise ValueError("max_resultados debe ser mayor que 0")
        if dias <= 0:
            raise ValueError("dias debe ser mayor que 0")

        params = {
            "db": "pubmed",
            "term": termino,
            "retmax": str(max_resultados),
            "retmode": "json",
            "sort": "relevance",
            "datetype": "pdat",
            "reldate": str(dias),
        }
        respuesta = self._get("esearch.fcgi", params)
        try:
            cuerpo = respuesta.json()
        except ValueError as exc:  # incluye json.JSONDecodeError
            raise RespuestaInvalidaError(
                "PubMed devolvió una respuesta de búsqueda que no es JSON válido."
            ) from exc

        resultado = cuerpo.get("esearchresult")
        if not isinstance(resultado, dict):
            raise RespuestaInvalidaError(
                "La respuesta de PubMed no contiene el bloque 'esearchresult' esperado."
            )
        if resultado.get("ERROR"):
            raise PubMedError(f"PubMed rechazó la búsqueda: {resultado['ERROR']}")

        idlist = resultado.get("idlist") or []
        return [str(pmid) for pmid in idlist if str(pmid).strip()]

    def obtener_detalles(self, pmids: Sequence[str]) -> list[Paper]:
        """Descarga título, autores, revista, fecha y abstract de cada PMID."""
        pmids = [str(p).strip() for p in pmids if str(p).strip()]
        if not pmids:
            return []

        papers: list[Paper] = []
        for lote in _en_lotes(pmids, TAMANO_LOTE):
            params = {
                "db": "pubmed",
                "id": ",".join(lote),
                "rettype": "abstract",
                "retmode": "xml",
            }
            respuesta = self._get("efetch.fcgi", params)
            papers.extend(parsear_articulos(respuesta.text))

        # Respetar el orden en que PubMed devolvió los PMIDs (relevancia),
        # aunque efetch los reordene, y anotarlo en cada paper: es la única
        # señal de relevancia que da la API, y sin guardarla aquí se pierde.
        posicion = {pmid: i for i, pmid in enumerate(pmids)}
        papers.sort(key=lambda p: posicion.get(p.pmid, len(posicion)))
        return [
            replace(paper, orden_relevancia=posicion.get(paper.pmid))
            for paper in papers
        ]

    def buscar_papers(
        self, termino: str, *, max_resultados: int = 15, dias: int = 730
    ) -> list[Paper]:
        """Atajo: `buscar` + `obtener_detalles` en una sola llamada."""
        pmids = self.buscar(termino, max_resultados=max_resultados, dias=dias)
        if not pmids:
            return []
        return self.obtener_detalles(pmids)

    # ---------------------------------------------------------------- interno

    def _get(self, endpoint: str, params: dict[str, str]) -> Any:
        """GET con rate limiting, parámetros obligatorios y reintentos."""
        params = dict(params)
        params["tool"] = self.herramienta
        params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        url = BASE_URL + endpoint
        ultimo_motivo = ""

        for intento in range(self.max_reintentos + 1):
            self.rate_limiter.esperar()
            try:
                respuesta = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                ultimo_motivo = f"error de red ({exc.__class__.__name__}: {exc})"
                if intento == self.max_reintentos:
                    break
                self._esperar_backoff(intento, None)
                continue

            estado = getattr(respuesta, "status_code", 200)
            if estado == 200:
                return respuesta

            ultimo_motivo = f"HTTP {estado}"
            if estado not in ESTADOS_REINTENTABLES or intento == self.max_reintentos:
                break

            log.warning(
                "PubMed devolvió %s en %s; reintentando (%s/%s)",
                estado,
                endpoint,
                intento + 1,
                self.max_reintentos,
            )
            self._esperar_backoff(intento, _retry_after(respuesta))

        raise PubMedError(
            f"No se pudo contactar con PubMed ({endpoint}) tras "
            f"{self.max_reintentos + 1} intentos: {ultimo_motivo}."
        )

    def _esperar_backoff(self, intento: int, retry_after: float | None) -> None:
        pausa = self.pausa_base * (2**intento)
        if retry_after is not None:
            pausa = max(pausa, retry_after)
        self._dormir(pausa)


# -------------------------------------------------------------------- parseo


def parsear_articulos(xml_texto: str) -> list[Paper]:
    """Convierte la respuesta XML de `efetch` en objetos `Paper`."""
    try:
        raiz = ET.fromstring(xml_texto)
    except ET.ParseError as exc:
        raise RespuestaInvalidaError(
            "PubMed devolvió un XML que no se pudo parsear."
        ) from exc

    papers: list[Paper] = []
    for articulo in raiz.iter("PubmedArticle"):
        paper = _parsear_articulo(articulo)
        if paper is not None:
            papers.append(paper)
    return papers


def _parsear_articulo(articulo: ET.Element) -> Paper | None:
    pmid = _texto(articulo.find("./MedlineCitation/PMID"))
    if not pmid:
        # Sin PMID no hay trazabilidad posible: se descarta el registro en vez
        # de presentarlo sin fuente verificable.
        return None

    art = articulo.find("./MedlineCitation/Article")
    if art is None:
        return None

    return Paper(
        pmid=pmid,
        titulo=_texto_completo(art.find("ArticleTitle")) or "(sin título)",
        autores=tuple(_parsear_autores(art.find("AuthorList"))),
        revista=_parsear_revista(art),
        fecha=_parsear_fecha(art),
        abstract=_parsear_abstract(art.find("Abstract")),
    )


def _parsear_autores(lista: ET.Element | None) -> list[str]:
    if lista is None:
        return []
    autores: list[str] = []
    for autor in lista.findall("Author"):
        colectivo = _texto(autor.find("CollectiveName"))
        if colectivo:
            autores.append(colectivo)
            continue
        apellido = _texto(autor.find("LastName"))
        iniciales = _texto(autor.find("Initials")) or _texto(autor.find("ForeName"))
        nombre = " ".join(parte for parte in (apellido, iniciales) if parte)
        if nombre:
            autores.append(nombre)
    return autores


def _parsear_revista(art: ET.Element) -> str:
    revista = art.find("Journal")
    if revista is None:
        return ""
    return (
        _texto(revista.find("ISOAbbreviation"))
        or _texto(revista.find("Title"))
        or ""
    )


def _parsear_fecha(art: ET.Element) -> str:
    pub_date = art.find("./Journal/JournalIssue/PubDate")
    if pub_date is not None:
        medline = _texto(pub_date.find("MedlineDate"))
        anio = _texto(pub_date.find("Year"))
        if anio:
            partes = [anio]
            mes = _normalizar_mes(_texto(pub_date.find("Month")))
            if mes:
                partes.append(mes)
                dia = _texto(pub_date.find("Day"))
                if dia:
                    partes.append(dia.zfill(2))
            return "-".join(partes)
        if medline:
            return medline

    article_date = art.find("ArticleDate")
    if article_date is not None:
        anio = _texto(article_date.find("Year"))
        if anio:
            mes = _texto(article_date.find("Month"))
            dia = _texto(article_date.find("Day"))
            partes = [anio]
            if mes:
                partes.append(mes.zfill(2))
            if dia:
                partes.append(dia.zfill(2))
            return "-".join(partes)
    return ""


MESES = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _normalizar_mes(mes: str) -> str:
    if not mes:
        return ""
    if mes.isdigit():
        return mes.zfill(2)
    return MESES.get(mes[:3].lower(), "")


def _parsear_abstract(abstract: ET.Element | None) -> str:
    if abstract is None:
        return ""
    trozos: list[str] = []
    for parte in abstract.findall("AbstractText"):
        texto = _texto_completo(parte)
        if not texto:
            continue
        etiqueta = parte.get("Label")
        trozos.append(f"{etiqueta}: {texto}" if etiqueta else texto)
    return "\n\n".join(trozos)


def _texto(elemento: ET.Element | None) -> str:
    if elemento is None or elemento.text is None:
        return ""
    return elemento.text.strip()


def _texto_completo(elemento: ET.Element | None) -> str:
    """Texto de un elemento incluyendo el de sus hijos (cursivas, sub/sup...)."""
    if elemento is None:
        return ""
    return " ".join("".join(elemento.itertext()).split())


def _retry_after(respuesta: Any) -> float | None:
    cabeceras = getattr(respuesta, "headers", None) or {}
    valor = cabeceras.get("Retry-After") or cabeceras.get("retry-after")
    if not valor:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _en_lotes(elementos: Sequence[str], tamano: int) -> Iterable[Sequence[str]]:
    for inicio in range(0, len(elementos), tamano):
        yield elementos[inicio : inicio + tamano]
