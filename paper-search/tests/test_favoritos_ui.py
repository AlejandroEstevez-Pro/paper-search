"""Favoritos a través de la CLI y de la web.

Va en su propio archivo porque necesita algo que `test_cli.py` y `test_app.py`
no dan: una base de datos que **sobreviva entre llamadas**. Aquellos tests
sustituyen `abrir_db` por una BD en memoria nueva cada vez, que es lo correcto
para una búsqueda aislada pero inservible aquí — marcar en una llamada y listar
en la siguiente exige persistencia. Se usa un archivo temporal real.
"""

from __future__ import annotations

import json

import pytest

import app as web
import cli
from paper_search import Paper, abrir_db
from paper_search.registro import RegistroAcciones

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="Variantes de SCN1A en el sindrome de Dravet",
        autores=("Garcia A",),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="Se identificaron 42 variantes nuevas.",
    ),
    Paper(
        pmid="38999999",
        titulo="Historia natural de una encefalopatia epileptica",
        autores=("Lopez B",),
        revista="Orphanet J Rare Dis",
        fecha="2023",
        abstract="Seguimiento de 20 pacientes.",
    ),
)


@pytest.fixture
def db_persistente(tmp_path, monkeypatch):
    """BD en archivo, con `papers` ya poblada como tras una búsqueda real."""
    ruta = tmp_path / "favoritos.db"
    conn = abrir_db(ruta)
    RegistroAcciones(conn).guardar_papers(PAPERS)
    conn.close()

    monkeypatch.setattr(cli, "abrir_db", lambda: abrir_db(ruta))
    monkeypatch.setattr(web, "abrir_db", lambda: abrir_db(ruta))
    monkeypatch.setattr(cli, "cargar_env", lambda: False)
    return ruta


@pytest.fixture
def cliente(db_persistente):
    web.app.config["TESTING"] = True
    return web.app.test_client()


def texto(respuesta) -> str:
    return respuesta.get_data(as_text=True)


# ------------------------------------------------------------------- CLI


def test_cli_listar_sin_favoritos(db_persistente, capsys):
    assert cli.main(["favoritos", "listar"]) == cli.EXIT_OK

    assert "No tienes ningún paper en favoritos" in capsys.readouterr().out


def test_cli_marcar_y_listar(db_persistente, capsys):
    assert cli.main(["favoritos", "marcar", "38123456"]) == cli.EXIT_OK
    capsys.readouterr()

    cli.main(["favoritos", "listar"])

    salida = capsys.readouterr().out
    assert "FAVORITOS (1)" in salida
    assert "Variantes de SCN1A" in salida
    assert "https://pubmed.ncbi.nlm.nih.gov/38123456/" in salida


def test_cli_marcar_con_nota_y_verla_en_el_listado(db_persistente, capsys):
    cli.main(["favoritos", "marcar", "38123456", "--nota", "Revisar la tabla 2"])
    capsys.readouterr()

    cli.main(["favoritos", "listar"])

    assert "Nota: Revisar la tabla 2" in capsys.readouterr().out


def test_cli_marcar_un_pmid_huerfano_falla(db_persistente, capsys):
    codigo = cli.main(["favoritos", "marcar", "99999999"])

    assert codigo == cli.EXIT_USO
    error = capsys.readouterr().err
    assert "99999999" in error
    assert "búsqueda" in error


def test_cli_anadir_y_editar_nota(db_persistente, capsys):
    cli.main(["favoritos", "marcar", "38123456"])

    assert cli.main(["favoritos", "nota", "38123456", "Primera"]) == cli.EXIT_OK
    assert cli.main(["favoritos", "nota", "38123456", "Segunda"]) == cli.EXIT_OK
    capsys.readouterr()

    cli.main(["favoritos", "listar"])
    salida = capsys.readouterr().out
    assert "Nota: Segunda" in salida
    assert "Primera" not in salida


