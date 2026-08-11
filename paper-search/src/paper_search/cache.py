"""Caché local de resúmenes verificados y de veredictos de alcance.

La clave de la caché de resúmenes es `(término normalizado, conjunto de
PMIDs)`: la búsqueda a PubMed se hace siempre (es barata y no consume llamadas
a Claude), y la caché ahorra lo caro — resumen y verificaciones. Si desde la
última vez se ha publicado un paper nuevo, el conjunto de PMIDs cambia y la
caché falla sola: nunca se sirve un resumen que ignore papers nuevos.

Solo se cachean resúmenes que ya superaron la verificación de `verificacion.py`
y veredictos de alcance concluyentes (los `no_concluyente` se reintentan en la
siguiente búsqueda).

La caducidad no se guarda en la base de datos: se calcula al leer
(`creado_en` + TTL), así que cambiar `PAPER_SEARCH_CACHE_DIAS` afecta también a
lo ya cacheado.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .alcance import NO_CONCLUYENTE, VeredictoAlcance
from .db import ahora_utc_iso

log = logging.getLogger(__name__)

TTL_DIAS_POR_DEFECTO = 30


def ttl_dias_configurado() -> int:
    """TTL en días: `PAPER_SEARCH_CACHE_DIAS` del entorno, o el default (30)."""
    crudo = os.environ.get("PAPER_SEARCH_CACHE_DIAS", "").strip()
    if not crudo:
        return TTL_DIAS_POR_DEFECTO
    try:
        valor = int(crudo)
    except ValueError:
        valor = 0
    if valor <= 0:
        log.warning(
            "PAPER_SEARCH_CACHE_DIAS=%r no es un entero positivo; se usa el "
            "valor por defecto (%d días).",
            crudo,
            TTL_DIAS_POR_DEFECTO,
        )
        return TTL_DIAS_POR_DEFECTO
    return valor


def normalizar_termino(termino: str) -> str:
    return termino.strip().lower()


def hash_pmids(pmids: Sequence[str]) -> str:
    """Hash estable del conjunto de PMIDs (el orden no importa)."""
    return hashlib.sha256(",".join(sorted(pmids)).encode("utf-8")).hexdigest()


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _caducado(creado_en: str, ttl_dias: int, ahora: datetime) -> bool:
    creado = datetime.fromisoformat(creado_en)
    return ahora - creado > timedelta(days=ttl_dias)


@dataclass(frozen=True)
class ResumenCacheado:
    """Un resumen servido desde la caché, con su fecha de generación."""

    id: int
    resumen: str
    modelo: str
    creado_en: str  # UTC ISO — se muestra al usuario al servir desde caché


class CacheResumenes:
    """Caché de resúmenes verificados, con caducidad por TTL."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        ttl_dias: int | None = None,
        ahora: Callable[[], datetime] = _ahora_utc,
    ) -> None:
        self.conn = conn
        self.ttl_dias = ttl_dias if ttl_dias is not None else ttl_dias_configurado()
        self._ahora = ahora

    def buscar(self, termino: str, pmids: Sequence[str]) -> ResumenCacheado | None:
        """Resumen cacheado y vigente para este término y estos PMIDs, o None."""
        fila = self.conn.execute(
            "SELECT id, resumen, modelo, creado_en FROM resumenes_cache "
            "WHERE termino_normalizado = ? AND pmids_hash = ?",
            (normalizar_termino(termino), hash_pmids(pmids)),
        ).fetchone()
        if fila is None:
            return None
        if _caducado(fila["creado_en"], self.ttl_dias, self._ahora()):
            return None
        return ResumenCacheado(
            id=fila["id"],
            resumen=fila["resumen"],
            modelo=fila["modelo"],
            creado_en=fila["creado_en"],
        )

    def guardar(
        self, termino: str, pmids: Sequence[str], resumen: str, modelo: str
    ) -> int:
        """Guarda (o renueva) el resumen y devuelve el id de la fila."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO resumenes_cache "
                "(termino_normalizado, pmids_hash, pmids, resumen, modelo, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (termino_normalizado, pmids_hash) DO UPDATE SET "
                "pmids = excluded.pmids, resumen = excluded.resumen, "
                "modelo = excluded.modelo, creado_en = excluded.creado_en",
                (
                    normalizar_termino(termino),
                    hash_pmids(pmids),
                    json.dumps(list(pmids)),
                    resumen,
                    modelo,
                    ahora_utc_iso(),
                ),
            )
        fila = self.conn.execute(
            "SELECT id FROM resumenes_cache "
            "WHERE termino_normalizado = ? AND pmids_hash = ?",
            (normalizar_termino(termino), hash_pmids(pmids)),
        ).fetchone()
        return fila["id"]


class CacheVeredictos:
    """Caché de veredictos de alcance por término (mismo TTL que los resúmenes)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        ttl_dias: int | None = None,
        ahora: Callable[[], datetime] = _ahora_utc,
    ) -> None:
        self.conn = conn
        self.ttl_dias = ttl_dias if ttl_dias is not None else ttl_dias_configurado()
        self._ahora = ahora

    def buscar(self, termino: str) -> VeredictoAlcance | None:
        fila = self.conn.execute(
            "SELECT veredicto, motivo, creado_en FROM veredictos_alcance "
            "WHERE termino_normalizado = ?",
            (normalizar_termino(termino),),
        ).fetchone()
        if fila is None:
            return None
        if _caducado(fila["creado_en"], self.ttl_dias, self._ahora()):
            return None
        return VeredictoAlcance(veredicto=fila["veredicto"], motivo=fila["motivo"])

    def guardar(self, termino: str, veredicto: VeredictoAlcance) -> None:
        """Guarda el veredicto. Los `no_concluyente` no se cachean."""
        if veredicto.veredicto == NO_CONCLUYENTE:
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO veredictos_alcance "
                "(termino_normalizado, veredicto, motivo, creado_en) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (termino_normalizado) DO UPDATE SET "
                "veredicto = excluded.veredicto, motivo = excluded.motivo, "
                "creado_en = excluded.creado_en",
                (
                    normalizar_termino(termino),
                    veredicto.veredicto,
                    veredicto.motivo,
                    ahora_utc_iso(),
                ),
            )
