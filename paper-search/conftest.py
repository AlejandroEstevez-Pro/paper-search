"""Configuración común de la suite.

Hace importable `paper_search` desde `src/` sin instalar nada, y aísla los
tests de las variables de entorno de quien los ejecuta (si no, un
`ANTHROPIC_API_KEY` o `NCBI_API_KEY` puesto en la máquina cambiaría el
comportamiento esperado).
"""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent
SRC = RAIZ / "src"
for ruta in (SRC, RAIZ):  # RAIZ hace importables `app.py` y `cli.py`
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))

VARIABLES_AISLADAS = (
    "ANTHROPIC_API_KEY",
    "NCBI_API_KEY",
    "NCBI_EMAIL",
    "PAPER_SEARCH_DB",
    "PAPER_SEARCH_CACHE_DIAS",
    "PAPER_SEARCH_MAX_BUSQUEDAS_DIA",
    "PAPER_SEARCH_MAX_LLAMADAS_DIA",
)


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for variable in VARIABLES_AISLADAS:
        monkeypatch.delenv(variable, raising=False)
