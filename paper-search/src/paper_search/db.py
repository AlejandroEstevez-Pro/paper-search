"""Base de datos local SQLite: caché, límites de uso y registro de acciones.

Un único archivo SQLite (sin servidor aparte), por defecto en
`paper-search/datos/paper-search.db` y configurable con la variable de entorno
`PAPER_SEARCH_DB`. La carpeta `datos/` está en `.gitignore`: son datos locales
del usuario, no parte del repo.

Migraciones: `MIGRACIONES` es una lista ordenada de scripts SQL; la posición
i-ésima lleva el esquema a la versión i+1. Al abrir la conexión se aplican las
pendientes según la tabla `esquema_version`. Cada script debe poder
re-ejecutarse sin daño (`IF NOT EXISTS`) por si una aplicación anterior quedó a
medias. Para evolucionar el esquema (favoritos en Fase 3, etc.) basta con
añadir un script nuevo al final de la lista, nunca editar los anteriores.

Este módulo no sabe nada de PubMed ni de Claude: solo conexión y esquema. La
lógica de cada tabla vive en su módulo (`cache.py`, `limites.py`,
`registro.py`).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import RAIZ_COMPONENTE
from .models import PaperSearchError

#: Ruta por defecto del archivo de base de datos (ver `ruta_db_por_defecto`).
RUTA_DB_POR_DEFECTO = RAIZ_COMPONENTE / "datos" / "paper-search.db"

#: Valor especial de sqlite3 para una base de datos en memoria (tests).
EN_MEMORIA = ":memory:"


class BaseDatosError(PaperSearchError):
    """No se pudo abrir o migrar la base de datos local."""


MIGRACION_V1 = """
CREATE TABLE IF NOT EXISTS esquema_version (
    version INTEGER NOT NULL,
    aplicada_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resumenes_cache (
    id INTEGER PRIMARY KEY,
    termino_normalizado TEXT NOT NULL,
    pmids_hash TEXT NOT NULL,
    pmids TEXT NOT NULL,
    resumen TEXT NOT NULL,
    modelo TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    UNIQUE (termino_normalizado, pmids_hash)
);

CREATE TABLE IF NOT EXISTS veredictos_alcance (
    termino_normalizado TEXT PRIMARY KEY,
    veredicto TEXT NOT NULL,
    motivo TEXT NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uso_diario (
    dia TEXT PRIMARY KEY,
    busquedas INTEGER NOT NULL DEFAULT 0,
    llamadas_claude INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS papers (
    pmid TEXT PRIMARY KEY,
    titulo TEXT NOT NULL,
    autores TEXT NOT NULL,
    revista TEXT NOT NULL,
    fecha TEXT NOT NULL,
    abstract TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    termino TEXT NOT NULL,
    max_resultados INTEGER,
    dias INTEGER,
    resultado TEXT NOT NULL,
    detalle TEXT,
    desde_cache INTEGER NOT NULL DEFAULT 0,
    llamadas_claude INTEGER NOT NULL DEFAULT 0,
    pmids TEXT,
    cache_id INTEGER REFERENCES resumenes_cache(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_acciones_termino ON acciones (termino);
"""

MIGRACION_V2 = """
CREATE TABLE IF NOT EXISTS favoritos (
    pmid TEXT PRIMARY KEY REFERENCES papers(pmid) ON DELETE CASCADE,
    nota TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_favoritos_creado_en ON favoritos (creado_en);
"""

#: Scripts de migración en orden. MIGRACIONES[i] lleva a la versión i+1.
MIGRACIONES: list[str] = [MIGRACION_V1, MIGRACION_V2]


def ruta_db_por_defecto() -> Path:
    """Ruta del archivo de BD: `PAPER_SEARCH_DB` del entorno, o el default."""
    configurada = os.environ.get("PAPER_SEARCH_DB", "").strip()
    return Path(configurada) if configurada else RUTA_DB_POR_DEFECTO


def abrir_db(ruta: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Abre (creando si hace falta) la BD local y aplica migraciones pendientes.

    Lanza `BaseDatosError` con un mensaje claro si el archivo no se puede
    abrir o una migración falla: nunca se sigue con un esquema a medias.
    """
    if ruta is None:
        ruta = ruta_db_por_defecto()

    try:
        if str(ruta) != EN_MEMORIA:
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(ruta))
    except (OSError, sqlite3.Error) as exc:
        # `sqlite3.connect` con una ruta imposible lanza sqlite3.OperationalError,
        # que NO es OSError: sin capturarla salía un traceback en vez del aviso.
        raise BaseDatosError(
            f"No se pudo abrir la base de datos local en «{ruta}» "
            f"({exc.__class__.__name__}: {exc}). Comprueba la ruta o la "
            f"variable PAPER_SEARCH_DB."
        ) from exc

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        aplicar_migraciones(conn)
    except sqlite3.Error as exc:
        conn.close()
        raise BaseDatosError(
            f"No se pudo migrar la base de datos «{ruta}» a la versión "
            f"{len(MIGRACIONES)} ({exc.__class__.__name__}: {exc})."
        ) from exc
    return conn


def version_esquema(conn: sqlite3.Connection) -> int:
    """Versión actual del esquema (0 si la BD está recién creada)."""
    existe = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'esquema_version'"
    ).fetchone()
    if existe is None:
        return 0
    fila = conn.execute("SELECT MAX(version) AS v FROM esquema_version").fetchone()
    return fila["v"] or 0


def aplicar_migraciones(conn: sqlite3.Connection) -> int:
    """Aplica los scripts pendientes en orden. Devuelve la versión final."""
    actual = version_esquema(conn)
    for indice in range(actual, len(MIGRACIONES)):
        version = indice + 1
        conn.executescript(MIGRACIONES[indice])
        conn.execute(
            "INSERT INTO esquema_version (version, aplicada_en) VALUES (?, ?)",
            (version, ahora_utc_iso()),
        )
        conn.commit()
    return version_esquema(conn)


def ahora_utc_iso() -> str:
    """Timestamp UTC en ISO-8601, el formato de todas las fechas de la BD."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
