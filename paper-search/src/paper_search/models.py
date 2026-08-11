"""Estructuras de datos del paquete.

El modo JSON de la CLI serializa exactamente estas dataclases, así que su forma
es el contrato estable que consumirán otras herramientas del repo (ver
`docs/roadmap.md`, fase 2).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

URL_PUBMED = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

#: Cita al final de cada afirmación del resumen: `[PMID: 12345678]` o
#: `[PMID: 12345678, 23456789]` (ver el prompt en `summarizer.py`).
PATRON_CITA = re.compile(r"\[PMID:\s*\d[\d,\s]*\]")

AVISO_NO_DIAGNOSTICO = (
    "Esta herramienta es una ayuda de búsqueda y síntesis bibliográfica. "
    "No es una herramienta de diagnóstico ni constituye asesoramiento médico. "
    "Verifica siempre cada afirmación en el paper original a partir de su PMID."
)


def url_de_pmid(pmid: str) -> str:
    """Enlace público a PubMed para un PMID."""
    return URL_PUBMED.format(pmid=pmid)


def plegar_texto(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar texto escrito por personas.

    La usan la detección de idioma (`idioma.py`) y los filtros por autor y
    patógeno (`busqueda.py`): quien escribe «Garcia» debe encontrar a «García».
    """
    descompuesto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


class PaperSearchError(Exception):
    """Base de los errores del paquete. La CLI la usa para dar un mensaje limpio."""


@dataclass(frozen=True)
class Segmento:
    """Un trozo de resumen: texto normal o una cita `[PMID: ...]`."""

    texto: str
    es_cita: bool = False


def segmentar_resumen(resumen: str) -> tuple[tuple[Segmento, ...], ...]:
    """Parte el resumen en párrafos y separa las citas del texto que las rodea.

    La interfaz web las resalta para que se vea de un vistazo qué afirmación se
    apoya en qué paper. No se toca el texto: solo se marca dónde está cada cita,
    así que el resumen se muestra íntegro aunque el modelo no cite como se
    esperaba.
    """
    parrafos: list[tuple[Segmento, ...]] = []
    for bruto in (resumen or "").split("\n\n"):
        parrafo = bruto.strip()
        if not parrafo:
            continue

        segmentos: list[Segmento] = []
        posicion = 0
        for cita in PATRON_CITA.finditer(parrafo):
            if cita.start() > posicion:
                segmentos.append(Segmento(parrafo[posicion : cita.start()]))
            segmentos.append(Segmento(cita.group(), es_cita=True))
            posicion = cita.end()
        if posicion < len(parrafo):
            segmentos.append(Segmento(parrafo[posicion:]))

        parrafos.append(tuple(segmentos))

    return tuple(parrafos)


@dataclass(frozen=True)
class Paper:
    """Un artículo de PubMed con los campos necesarios para la trazabilidad."""

    pmid: str
    titulo: str
    autores: tuple[str, ...] = ()
    revista: str = ""
    fecha: str = ""
    abstract: str = ""
    #: Posición (0 = primero) en que PubMed devolvió este artículo para la
    #: búsqueda, que es su orden de relevancia. PubMed no da una puntuación,
    #: solo el orden, así que este entero es toda la señal de relevancia que
    #: existe. `None` en papers que no vienen de una búsqueda (p. ej. los
    #: releídos de la BD local para la vista de favoritos).
    orden_relevancia: int | None = None

    @property
    def url(self) -> str:
        return url_de_pmid(self.pmid)

    @property
    def anio(self) -> str:
        """Año de publicación, o cadena vacía si la fecha no lo trae."""
        for i in range(len(self.fecha) - 3):
            trozo = self.fecha[i : i + 4]
            if trozo.isdigit():
                return trozo
        return ""

    @property
    def autores_texto(self) -> str:
        """Autores en formato corto: los tres primeros y 'et al.'."""
        if not self.autores:
            return "Autores no disponibles"
        if len(self.autores) <= 3:
            return ", ".join(self.autores)
        return ", ".join(self.autores[:3]) + " et al."

    def to_dict(self) -> dict[str, Any]:
        return {
            "pmid": self.pmid,
            "titulo": self.titulo,
            "autores": list(self.autores),
            "revista": self.revista,
            "fecha": self.fecha,
            "abstract": self.abstract,
            "url": self.url,
            "orden_relevancia": self.orden_relevancia,
        }


@dataclass(frozen=True)
class ResultadoBusqueda:
    """Resultado completo de una búsqueda: papers reales + resumen trazable."""

    query: str
    papers: tuple[Paper, ...] = ()
    resumen: str | None = None
    #: Motivo por el que no hay resumen (falta de clave, fallo de la API...).
    #: Nunca se rellena `resumen` con texto aproximado: o hay resumen real o
    #: hay error explicado.
    error_resumen: str | None = None
    #: Aviso del guardarraíl de alcance cuando el término es ambiguo o la
    #: verificación no se pudo hacer. `None` si el término pasó limpio. Un
    #: término fuera de alcance no llega aquí: bloquea la búsqueda con
    #: `TerminoFueraDeAlcanceError` antes de tocar PubMed.
    aviso_alcance: str | None = None
    #: Aviso cuando el término parece escrito en español, catalán, euskera o
    #: gallego (ver `idioma.py`). PubMed indexa sobre todo en inglés. Es
    #: informativo: nunca bloquea la búsqueda ni traduce el término, igual que
    #: `aviso_alcance` cuando el veredicto es ambiguo.
    aviso_idioma: str | None = None
    #: True si el resumen viene de la caché local en vez de generarse ahora.
    desde_cache: bool = False
    #: Cuándo se generó originalmente el resumen cacheado (UTC ISO). Solo
    #: rellenado cuando `desde_cache` es True.
    cache_creado_en: str | None = None
    dias: int | None = None
    #: Criterio con el que está ordenado `papers` (ver `orden.py`). El orden es
    #: solo de presentación: no cambia qué artículos hay, ni la clave de la
    #: caché de resúmenes, ni el resumen, que siempre se genera a partir del
    #: orden canónico de PubMed.
    orden: str = "fecha"
    #: Criterios con los que se lanzó la búsqueda (término, autor, patógeno).
    #: `query` es la consulta ya montada que se mandó a PubMed; esto es lo que
    #: escribió la persona, campo a campo. Se tipa como `Any` para no crear una
    #: dependencia circular con `busqueda.py`.
    criterios: Any | None = None
    aviso: str = field(default=AVISO_NO_DIAGNOSTICO)

    @property
    def total(self) -> int:
        return len(self.papers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "resumen": self.resumen,
            "papers": [p.to_dict() for p in self.papers],
            "total": self.total,
            "dias": self.dias,
            "orden": self.orden,
            "criterios": self.criterios.to_dict() if self.criterios else None,
            "error_resumen": self.error_resumen,
            "aviso_alcance": self.aviso_alcance,
            "aviso_idioma": self.aviso_idioma,
            "desde_cache": self.desde_cache,
            "cache_creado_en": self.cache_creado_en,
            "aviso": self.aviso,
        }
