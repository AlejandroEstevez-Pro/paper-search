"""Registro de acciones: cada búsqueda queda anotada en SQLite.

Sirve para dos cosas: auditoría/depuración hoy (qué se buscó, qué pasó, cuántas
llamadas a Claude consumió cada búsqueda) y como base del historial y los
favoritos de la Fase 3 — por eso se guardan también los PMIDs devueltos (JSON,
en orden) y los metadatos de cada paper en la tabla `papers`, aunque la UI
todavía no los muestre.

El registro nunca decide nada: solo anota. Los bloqueos (alcance, límites) y
los errores se registran igual que los éxitos, para que la auditoría cuente
todo lo que el usuario intentó.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence

from .db import ahora_utc_iso
from .models import Paper

RESULTADO_EXITO = "exito"
RESULTADO_SIN_RESULTADOS = "sin_resultados"
RESULTADO_BLOQUEADA_ALCANCE = "bloqueada_alcance"
RESULTADO_BLOQUEADA_LIMITE = "bloqueada_limite"
RESULTADO_ERROR_PUBMED = "error_pubmed"
RESULTADO_ERROR_RESUMEN = "error_resumen"

RESULTADOS_VALIDOS = (
    RESULTADO_EXITO,
    RESULTADO_SIN_RESULTADOS,
    RESULTADO_BLOQUEADA_ALCANCE,
    RESULTADO_BLOQUEADA_LIMITE,
    RESULTADO_ERROR_PUBMED,
    RESULTADO_ERROR_RESUMEN,
)


class RegistroAcciones:
    """Escribe en las tablas `acciones` y `papers`."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        ahora: Callable[[], str] = ahora_utc_iso,
    ) -> None:
        self.conn = conn
        self._ahora = ahora

    def registrar(
        self,
        *,
        termino: str,
        resultado: str,
        max_resultados: int | None = None,
        dias: int | None = None,
        detalle: str | None = None,
        desde_cache: bool = False,
        llamadas_claude: int = 0,
        pmids: Sequence[str] | None = None,
        cache_id: int | None = None,
    ) -> int:
        """Anota una búsqueda (o un intento bloqueado) y devuelve su id."""
        if resultado not in RESULTADOS_VALIDOS:
            raise ValueError(
                f"Resultado desconocido: {resultado!r}. "
                f"Debe ser uno de {RESULTADOS_VALIDOS}."
            )
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO acciones "
                "(timestamp, termino, max_resultados, dias, resultado, detalle, "
                " desde_cache, llamadas_claude, pmids, cache_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._ahora(),
                    termino,
                    max_resultados,
                    dias,
                    resultado,
                    detalle,
                    1 if desde_cache else 0,
                    llamadas_claude,
                    json.dumps(list(pmids)) if pmids else None,
                    cache_id,
                ),
            )
        return cursor.lastrowid

    def guardar_papers(self, papers: Sequence[Paper]) -> None:
        """Upsert de los metadatos de cada paper (para el historial de Fase 3)."""
        ahora = self._ahora()
        with self.conn:
            self.conn.executemany(
                "INSERT INTO papers "
                "(pmid, titulo, autores, revista, fecha, abstract, actualizado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (pmid) DO UPDATE SET "
                "titulo = excluded.titulo, autores = excluded.autores, "
                "revista = excluded.revista, fecha = excluded.fecha, "
                "abstract = excluded.abstract, "
                "actualizado_en = excluded.actualizado_en",
                [
                    (
                        paper.pmid,
                        paper.titulo,
                        json.dumps(list(paper.autores)),
                        paper.revista,
                        paper.fecha,
                        paper.abstract,
                        ahora,
                    )
                    for paper in papers
                ],
            )
