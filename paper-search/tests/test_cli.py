"""Tests de la CLI (aviso de clave, códigos de salida, renderizado).

Igual que en `test_app.py`, se sustituye `buscar_y_resumir` en el módulo `cli`
por un doble: aquí se prueba la capa de entrada/salida, no la búsqueda.
"""

from __future__ import annotations

import json

import pytest

import cli
from paper_search import Paper, ResultadoBusqueda, abrir_db

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="Variantes de SCN1A en el sindrome de Dravet",
        autores=("Garcia A",),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="Se identificaron 42 variantes nuevas.",
    ),
)


@pytest.fixture(autouse=True)
def cli_aislada(monkeypatch):
    """Aísla la CLI de la máquina: ni BD real en `datos/` ni el `.env` real.

    Sin esto, `cli.main()` cargaría el `.env` del repo (que puede tener una
    clave de verdad) y desharía el `delenv` de los tests.
    """
    monkeypatch.setattr(cli, "abrir_db", lambda: abrir_db(":memory:"))
    monkeypatch.setattr(cli, "cargar_env", lambda: False)


def busqueda_falsa(monkeypatch, resultado):
    """Sustituye la búsqueda real y captura los kwargs con que se llamó."""
    llamadas: list[dict] = []

    def falsa(termino, **kwargs):
        llamadas.append({"termino": termino, **kwargs})
        return resultado

    monkeypatch.setattr(cli, "buscar_y_resumir", falsa)
    return llamadas


# ----------------------------------------------------- búsqueda avanzada


