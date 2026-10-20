"""`NCBI_EMAIL` es obligatorio y no tiene valor por defecto.

NCBI pide a quien usa su API un email de contacto real. Antes había uno fijo
en el código (el del autor), así que cualquiera que clonase el repo hablaba con
NCBI en su nombre. Ahora, sin `NCBI_EMAIL`, no se consulta PubMed: se falla con
un mensaje que explica qué es y por qué se pide, y se falla ANTES de gastar
ninguna llamada a Claude o de contar la búsqueda en los límites diarios.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import app as web
import cli
from paper_search import (
    FaltaEmailNCBIError,
    MENSAJE_FALTA_EMAIL,
    PaperSearchError,
    PubMedError,
    abrir_db,
    buscar_y_resumir,
)
from paper_search import pubmed_client
from paper_search.limites import LimitesUso
from paper_search.pubmed_client import PubMedClient

RAIZ = Path(__file__).resolve().parent.parent
PATRON_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


# ------------------------------------------------------------------ cliente


def test_sin_ncbi_email_el_cliente_no_se_construye():
    with pytest.raises(FaltaEmailNCBIError):
        PubMedClient()


@pytest.mark.parametrize("valor", ["", "   ", "sin-arroba"])
def test_un_ncbi_email_vacio_o_sin_arroba_tampoco_vale(monkeypatch, valor):
    monkeypatch.setenv("NCBI_EMAIL", valor)

    with pytest.raises(FaltaEmailNCBIError):
        PubMedClient()


def test_el_email_del_entorno_se_usa_sin_espacios(monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "  yo@example.org \n")

    assert PubMedClient().email == "yo@example.org"


def test_el_email_explicito_gana_al_del_entorno(monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "entorno@example.org")

    assert PubMedClient(email="explicito@example.org").email == "explicito@example.org"


def test_el_mensaje_explica_que_es_y_por_que_se_pide():
    with pytest.raises(FaltaEmailNCBIError) as excinfo:
        PubMedClient()

    mensaje = str(excinfo.value)
    assert mensaje == MENSAJE_FALTA_EMAIL
    assert "NCBI_EMAIL" in mensaje
    assert "NCBI" in mensaje and "PubMed" in mensaje
    assert ".env" in mensaje
    # No sugiere ninguna dirección concreta que se pueda copiar tal cual.
    assert PATRON_EMAIL.search(mensaje) is None


def test_es_un_error_de_configuracion_no_de_pubmed():
    """Así la web no lo sirve como 502 ni el registro lo anota como fallo de PubMed."""
    assert issubclass(FaltaEmailNCBIError, PaperSearchError)
    assert not issubclass(FaltaEmailNCBIError, PubMedError)


def test_no_queda_ningun_email_por_defecto_en_el_codigo():
    assert not hasattr(pubmed_client, "EMAIL_POR_DEFECTO")
    for ruta in (RAIZ / "src" / "paper_search").glob("*.py"):
        assert PATRON_EMAIL.search(ruta.read_text(encoding="utf-8")) is None, ruta.name


def test_la_plantilla_env_no_trae_un_email_que_usar_tal_cual():
    plantilla = (RAIZ / ".env.example").read_text(encoding="utf-8")

    assert re.search(r"^NCBI_EMAIL=\s*$", plantilla, re.MULTILINE), (
        "NCBI_EMAIL debe estar en .env.example, sin comentar y vacío"
    )
    assert PATRON_EMAIL.search(plantilla) is None


# ------------------------------------------------------- buscar_y_resumir


class AlcanceQueNoDebeLlamarse:
    def verificar(self, *args, **kwargs):  # pragma: no cover - si se llega, falla
        raise AssertionError("se gastó la llamada de alcance sin poder consultar PubMed")


def test_falla_antes_de_gastar_llamadas_o_contar_la_busqueda():
    db = abrir_db(":memory:")
    try:
        limites = LimitesUso(db)

        with pytest.raises(FaltaEmailNCBIError):
            buscar_y_resumir(
                "SCN1A",
                db=db,
                limites=limites,
                verificador_alcance=AlcanceQueNoDebeLlamarse(),
            )

        assert limites.uso_de_hoy() == (0, 0)
    finally:
        db.close()


# ------------------------------------------------------------- CLI y web


def test_la_cli_lo_explica_y_sale_con_el_codigo_de_uso(monkeypatch, capsys):
    monkeypatch.setattr(cli, "abrir_db", lambda: abrir_db(":memory:"))
    monkeypatch.setattr(cli, "cargar_env", lambda: False)

    codigo = cli.main(["buscar", "SCN1A"])

    assert codigo == cli.EXIT_USO
    assert "NCBI_EMAIL" in capsys.readouterr().err


def test_la_web_lo_explica_con_un_500_y_no_un_502(monkeypatch):
    monkeypatch.setattr(web, "abrir_db", lambda: abrir_db(":memory:"))
    web.app.config["TESTING"] = True

    respuesta = web.app.test_client().post("/buscar", data={"termino": "SCN1A"})

    assert respuesta.status_code == 500
    assert "NCBI_EMAIL" in respuesta.get_data(as_text=True)