def test_cli_borrar_la_nota(db_persistente, capsys):
    cli.main(["favoritos", "marcar", "38123456", "--nota", "Algo"])

    assert cli.main(["favoritos", "nota", "38123456", "--borrar"]) == cli.EXIT_OK

    assert "Nota borrada" in capsys.readouterr().out


def test_cli_nota_sin_texto_ni_borrar_es_error_de_uso(db_persistente, capsys):
    cli.main(["favoritos", "marcar", "38123456"])
    capsys.readouterr()

    codigo = cli.main(["favoritos", "nota", "38123456"])

    assert codigo == cli.EXIT_USO
    assert "--borrar" in capsys.readouterr().err


def test_cli_anotar_algo_no_marcado_falla(db_persistente, capsys):
    codigo = cli.main(["favoritos", "nota", "38123456", "Una nota"])

    assert codigo == cli.EXIT_USO
    assert "Márcalo primero" in capsys.readouterr().err


def test_cli_desmarcar_sin_nota_no_pregunta(db_persistente, capsys):
    cli.main(["favoritos", "marcar", "38123456"])
    capsys.readouterr()

    assert cli.main(["favoritos", "desmarcar", "38123456"]) == cli.EXIT_OK

    assert "Quitado de favoritos" in capsys.readouterr().out
    capsys.readouterr()
    cli.main(["favoritos", "listar"])
    assert "No tienes ningún paper" in capsys.readouterr().out


def test_cli_desmarcar_con_nota_no_borra_sin_confirmar(db_persistente, capsys):
    """Sin terminal interactiva la respuesta es NO: no se pierde la nota."""
    cli.main(["favoritos", "marcar", "38123456", "--nota", "No la pierdas"])
    capsys.readouterr()

    cli.main(["favoritos", "desmarcar", "38123456"])

    salida = capsys.readouterr().out
    assert "se borrará" in salida
    assert "Cancelado" in salida
    capsys.readouterr()
    cli.main(["favoritos", "listar"])
    assert "Nota: No la pierdas" in capsys.readouterr().out


def test_cli_desmarcar_con_nota_y_si_lo_borra(db_persistente, capsys):
    cli.main(["favoritos", "marcar", "38123456", "--nota", "Adiós"])
    capsys.readouterr()

    assert cli.main(["favoritos", "desmarcar", "38123456", "--si"]) == cli.EXIT_OK

    assert "Quitado de favoritos" in capsys.readouterr().out


def test_cli_desmarcar_algo_no_marcado_no_es_error(db_persistente, capsys):
    codigo = cli.main(["favoritos", "desmarcar", "38123456"])

    assert codigo == cli.EXIT_OK
    assert "no estaba en favoritos" in capsys.readouterr().out


# ------------------------------------------------------------------- web


def alternar(cliente, pmid, confirmado=False):
    return cliente.post(
        "/favoritos/alternar",
        json={"pmid": pmid, "confirmado": confirmado},
    )


def test_web_la_vista_vacia_lo_dice(cliente):
    cuerpo = texto(cliente.get("/favoritos"))

    assert "Todavía no has guardado ningún paper" in cuerpo


def test_web_marcar_y_ver_en_la_vista(cliente):
    respuesta = alternar(cliente, "38123456")

    assert respuesta.status_code == 200
    assert respuesta.get_json()["favorito"] is True
    cuerpo = texto(cliente.get("/favoritos"))
    assert "Variantes de SCN1A" in cuerpo
    assert "Guardados (1)" in cuerpo


def test_web_alternar_dos_veces_desmarca(cliente):
    alternar(cliente, "38123456")

    respuesta = alternar(cliente, "38123456")

    assert respuesta.get_json()["favorito"] is False
    assert "Todavía no has guardado" in texto(cliente.get("/favoritos"))


def test_web_marcar_un_pmid_huerfano_responde_400(cliente):
    respuesta = alternar(cliente, "99999999")

    assert respuesta.status_code == 400
    assert "99999999" in respuesta.get_json()["error"]


