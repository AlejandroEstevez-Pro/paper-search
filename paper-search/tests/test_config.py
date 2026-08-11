"""Tests de la carga del `.env`.

Nunca se toca el `.env` real de la máquina: cada test escribe el suyo en un
directorio temporal y se lo pasa a `cargar_env`.
"""

from __future__ import annotations

import os

from paper_search import RUTA_ENV, cargar_env
from paper_search.config import RAIZ_COMPONENTE


def escribir_env(tmp_path, contenido: str):
    ruta = tmp_path / ".env"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def test_lee_la_clave_del_env_cuando_no_esta_en_el_entorno(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ruta = escribir_env(tmp_path, "ANTHROPIC_API_KEY=sk-ant-del-archivo\n")

    assert cargar_env(ruta) is True
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-del-archivo"


def test_la_variable_de_entorno_tiene_prioridad_sobre_el_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-del-entorno")
    ruta = escribir_env(tmp_path, "ANTHROPIC_API_KEY=sk-ant-del-archivo\n")

    cargar_env(ruta)

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-del-entorno"


def test_sin_archivo_env_no_es_un_error(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert cargar_env(tmp_path / "no-existe.env") is False
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_tambien_carga_las_variables_de_ncbi(tmp_path, monkeypatch):
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    monkeypatch.delenv("NCBI_EMAIL", raising=False)
    ruta = escribir_env(
        tmp_path, "NCBI_API_KEY=abc123\nNCBI_EMAIL=alguien@ejemplo.org\n"
    )

    cargar_env(ruta)

    assert os.environ["NCBI_API_KEY"] == "abc123"
    assert os.environ["NCBI_EMAIL"] == "alguien@ejemplo.org"


def test_una_clave_vacia_en_el_env_no_tapa_la_del_entorno(tmp_path, monkeypatch):
    # .env.example se distribuye con la clave vacía: copiarlo tal cual a .env
    # no debe romper a quien sí tiene la variable exportada.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-del-entorno")
    ruta = escribir_env(tmp_path, "ANTHROPIC_API_KEY=\n")

    cargar_env(ruta)

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-del-entorno"


def test_lee_un_env_guardado_con_BOM(tmp_path, monkeypatch):
    # El Bloc de notas y `Set-Content` de PowerShell escriben UTF-8 con BOM.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ruta = tmp_path / ".env"
    ruta.write_text("ANTHROPIC_API_KEY=sk-ant-con-bom\n", encoding="utf-8-sig")

    cargar_env(ruta)

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-con-bom"


def test_la_ruta_por_defecto_es_el_env_de_la_raiz_del_componente():
    assert RUTA_ENV == RAIZ_COMPONENTE / ".env"
    assert (RAIZ_COMPONENTE / "cli.py").is_file()  # la raíz es paper-search/
