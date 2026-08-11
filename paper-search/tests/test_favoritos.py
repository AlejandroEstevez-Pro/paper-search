"""Tests de favoritos (migración v2 + módulo `favoritos.py`).

Todo contra una BD en memoria. La tabla `papers` se rellena con el mismo
`RegistroAcciones.guardar_papers` que usa una búsqueda real, para que el test
recorra el camino de verdad: primero buscas, luego marcas lo que salió.
"""

from __future__ import annotations

import pytest

from paper_search import Favoritos, Paper, abrir_db
from paper_search.db import MIGRACIONES, version_esquema
from paper_search.favoritos import FavoritoError
from paper_search.registro import RegistroAcciones

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="Variantes de SCN1A en el sindrome de Dravet",
        autores=("Garcia A", "Smith JR"),
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
def db():
    conn = abrir_db(":memory:")
    # Lo que haría una búsqueda de la Fase 2 antes de que se marque nada.
    RegistroAcciones(conn).guardar_papers(PAPERS)
    yield conn
    conn.close()


@pytest.fixture
def favoritos(db):
    return Favoritos(db)


# --------------------------------------------------------------- migración


def test_la_migracion_v2_esta_aplicada(db):
    assert version_esquema(db) == len(MIGRACIONES)
    assert version_esquema(db) >= 2


def test_la_tabla_favoritos_existe_con_sus_columnas(db):
    columnas = {fila["name"] for fila in db.execute("PRAGMA table_info(favoritos)")}

    assert columnas == {"pmid", "nota", "creado_en", "actualizado_en"}


def test_las_migraciones_son_reejecutables(db):
    """El patrón del repo: cada script debe poder reaplicarse sin daño."""
    from paper_search.db import aplicar_migraciones

    for script in MIGRACIONES:
        db.executescript(script)

    assert aplicar_migraciones(db) == len(MIGRACIONES)


# ------------------------------------------------------------ marcar/desmarcar


def test_marcar_un_paper_que_salio_en_una_busqueda(favoritos):
    favorito = favoritos.marcar("38123456")

    assert favorito.pmid == "38123456"
    # Los metadatos vienen de la BD local: no se ha consultado PubMed.
    assert favorito.paper.titulo == "Variantes de SCN1A en el sindrome de Dravet"
    assert favorito.paper.revista == "Epilepsia"
    assert favorito.nota is None
    assert favoritos.es_favorito("38123456")


def test_marcar_es_idempotente(favoritos):
    favoritos.marcar("38123456")
    favoritos.marcar("38123456")

    assert len(favoritos.listar()) == 1


def test_re_marcar_no_pisa_la_nota_existente(favoritos):
    favoritos.marcar("38123456", nota="Revisar la tabla 2")
    favoritos.marcar("38123456")

    assert favoritos.obtener("38123456").nota == "Revisar la tabla 2"


def test_desmarcar_quita_el_favorito(favoritos):
    favoritos.marcar("38123456")

    assert favoritos.desmarcar("38123456") is True
    assert not favoritos.es_favorito("38123456")
    assert favoritos.listar() == []


def test_desmarcar_algo_no_marcado_no_es_un_error(favoritos):
    assert favoritos.desmarcar("38123456") is False


def test_desmarcar_borra_tambien_la_nota(favoritos):
    """Decisión registrada: se va la fila entera, nota incluida."""
    favoritos.marcar("38123456", nota="Importante")
    favoritos.desmarcar("38123456")
    favoritos.marcar("38123456")

    assert favoritos.obtener("38123456").nota is None


# -------------------------------------------------------- PMID huérfano


def test_marcar_un_pmid_desconocido_falla_con_mensaje_claro(favoritos):
    with pytest.raises(FavoritoError) as excinfo:
        favoritos.marcar("99999999")

    mensaje = str(excinfo.value)
    assert "99999999" in mensaje
    assert "búsqueda" in mensaje  # dice qué hacer, no solo que falló


def test_un_pmid_desconocido_no_deja_favorito_huerfano(favoritos, db):
    with pytest.raises(FavoritoError):
        favoritos.marcar("99999999")

    assert favoritos.listar() == []
    filas = db.execute("SELECT COUNT(*) AS n FROM favoritos").fetchone()
    assert filas["n"] == 0


def test_un_pmid_que_no_es_numero_se_rechaza(favoritos):
    with pytest.raises(FavoritoError) as excinfo:
        favoritos.marcar("SCN1A")

    assert "no parece un PMID" in str(excinfo.value)


def test_un_pmid_vacio_se_rechaza(favoritos):
    with pytest.raises(FavoritoError):
        favoritos.marcar("   ")


