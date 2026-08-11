"""Tests de la base de datos local (conexión, esquema, migraciones)."""

from __future__ import annotations

import sqlite3

import pytest

from paper_search.db import (
    MIGRACIONES,
    RUTA_DB_POR_DEFECTO,
    BaseDatosError,
    abrir_db,
    ruta_db_por_defecto,
    version_esquema,
)

TABLAS_V1 = {
    "esquema_version",
    "resumenes_cache",
    "veredictos_alcance",
    "uso_diario",
    "papers",
    "acciones",
}


def test_abrir_crea_el_archivo_y_el_esquema(tmp_path):
    ruta = tmp_path / "sub" / "paper-search.db"  # la carpeta no existe aún

    conn = abrir_db(ruta)
    try:
        assert ruta.is_file()
        tablas = {
            fila["name"]
            for fila in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert TABLAS_V1 <= tablas
    finally:
        conn.close()


def test_el_esquema_queda_en_la_ultima_version(tmp_path):
    conn = abrir_db(tmp_path / "db.sqlite")
    try:
        assert version_esquema(conn) == len(MIGRACIONES)
    finally:
        conn.close()


def test_reabrir_no_reaplica_migraciones(tmp_path):
    ruta = tmp_path / "db.sqlite"
    abrir_db(ruta).close()

    conn = abrir_db(ruta)  # segunda apertura
    try:
        filas = conn.execute("SELECT COUNT(*) AS n FROM esquema_version").fetchone()
        assert filas["n"] == len(MIGRACIONES)  # una fila por migración, sin duplicar
    finally:
        conn.close()


def test_una_migracion_nueva_se_aplica_al_reabrir(tmp_path, monkeypatch):
    ruta = tmp_path / "db.sqlite"
    abrir_db(ruta).close()  # BD al día con las migraciones actuales

    monkeypatch.setattr(
        "paper_search.db.MIGRACIONES",
        MIGRACIONES + ["ALTER TABLE acciones ADD COLUMN revisado INTEGER DEFAULT 0;"],
    )

    conn = abrir_db(ruta)
    try:
        # Sin número fijo: lo que se comprueba es que se aplica UNA más.
        assert version_esquema(conn) == len(MIGRACIONES) + 1
        columnas = {
            fila["name"] for fila in conn.execute("PRAGMA table_info(acciones)")
        }
        assert "revisado" in columnas
    finally:
        conn.close()


def test_el_indice_sobre_termino_existe(tmp_path):
    conn = abrir_db(tmp_path / "db.sqlite")
    try:
        indices = {
            fila["name"]
            for fila in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "idx_acciones_termino" in indices
    finally:
        conn.close()


def test_las_claves_foraneas_estan_activadas(tmp_path):
    conn = abrir_db(tmp_path / "db.sqlite")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO acciones (timestamp, termino, resultado, cache_id) "
                "VALUES ('2026-08-10T00:00:00+00:00', 'x', 'exito', 999)"
            )
    finally:
        conn.close()


def test_la_ruta_se_configura_con_la_variable_de_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_DB", str(tmp_path / "otra.db"))

    assert ruta_db_por_defecto() == tmp_path / "otra.db"


def test_sin_variable_se_usa_la_ruta_del_repo(monkeypatch):
    monkeypatch.delenv("PAPER_SEARCH_DB", raising=False)

    assert ruta_db_por_defecto() == RUTA_DB_POR_DEFECTO


def test_una_ruta_imposible_da_un_error_claro(tmp_path):
    archivo = tmp_path / "no-es-carpeta"
    archivo.write_text("x")

    with pytest.raises(BaseDatosError, match="PAPER_SEARCH_DB"):
        # El padre de la ruta es un archivo: mkdir/connect no pueden funcionar.
        abrir_db(archivo / "db.sqlite")


def test_un_fallo_de_sqlite_al_conectar_tambien_se_envuelve(tmp_path, monkeypatch):
    """`sqlite3.connect` lanza sqlite3.OperationalError, que NO es OSError.

    Sin capturarla, una ruta que sqlite no puede abrir salía como traceback en
    vez de como el aviso de `BaseDatosError`.
    """
    import sqlite3

    def connect_roto(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", connect_roto)

    with pytest.raises(BaseDatosError, match="PAPER_SEARCH_DB"):
        abrir_db(tmp_path / "db.sqlite")


def test_en_memoria_para_tests():
    conn = abrir_db(":memory:")
    try:
        assert version_esquema(conn) == len(MIGRACIONES)
    finally:
        conn.close()
