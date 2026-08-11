"""Ordenación de los resultados de una búsqueda.

Dos criterios: por fecha de publicación (el de por defecto, del más reciente al
más antiguo) y por relevancia según PubMed.

Ordenar es una transformación **local y pura** sobre un conjunto de papers que
ya se tiene: no consulta PubMed, no gasta llamadas y no cambia qué artículos
hay, solo en qué orden se ven. Eso tiene dos consecuencias buenas:

- Cambiar el orden no puede invalidar la caché de resúmenes, cuya clave es
  (término, hash de los PMIDs **ordenados alfabéticamente**) — ver `cache.py`.
- El resumen se genera siempre a partir del orden canónico de PubMed
  (relevancia), independientemente de cómo se muestre, así que dos búsquedas
  iguales con distinto orden de visualización producen el mismo resumen.

Para que "relevancia" signifique algo, la búsqueda pide a PubMed `sort=relevance`
y guarda la posición devuelta en `Paper.orden_relevancia`: PubMed no da una
puntuación numérica, solo el orden. El razonamiento completo, incluido lo que
esto cambia respecto a las Fases 1 y 2, está en docs/decisions.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from .models import Paper

ORDEN_FECHA = "fecha"
ORDEN_RELEVANCIA = "relevancia"

#: Criterios admitidos, en el orden en que se ofrecen en CLI y web.
ORDENES = (ORDEN_FECHA, ORDEN_RELEVANCIA)

ORDEN_POR_DEFECTO = ORDEN_FECHA

#: Etiquetas para la interfaz.
ETIQUETAS = {
    ORDEN_FECHA: "Más recientes primero",
    ORDEN_RELEVANCIA: "Más relevantes primero (según PubMed)",
}

_ANIO = re.compile(r"(\d{4})")
_MES_DIA = re.compile(r"^\d{4}-(\d{1,2})(?:-(\d{1,2}))?")

_MESES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class OrdenDesconocidoError(ValueError):
    """El criterio de orden pedido no existe."""


def clave_fecha(fecha: str) -> tuple[int, int, int]:
    """Convierte la fecha de un `Paper` en algo comparable: (año, mes, día).

    PubMed devuelve fechas de granularidad variable —`2024-03-15`, `2024-03`,
    `2024`, o un texto libre tipo `2023 Nov-Dec`—, así que lo que falta se
    rellena con 0. Un paper sin fecha reconocible da `(0, 0, 0)` y, ordenando
    de más reciente a más antiguo, queda al final: nunca se cuela arriba por
    no tener dato.
    """
    texto = (fecha or "").strip()
    if not texto:
        return (0, 0, 0)

    coincidencia = _ANIO.search(texto)
    if coincidencia is None:
        return (0, 0, 0)
    anio = int(coincidencia.group(1))

    iso = _MES_DIA.match(texto)
    if iso is not None:
        mes = int(iso.group(1))
        dia = int(iso.group(2)) if iso.group(2) else 0
        return (anio, mes, dia)

    # Fechas Medline en texto ("2023 Nov-Dec"): se aprovecha el primer mes que
    # aparezca; el día no existe en ese formato.
    resto = texto[coincidencia.end() :].strip().lower()
    for nombre, numero in _MESES.items():
        if resto.startswith(nombre):
            return (anio, numero, 0)
    return (anio, 0, 0)


def _clave_relevancia(paper: Paper) -> int:
    """Posición devuelta por PubMed. Sin dato, al final (no se inventa)."""
    if paper.orden_relevancia is None:
        return 1_000_000
    return paper.orden_relevancia


def ordenar_papers(
    papers: Iterable[Paper], criterio: str = ORDEN_POR_DEFECTO
) -> tuple[Paper, ...]:
    """Devuelve los papers ordenados según `criterio`, sin tocar la entrada.

    Con `ORDEN_FECHA`, el desempate es el orden de relevancia de PubMed: es
    estable, reproducible y no arbitrario. Muchos artículos comparten fecha
    (sobre todo los que solo traen el año), así que sin un desempate explícito
    el orden dependería del azar de la entrada.
    """
    if criterio not in ORDENES:
        raise OrdenDesconocidoError(
            f"Orden desconocido: {criterio!r}. Debe ser uno de {ORDENES}."
        )

    lista: Sequence[Paper] = list(papers)
    if criterio == ORDEN_RELEVANCIA:
        return tuple(sorted(lista, key=_clave_relevancia))

    # Fecha descendente, desempate por relevancia ascendente. Se hace con una
    # sola clave (fecha negada) en vez de dos pasadas para que el desempate no
    # dependa de la estabilidad del sort previo.
    def clave(paper: Paper) -> tuple[int, int, int, int]:
        anio, mes, dia = clave_fecha(paper.fecha)
        return (-anio, -mes, -dia, _clave_relevancia(paper))

    return tuple(sorted(lista, key=clave))


def normalizar_orden(criterio: str | None) -> str:
    """Criterio válido a partir de una entrada del usuario, o el de por defecto."""
    if not criterio:
        return ORDEN_POR_DEFECTO
    limpio = str(criterio).strip().lower()
    return limpio if limpio in ORDENES else ORDEN_POR_DEFECTO