def test_se_pueden_pasar_autor_y_patogeno(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llamadas = busqueda_falsa(
        monkeypatch,
        ResultadoBusqueda(query="x", papers=PAPERS, resumen="R.", dias=365),
    )

    cli.main(
        [
            "buscar",
            "toxoplasmosis",
            "--autor",
            "Lopez B",
            "--patogeno",
            "Toxoplasma gondii",
        ]
    )

    assert llamadas[0]["termino"] == "toxoplasmosis"
    assert llamadas[0]["autor"] == "Lopez B"
    assert llamadas[0]["patogeno"] == "Toxoplasma gondii"


def test_se_puede_buscar_solo_por_autor(monkeypatch, capsys):
    """El término deja de ser obligatorio si hay otro criterio."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llamadas = busqueda_falsa(
        monkeypatch,
        ResultadoBusqueda(query='"Scheffer IE"[AU]', papers=PAPERS, resumen="R.", dias=365),
    )

    codigo = cli.main(["buscar", "--autor", "Scheffer IE"])

    assert codigo == cli.EXIT_OK
    assert llamadas[0]["termino"] == ""
    assert llamadas[0]["autor"] == "Scheffer IE"


def test_sin_ningun_criterio_argparse_lo_rechaza(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    busqueda_falsa(monkeypatch, ResultadoBusqueda(query="x", papers=PAPERS))

    with pytest.raises(SystemExit):
        cli.main(["buscar"])


# --------------------------------------------------------------- orden


def test_el_orden_por_defecto_es_por_fecha(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llamadas = busqueda_falsa(
        monkeypatch,
        ResultadoBusqueda(query="SCN1A", papers=PAPERS, resumen="R.", dias=365),
    )

    cli.main(["buscar", "SCN1A"])

    assert llamadas[0]["orden"] == "fecha"


def test_se_puede_pedir_orden_por_relevancia(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llamadas = busqueda_falsa(
        monkeypatch,
        ResultadoBusqueda(
            query="SCN1A", papers=PAPERS, resumen="R.", dias=365, orden="relevancia"
        ),
    )

    cli.main(["buscar", "SCN1A", "--orden", "relevancia"])

    assert llamadas[0]["orden"] == "relevancia"
    assert "Orden: Más relevantes primero" in capsys.readouterr().out


def test_un_orden_invalido_lo_rechaza_argparse(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    busqueda_falsa(monkeypatch, ResultadoBusqueda(query="SCN1A", papers=PAPERS))

    with pytest.raises(SystemExit):
        cli.main(["buscar", "SCN1A", "--orden", "por_color"])


# ------------------------------------------------------- aviso de idioma


def test_el_aviso_de_idioma_se_imprime(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    busqueda_falsa(
        monkeypatch,
        ResultadoBusqueda(
            query="síndrome de Dravet",
            papers=PAPERS,
            resumen="Resumen [PMID: 38123456].",
            dias=365,
            aviso_idioma="El término «síndrome de Dravet» parece estar en español.",
        ),
    )

    codigo = cli.main(["buscar", "síndrome de Dravet"])

    salida = capsys.readouterr().out
    assert "AVISO DE IDIOMA:" in salida
    assert "parece estar en español" in salida
    # Es informativo: la búsqueda es correcta y las referencias se muestran.
    assert codigo == cli.EXIT_OK
    assert "38123456" in salida


def test_sin_aviso_de_idioma_no_se_imprime_la_seccion(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    busqueda_falsa(
        monkeypatch,
        ResultadoBusqueda(
            query="SCN1A", papers=PAPERS, resumen="Resumen [PMID: 38123456].", dias=365
        ),
    )

    cli.main(["buscar", "SCN1A"])

    assert "AVISO DE IDIOMA" not in capsys.readouterr().out


def test_el_aviso_de_idioma_va_en_el_json(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    busqueda_falsa(
        monkeypatch,
        ResultadoBusqueda(
            query="síndrome de Dravet",
            papers=PAPERS,
            resumen="Resumen [PMID: 38123456].",
            dias=365,
            aviso_idioma="Parece estar en español.",
        ),
    )

    cli.main(["buscar", "síndrome de Dravet", "--formato", "json"])

    datos = json.loads(capsys.readouterr().out)
    assert datos["aviso_idioma"] == "Parece estar en español."


# --------------------------------------------- aviso de clave consolidado


def test_sin_clave_el_aviso_sale_una_sola_vez(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    busqueda_falsa(monkeypatch, ResultadoBusqueda(query="SCN1A", papers=PAPERS, dias=365))

    cli.main(["buscar", "SCN1A"])

    salida = capsys.readouterr()
    todo = salida.out + salida.err
    # El mensaje completo (con instrucciones) aparece exactamente una vez, y
    # en stderr, al principio.
    assert todo.count("Falta ANTHROPIC_API_KEY") == 1
    assert "Falta ANTHROPIC_API_KEY" in salida.err
    # Ninguna de las repeticiones antiguas: ni el aviso del guardarraíl de
    # alcance ("falta la clave de la API") ni el "Motivo: desconocido".
    assert "falta la clave de la API" not in todo
    assert "desconocido" not in todo


def test_sin_clave_no_se_piden_ni_alcance_ni_resumen(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llamadas = busqueda_falsa(
        monkeypatch, ResultadoBusqueda(query="SCN1A", papers=PAPERS, dias=365)
    )

    codigo = cli.main(["buscar", "SCN1A"])

    assert llamadas[0]["resumir"] is False
    assert llamadas[0]["verificar_alcance"] is False
    # Se mantiene el contrato documentado: sin resumen, código de salida 2.
    assert codigo == cli.EXIT_FALLO_API
    # Las referencias reales sí se muestran.
    assert "38123456" in capsys.readouterr().out


def test_sin_clave_el_cuerpo_remite_al_aviso_del_inicio(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    busqueda_falsa(monkeypatch, ResultadoBusqueda(query="SCN1A", papers=PAPERS, dias=365))

    cli.main(["buscar", "SCN1A"])

    assert "ver el aviso del inicio" in capsys.readouterr().out


def test_con_clave_no_hay_aviso_y_se_pide_el_resumen(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llamadas = busqueda_falsa(
        monkeypatch,
        ResultadoBusqueda(
            query="SCN1A", papers=PAPERS, resumen="Resumen [PMID: 38123456].", dias=365
        ),
    )

    codigo = cli.main(["buscar", "SCN1A"])

    salida = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" not in salida.out + salida.err
    assert llamadas[0]["resumir"] is True
    assert llamadas[0]["verificar_alcance"] is True
    assert codigo == cli.EXIT_OK


def test_sin_clave_el_json_queda_limpio_en_stdout(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    busqueda_falsa(monkeypatch, ResultadoBusqueda(query="SCN1A", papers=PAPERS, dias=365))

    cli.main(["buscar", "SCN1A", "--formato", "json"])

    salida = capsys.readouterr()
    datos = json.loads(salida.out)  # stdout es JSON válido, sin el aviso mezclado
    assert datos["query"] == "SCN1A"
    assert salida.err.count("Falta ANTHROPIC_API_KEY") == 1