def test_web_guardar_y_editar_la_nota(cliente):
    alternar(cliente, "38123456")

    respuesta = cliente.post(
        "/favoritos/nota", data={"pmid": "38123456", "nota": "Mi nota"}
    )

    assert respuesta.status_code == 302  # redirige a la vista
    cuerpo = texto(cliente.get("/favoritos"))
    assert "Mi nota" in cuerpo

    cliente.post("/favoritos/nota", data={"pmid": "38123456", "nota": "Corregida"})
    cuerpo = texto(cliente.get("/favoritos"))
    assert "Corregida" in cuerpo
    assert "Mi nota" not in cuerpo


def test_web_la_nota_es_editable_desde_la_vista(cliente):
    """El textarea sale relleno: editar es cambiar y volver a guardar."""
    alternar(cliente, "38123456")
    cliente.post("/favoritos/nota", data={"pmid": "38123456", "nota": "Editable"})

    cuerpo = texto(cliente.get("/favoritos"))

    assert "<textarea" in cuerpo
    assert ">Editable</textarea>" in cuerpo


def test_web_anotar_algo_no_marcado_responde_400(cliente):
    respuesta = cliente.post(
        "/favoritos/nota", data={"pmid": "38123456", "nota": "Sin marcar"}
    )

    assert respuesta.status_code == 400
    assert "Márcalo primero" in texto(respuesta)


def test_web_desmarcar_con_nota_pide_confirmacion_antes(cliente):
    alternar(cliente, "38123456")
    cliente.post("/favoritos/nota", data={"pmid": "38123456", "nota": "No la pierdas"})

    respuesta = alternar(cliente, "38123456")

    datos = respuesta.get_json()
    assert datos["requiere_confirmacion"] is True
    assert datos["nota"] == "No la pierdas"
    assert datos["favorito"] is True  # sigue marcado: no se ha tocado nada
    assert "No la pierdas" in texto(cliente.get("/favoritos"))


def test_web_desmarcar_confirmado_si_borra(cliente):
    alternar(cliente, "38123456")
    cliente.post("/favoritos/nota", data={"pmid": "38123456", "nota": "Adiós"})

    respuesta = alternar(cliente, "38123456", confirmado=True)

    assert respuesta.get_json()["favorito"] is False
    assert "Todavía no has guardado" in texto(cliente.get("/favoritos"))


def test_web_quitar_desde_la_vista(cliente):
    alternar(cliente, "38123456")

    respuesta = cliente.post("/favoritos/quitar", data={"pmid": "38123456"})

    assert respuesta.status_code == 302
    assert "Todavía no has guardado" in texto(cliente.get("/favoritos"))


def test_web_el_boton_sale_en_cada_resultado_con_su_estado(cliente, monkeypatch):
    """El botón nace en el estado correcto, sin esperar a un fetch."""
    from paper_search import ResultadoBusqueda

    monkeypatch.setattr(
        web,
        "buscar_y_resumir",
        lambda termino, **kwargs: ResultadoBusqueda(
            query=termino, papers=PAPERS, resumen="Resumen [PMID: 38123456].", dias=365
        ),
    )
    alternar(cliente, "38123456")  # uno marcado, el otro no

    cuerpo = texto(cliente.post("/buscar", data={"termino": "SCN1A"}))

    assert 'data-pmid="38123456"' in cuerpo
    assert 'data-pmid="38999999"' in cuerpo
    assert "★ En favoritos" in cuerpo
    assert "☆ Guardar en favoritos" in cuerpo


def test_web_la_vista_de_favoritos_no_consulta_pubmed(cliente, monkeypatch):
    import paper_search.pubmed_client as pubmed

    def prohibido(*args, **kwargs):  # pragma: no cover - no debe ejecutarse
        raise AssertionError("la vista de favoritos no debe consultar PubMed")

    monkeypatch.setattr(pubmed.PubMedClient, "buscar_papers", prohibido)
    alternar(cliente, "38123456")

    assert "Variantes de SCN1A" in texto(cliente.get("/favoritos"))