# ---------------------------------------------------------------- notas


def test_anadir_una_nota_al_marcar(favoritos):
    favorito = favoritos.marcar("38123456", nota="Mirar la cohorte")

    assert favorito.nota == "Mirar la cohorte"
    assert favorito.tiene_nota


def test_anadir_una_nota_despues_de_marcar(favoritos):
    favoritos.marcar("38123456")

    favorito = favoritos.anotar("38123456", "Nota puesta más tarde")

    assert favorito.nota == "Nota puesta más tarde"


def test_editar_una_nota_existente(favoritos):
    favoritos.marcar("38123456", nota="Primera versión")

    favorito = favoritos.anotar("38123456", "Segunda versión")

    assert favorito.nota == "Segunda versión"
    assert len(favoritos.listar()) == 1


def test_vaciar_una_nota_la_deja_en_nulo(favoritos):
    """«Sin nota» tiene una sola representación: NULL, nunca ''."""
    favoritos.marcar("38123456", nota="Algo")

    favorito = favoritos.anotar("38123456", "   ")

    assert favorito.nota is None
    assert not favorito.tiene_nota


def test_anotar_algo_no_marcado_falla_y_no_lo_marca(favoritos):
    """Anotar no marca por su cuenta: evita favoritos creados sin querer."""
    with pytest.raises(FavoritoError) as excinfo:
        favoritos.anotar("38123456", "Una nota")

    assert "Márcalo primero" in str(excinfo.value)
    assert not favoritos.es_favorito("38123456")


def test_editar_la_nota_actualiza_la_marca_de_tiempo(favoritos):
    """Por eso existe `actualizado_en` además de `creado_en`."""
    momentos = iter(["2026-08-10T10:00:00+00:00", "2026-08-11T18:30:00+00:00"])
    favs = Favoritos(favoritos.conn, ahora=lambda: next(momentos))

    favs.marcar("38123456", nota="Primera")
    favorito = favs.anotar("38123456", "Segunda")

    assert favorito.creado_en == "2026-08-10T10:00:00+00:00"
    assert favorito.actualizado_en == "2026-08-11T18:30:00+00:00"


# --------------------------------------------------------------- listado


def test_listar_sin_favoritos_devuelve_vacio(favoritos):
    assert favoritos.listar() == []
    assert favoritos.pmids() == set()


def test_listar_con_contenido_trae_los_metadatos_y_la_nota(favoritos):
    favoritos.marcar("38123456", nota="Revisar")
    favoritos.marcar("38999999")

    lista = favoritos.listar()

    assert len(lista) == 2
    por_pmid = {f.pmid: f for f in lista}
    assert por_pmid["38123456"].nota == "Revisar"
    assert por_pmid["38999999"].nota is None
    assert por_pmid["38999999"].paper.revista == "Orphanet J Rare Dis"
    assert por_pmid["38123456"].paper.autores == ("Garcia A", "Smith JR")


def test_listar_ordena_del_mas_reciente_al_mas_antiguo(favoritos):
    momentos = iter(["2026-08-01T10:00:00+00:00", "2026-08-09T10:00:00+00:00"])
    favs = Favoritos(favoritos.conn, ahora=lambda: next(momentos))

    favs.marcar("38123456")  # el más antiguo
    favs.marcar("38999999")  # el más reciente

    assert [f.pmid for f in favs.listar()] == ["38999999", "38123456"]


def test_pmids_devuelve_el_conjunto_marcado(favoritos):
    favoritos.marcar("38123456")

    assert favoritos.pmids() == {"38123456"}


def test_el_favorito_se_serializa_con_su_nota(favoritos):
    favoritos.marcar("38123456", nota="Para la reunión")

    datos = favoritos.listar()[0].to_dict()

    assert datos["pmid"] == "38123456"
    assert datos["nota"] == "Para la reunión"
    assert datos["url"] == "https://pubmed.ncbi.nlm.nih.gov/38123456/"


def test_marcar_no_consulta_pubmed(favoritos, monkeypatch):
    """Garantía explícita: los metadatos salen de `papers`, no de la red."""
    import paper_search.pubmed_client as pubmed

    def prohibido(*args, **kwargs):  # pragma: no cover - no debe ejecutarse
        raise AssertionError("no se debe consultar PubMed al marcar un favorito")

    monkeypatch.setattr(pubmed.PubMedClient, "buscar_papers", prohibido)
    monkeypatch.setattr(pubmed.PubMedClient, "obtener_detalles", prohibido)

    favoritos.marcar("38123456")

    assert favoritos.listar()[0].paper.titulo.startswith("Variantes de SCN1A")
