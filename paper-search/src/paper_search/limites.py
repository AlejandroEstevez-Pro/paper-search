"""Límites de uso diarios propios del usuario (aparte del rate limit de NCBI).

Dos límites independientes con reseteo diario (medianoche local):

- número de búsquedas al día (`PAPER_SEARCH_MAX_BUSQUEDAS_DIA`, 50 por defecto);
- número de llamadas a la API de Claude al día
  (`PAPER_SEARCH_MAX_LLAMADAS_DIA`, 200 por defecto). Cada búsqueda con resumen
  puede consumir varias: alcance + resumen + verificación, y más si hay
  regeneraciones — se cuenta cada llamada real, no "una por búsqueda".

Política: los dos límites se comprueban AL INICIO de la búsqueda; una búsqueda
ya en marcha se termina aunque cruce el límite a mitad (abortar a medias
tiraría trabajo ya pagado). El contador vive en la tabla `uso_diario` (una fila
por día), así que las filas de días anteriores quedan como histórico de uso.

El rate limiting hacia PubMed es otra cosa y vive en `pubmed_client.py`.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta

from .models import PaperSearchError

log = logging.getLogger(__name__)

LIMITE_BUSQUEDAS_POR_DEFECTO = 50
LIMITE_LLAMADAS_POR_DEFECTO = 200


class LimiteAlcanzadoError(PaperSearchError):
    """Se alcanzó uno de los límites diarios de uso."""


def limite_configurado(variable: str, por_defecto: int) -> int:
    """Lee un límite del entorno, con el valor por defecto si no es válido."""
    crudo = os.environ.get(variable, "").strip()
    if not crudo:
        return por_defecto
    try:
        valor = int(crudo)
    except ValueError:
        valor = 0
    if valor <= 0:
        log.warning(
            "%s=%r no es un entero positivo; se usa el valor por defecto (%d).",
            variable,
            crudo,
            por_defecto,
        )
        return por_defecto
    return valor


class LimitesUso:
    """Contadores diarios de búsquedas y llamadas a Claude, en SQLite."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        max_busquedas: int | None = None,
        max_llamadas: int | None = None,
        hoy: Callable[[], date] = date.today,
    ) -> None:
        self.conn = conn
        self.max_busquedas = (
            max_busquedas
            if max_busquedas is not None
            else limite_configurado(
                "PAPER_SEARCH_MAX_BUSQUEDAS_DIA", LIMITE_BUSQUEDAS_POR_DEFECTO
            )
        )
        self.max_llamadas = (
            max_llamadas
            if max_llamadas is not None
            else limite_configurado(
                "PAPER_SEARCH_MAX_LLAMADAS_DIA", LIMITE_LLAMADAS_POR_DEFECTO
            )
        )
        self._hoy = hoy

    def uso_de_hoy(self) -> tuple[int, int]:
        """(búsquedas, llamadas a Claude) consumidas hoy."""
        fila = self.conn.execute(
            "SELECT busquedas, llamadas_claude FROM uso_diario WHERE dia = ?",
            (self._hoy().isoformat(),),
        ).fetchone()
        if fila is None:
            return (0, 0)
        return (fila["busquedas"], fila["llamadas_claude"])

    def comprobar(self) -> None:
        """Lanza `LimiteAlcanzadoError` si algún límite diario está agotado."""
        busquedas, llamadas = self.uso_de_hoy()
        manana = (self._hoy() + timedelta(days=1)).isoformat()
        if busquedas >= self.max_busquedas:
            raise LimiteAlcanzadoError(
                f"Se ha alcanzado el límite diario de búsquedas "
                f"({busquedas} de {self.max_busquedas}). El contador se "
                f"resetea a medianoche: podrás volver a buscar el {manana}. "
                f"El límite se cambia con PAPER_SEARCH_MAX_BUSQUEDAS_DIA."
            )
        if llamadas >= self.max_llamadas:
            raise LimiteAlcanzadoError(
                f"Se ha alcanzado el límite diario de llamadas a la API de "
                f"Claude ({llamadas} de {self.max_llamadas}). El contador se "
                f"resetea a medianoche: podrás volver a buscar el {manana}. "
                f"El límite se cambia con PAPER_SEARCH_MAX_LLAMADAS_DIA."
            )

    def registrar_busqueda(self) -> None:
        self._incrementar("busquedas")

    def registrar_llamada_claude(self) -> None:
        self._incrementar("llamadas_claude")

    def _incrementar(self, columna: str) -> None:
        assert columna in ("busquedas", "llamadas_claude")
        with self.conn:
            self.conn.execute(
                f"INSERT INTO uso_diario (dia, {columna}) VALUES (?, 1) "
                f"ON CONFLICT (dia) DO UPDATE SET {columna} = {columna} + 1",
                (self._hoy().isoformat(),),
            )
