"""Carga de la configuración local desde un archivo `.env`.

Las claves se siguen leyendo siempre del entorno del proceso (nunca están
escritas en el código). Este módulo solo añade una forma cómoda de ponerlas sin
exportarlas a mano en cada sesión: un `.env` en la raíz de `paper-search/`.

La prioridad es siempre del entorno del sistema (`override=False`): si
`ANTHROPIC_API_KEY` ya está exportada, el `.env` no la pisa. Así una clave
temporal puesta en la terminal siempre gana sobre la del archivo.

`.env` está en `.gitignore` y nunca debe subirse al repositorio; la plantilla
versionada es `.env.example`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

#: Raíz del componente (`paper-search/`), dos niveles por encima de
#: `src/paper_search/config.py`.
RAIZ_COMPONENTE = Path(__file__).resolve().parents[2]
RUTA_ENV = RAIZ_COMPONENTE / ".env"

#: Variables que tiene sentido poner en el `.env` (ver README).
VARIABLES_SOPORTADAS = (
    "ANTHROPIC_API_KEY",
    "NCBI_API_KEY",
    "NCBI_EMAIL",
    "PAPER_SEARCH_DB",
    "PAPER_SEARCH_CACHE_DIAS",
    "PAPER_SEARCH_MAX_BUSQUEDAS_DIA",
    "PAPER_SEARCH_MAX_LLAMADAS_DIA",
)


def cargar_env(ruta: str | os.PathLike[str] | None = None) -> bool:
    """Carga el `.env` en el entorno sin pisar lo que ya esté definido.

    Devuelve `True` si se leyó un archivo y `False` si no había ninguno (no
    tener `.env` es lo normal cuando las claves se exportan a mano, así que no
    es un error). La llaman los puntos de entrada (`cli.py`, `app.py`); el
    paquete usado como librería no toca el entorno por su cuenta.
    """
    ruta = Path(ruta) if ruta is not None else RUTA_ENV
    if not ruta.is_file():
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - depende del entorno
        # Sin silencios: hay un .env que el usuario espera que se lea y no se
        # puede. La herramienta sigue funcionando con las variables del sistema.
        log.warning(
            "Hay un archivo %s pero falta el paquete 'python-dotenv', así que no "
            "se ha leído. Instálalo con `pip install -r requirements.txt` o "
            "exporta las variables a mano.",
            ruta,
        )
        return False

    # utf-8-sig y no utf-8: el Bloc de notas y `Set-Content` de PowerShell
    # escriben un BOM al principio del archivo, y sin descartarlo la primera
    # clave se leería como "﻿ANTHROPIC_API_KEY" y no se vería nunca.
    return load_dotenv(ruta, override=False, encoding="utf-8-sig")
