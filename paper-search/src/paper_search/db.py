"""Base de datos local SQLite: caché, límites de uso y registro de acciones.

Un único archivo SQLite (sin servidor aparte), por defecto en
`paper-search/datos/paper-search.db` y configurable con la variable de entorno
`PAPER_SEARCH_DB`. La carpeta `datos/` está en `.gitignore`: son datos locales
del usuario, no parte del repo.

Migraciones: `MIGRACIONES` es una lista ordenada de scripts SQL; la posición
i-ésima lleva el esquema a la versión i+1. Al abrir la conexión se aplican las
pendientes según la tabla `esquema_version`. Cada script debe poder
re-ejecutarse SIN DAÑO por si una aplicación anterior quedó a medias — que no
es lo mismo que sin error: los que solo crean lo consiguen con `IF NOT EXISTS`,
y los que recrean una tabla (v3) fallan ruidosamente al reaplicarse, que es
preferible a corromper datos en silencio. Para evolucionar el esquema basta con
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

MIGRACION_V3 = """
-- La clave de la caché de resúmenes pasa a incluir el idioma: sin él, un
-- resumen en español se serviría a quien pidió inglés, y encima pareciendo
-- recién hecho.
--
-- El `UNIQUE (termino_normalizado, pmids_hash)` de la v1 va declarado dentro
-- del CREATE TABLE, y SQLite no deja quitarlo sin recrear la tabla. Se recrea
-- CONSERVANDO EL NOMBRE, y eso no es cosmético: `acciones.cache_id` tiene una
-- clave ajena a `resumenes_cache`, así que una tabla con otro nombre habría
-- dejado esa FK apuntando a la vieja y CUALQUIER búsqueda que tocara la caché
-- fallaría al escribir el registro.
--
-- `legacy_alter_table = ON` es lo que hace que el renombrado NO reescriba esa
-- FK en `acciones`: la referencia se queda apuntando al nombre, que es el que
-- va a llevar la tabla nueva. Sin este pragma, SQLite 3.25+ la reescribiría a
-- `resumenes_cache_legacy` y pasaría justo lo que se quiere evitar.
--
-- Se conservan los `id` para que los `cache_id` ya registrados en `acciones`
-- sigan resolviendo, y la tabla vieja se queda como `resumenes_cache_legacy`:
-- no se destruye nada. Si esta migración se interrumpiera a medias, una
-- segunda pasada falla en el ALTER —porque el destino ya existe— en vez de
-- copiar las filas inglesas como españolas: falla ruidosa antes que corromper.
--
-- Lo ya cacheado se marca 'es', y no es una suposición: se generó con el
-- prompt en español, que era el único que había.

PRAGMA legacy_alter_table = ON;

ALTER TABLE resumenes_cache RENAME TO resumenes_cache_legacy;

CREATE TABLE resumenes_cache (
    id INTEGER PRIMARY KEY,
    termino_normalizado TEXT NOT NULL,
    pmids_hash TEXT NOT NULL,
    pmids TEXT NOT NULL,
    idioma TEXT NOT NULL,
    resumen TEXT NOT NULL,
    modelo TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    UNIQUE (termino_normalizado, pmids_hash, idioma)
);

INSERT INTO resumenes_cache
    (id, termino_normalizado, pmids_hash, pmids, idioma, resumen, modelo, creado_en)
SELECT id, termino_normalizado, pmids_hash, pmids, 'es', resumen, modelo, creado_en
FROM resumenes_cache_legacy;

PRAGMA legacy_alter_table = OFF;
"""

#: Scripts de migración en orden. MIGRACIONES[i] lleva a la versión i+1.
MIGRACIONES: list[str] = [MIGRACION_V1, MIGRACION_V2, MIGRACION_V3]


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
    """Aplica los scripts pendientes en orden. Devuelve la versión final.

    Las claves ajenas se desactivan mientras se migra y se vuelven a activar al
    terminar. Es el procedimiento que documenta SQLite para cambios de esquema,
    y aquí hace falta de verdad: con `foreign_keys = ON`, renombrar una tabla
    reescribe las cláusulas `REFERENCES` que apuntan a ella, así que la v3
    dejaba la FK de `acciones.cache_id` apuntando a la tabla vieja y cualquier
    búsqueda que tocara la caché fallaba al escribir el registro.

    Al reactivarlas se pasa `foreign_key_check`: si una migración hubiera roto
    la integridad, es mejor enterarse aquí que al primer INSERT.
    """
    actual = version_esquema(conn)
    if actual >= len(MIGRACIONES):
        return actual

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for indice in range(actual, len(MIGRACIONES)):
            version = indice + 1
            conn.executescript(MIGRACIONES[indice])
            conn.execute(
                "INSERT INTO esquema_version (version, aplicada_en) VALUES (?, ?)",
                (version, ahora_utc_iso()),
            )
            conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    rotas = conn.execute("PRAGMA foreign_key_check").fetchall()
    if rotas:
        raise sqlite3.IntegrityError(
            f"la migración dejó {len(rotas)} referencia(s) rota(s); "
            f"la primera en la tabla «{rotas[0][0]}»"
        )
    return version_esquema(conn)


def ahora_utc_iso() -> str:
    """Timestamp UTC en ISO-8601, el formato de todas las fechas de la BD."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
