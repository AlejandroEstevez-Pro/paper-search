"""Tests del buscador avanzado: término + autor + patógeno.

Lo que se protege aquí:

- que el **autor nunca llegue al guardarraíl de alcance** (solo término y
  patógeno son sujeto médico),
- que una búsqueda **solo por autor** pase con aviso y **sin gastar llamada**,
- que filtrar en local no consulte PubMed y no pueda inventar resultados.
"""

from __future__ import annotations

import pytest

from paper_search import (
    Criterios,
    CriteriosVaciosError,
    Paper,
    buscar_y_resumir,
    construir_consulta,
    filtrar_papers,
    sujeto_de_alcance,
)
from paper_search.alcance import (
    AMBIGUO,
    DENTRO_DE_ALCANCE,
    FUERA_DE_ALCANCE,
    MOTIVO_SIN_SUJETO,
    NO_CONCLUYENTE,
    TerminoFueraDeAlcanceError,
    VerificadorAlcance,
)

PAPERS = (
    Paper(
        pmid="1",
        titulo="SCN1A variants in Dravet syndrome",
        autores=("García A", "Smith JR"),
        abstract="Cohort of 42 patients.",
        orden_relevancia=0,
    ),
    Paper(
        pmid="2",
        titulo="Congenital toxoplasmosis outcomes",
        autores=("Lopez B",),
        abstract="Infection by Toxoplasma gondii in newborns.",
        orden_relevancia=1,
    ),
    Paper(
        pmid="3",
        titulo="Natural history of epileptic encephalopathy",
        autores=("Smith JR", "Nguyen T"),
        abstract="Follow-up over ten years.",
        orden_relevancia=2,
    ),
)


# ------------------------------------------------------------- construcción


def test_solo_termino_produce_la_consulta_de_siempre():
    """Sin criterios nuevos, la consulta no cambia respecto a las Fases 1-2."""
    assert construir_consulta(Criterios.de("SCN1A")) == "SCN1A"


def test_el_termino_no_se_toca_para_no_romper_la_sintaxis_de_pubmed():
    consulta = construir_consulta(Criterios.de("SCN1A OR SCN2A"))

    assert consulta == "SCN1A OR SCN2A"


def test_termino_mas_autor():
    consulta = construir_consulta(Criterios.de("Dravet", autor="Scheffer IE"))

    assert consulta == '(Dravet) AND ("Scheffer IE"[AU])'


def test_termino_mas_patogeno():
    consulta = construir_consulta(
        Criterios.de("toxoplasmosis", patogeno="Toxoplasma gondii")
    )

    assert consulta == '(toxoplasmosis) AND ("Toxoplasma gondii")'


def test_los_tres_criterios_juntos():
    consulta = construir_consulta(
        Criterios.de("toxoplasmosis", autor="Lopez B", patogeno="Toxoplasma gondii")
    )

    assert consulta == (
        '(toxoplasmosis) AND ("Lopez B"[AU]) AND ("Toxoplasma gondii")'
    )


def test_solo_autor_es_una_consulta_valida():
    assert construir_consulta(Criterios.de(autor="Scheffer IE")) == '"Scheffer IE"[AU]'


def test_sin_ningun_criterio_es_error():
    with pytest.raises(CriteriosVaciosError):
        construir_consulta(Criterios.de())


def test_los_valores_no_pueden_romper_la_consulta():
    """Comillas y corchetes en autor/patógeno se limpian antes de envolver."""
    consulta = construir_consulta(
        Criterios.de("x", autor='Smith" OR [AU] "', patogeno="a(b)c")
    )

    assert consulta.count('"[AU]') == 1
    assert "(abc)" in consulta or '"abc"' in consulta


# ------------------------------------------- qué ve el guardarraíl de alcance


def test_el_sujeto_es_termino_mas_patogeno():
    criterios = Criterios.de("toxoplasmosis", patogeno="Toxoplasma gondii")

    assert sujeto_de_alcance(criterios) == "toxoplasmosis Toxoplasma gondii"


def test_el_autor_nunca_forma_parte_del_sujeto():
    criterios = Criterios.de("Dravet", autor="Scheffer IE")

    assert sujeto_de_alcance(criterios) == "Dravet"
    assert "Scheffer" not in sujeto_de_alcance(criterios)


def test_solo_autor_deja_el_sujeto_vacio():
    criterios = Criterios.de(autor="Scheffer IE")

    assert sujeto_de_alcance(criterios) == ""
    assert criterios.solo_autor


# ------------------------------------------------------- filtros en local


def test_filtrar_por_autor_sobre_resultados_ya_obtenidos():
    filtrados = filtrar_papers(PAPERS, autor="Smith")

    assert [p.pmid for p in filtrados] == ["1", "3"]


def test_el_filtro_de_autor_ignora_mayusculas_y_tildes():
    assert [p.pmid for p in filtrar_papers(PAPERS, autor="garcia")] == ["1"]
    assert [p.pmid for p in filtrar_papers(PAPERS, autor="GARCÍA")] == ["1"]


def test_filtrar_por_patogeno_mira_titulo_y_abstract():
    filtrados = filtrar_papers(PAPERS, patogeno="toxoplasma")

    assert [p.pmid for p in filtrados] == ["2"]


def test_los_filtros_se_acumulan():
    filtrados = filtrar_papers(PAPERS, autor="Smith", patogeno="Dravet")

    assert [p.pmid for p in filtrados] == ["1"]


def test_sin_filtros_devuelve_todo_en_el_mismo_orden():
    assert filtrar_papers(PAPERS) == PAPERS


def test_un_filtro_que_no_encaja_devuelve_vacio_no_inventa():
    assert filtrar_papers(PAPERS, autor="Nadie Existente") == ()


def test_filtrar_no_consulta_pubmed(monkeypatch):
    import paper_search.pubmed_client as pubmed

    def prohibido(*args, **kwargs):  # pragma: no cover - no debe ejecutarse
        raise AssertionError("filtrar en local no debe consultar PubMed")

    monkeypatch.setattr(pubmed.PubMedClient, "buscar_papers", prohibido)

    assert len(filtrar_papers(PAPERS, autor="Smith")) == 2


def test_filtrar_solo_puede_quitar_nunca_anadir():
    for autor in ("Smith", "garcia", "zzz", ""):
        filtrados = filtrar_papers(PAPERS, autor=autor)
        assert set(p.pmid for p in filtrados) <= {p.pmid for p in PAPERS}


# --------------------------------------------------- dobles para integración


class ClientPubMedFalso:
    def __init__(self, papers=PAPERS):
        self.papers = list(papers)
        self.consultas: list[str] = []

    def buscar_papers(self, termino, *, max_resultados, dias):
        self.consultas.append(termino)
        return list(self.papers)


class VerificadorFalso:
    """Registra qué texto se le pidió clasificar y con qué veredicto responde."""

    def __init__(self, veredicto=DENTRO_DE_ALCANCE, motivo="ok"):
        from paper_search.alcance import VeredictoAlcance

        self._respuesta = VeredictoAlcance(veredicto=veredicto, motivo=motivo)
        self.sujetos: list[str] = []
        self.llamadas = 0

    def verificar(self, termino, *, contador=None):
        self.sujetos.append(termino)
        self.llamadas += 1
        if contador is not None:
            contador()
        return self._respuesta


def buscar(**kwargs):
    client = kwargs.pop("client", None) or ClientPubMedFalso()
    verificador = kwargs.pop("verificador", None) or VerificadorFalso()
    resultado = buscar_y_resumir(
        resumir=False,
        client=client,
        verificador_alcance=verificador,
        **kwargs,
    )
    return resultado, client, verificador


# ------------------------------------------------ búsqueda con criterios


def test_busqueda_por_termino_y_autor():
    resultado, client, verificador = buscar(termino="Dravet", autor="Scheffer IE")

    assert client.consultas == ['(Dravet) AND ("Scheffer IE"[AU])']
    # El guardarraíl solo vio el término.
    assert verificador.sujetos == ["Dravet"]
    assert resultado.criterios.autor == "Scheffer IE"


def test_busqueda_por_termino_y_patogeno():
    resultado, client, verificador = buscar(
        termino="toxoplasmosis congénita", patogeno="Toxoplasma gondii"
    )

    assert client.consultas == [
        '(toxoplasmosis congénita) AND ("Toxoplasma gondii")'
    ]
    # Aquí el patógeno SÍ es sujeto médico y refuerza la clasificación.
    assert verificador.sujetos == ["toxoplasmosis congénita Toxoplasma gondii"]


def test_los_tres_criterios_en_una_busqueda():
    resultado, client, verificador = buscar(
        termino="toxoplasmosis", autor="Lopez B", patogeno="Toxoplasma gondii"
    )

    assert client.consultas == [
        '(toxoplasmosis) AND ("Lopez B"[AU]) AND ("Toxoplasma gondii")'
    ]
    assert verificador.sujetos == ["toxoplasmosis Toxoplasma gondii"]
    assert "Lopez" not in verificador.sujetos[0]
    assert resultado.total == 3


# ------------------------------------- caso límite: búsqueda solo por autor


def test_solo_autor_no_gasta_llamada_de_verificacion():
    """No hay sujeto médico que clasificar: se resuelve en local."""
    resultado, client, verificador = buscar(autor="Scheffer IE")

    assert verificador.llamadas == 0
    assert client.consultas == ['"Scheffer IE"[AU]']


def test_solo_autor_pasa_con_aviso_y_no_bloquea():
    resultado, _, _ = buscar(autor="Scheffer IE")

    assert resultado.total == 3  # la búsqueda se ejecutó
    assert resultado.aviso_alcance is not None
    assert "no incluye ningún término de enfermedad" in resultado.aviso_alcance
    assert "igualmente" in resultado.aviso_alcance


def test_solo_autor_avisa_de_que_puede_salirse_del_ambito():
    resultado, _, _ = buscar(autor="Scheffer IE")

    assert "ajenos a este ámbito" in resultado.aviso_alcance


def test_el_veredicto_sin_sujeto_es_no_concluyente():
    from paper_search.alcance import veredicto_sin_sujeto

    veredicto = veredicto_sin_sujeto()

    assert veredicto.veredicto == NO_CONCLUYENTE
    assert veredicto.motivo == MOTIVO_SIN_SUJETO
    assert not veredicto.bloquea


def test_solo_autor_no_dispara_el_aviso_de_idioma():
    """Un apellido no está «escrito en» ningún idioma."""
    resultado, _, _ = buscar(autor="García Sánchez")

    assert resultado.aviso_idioma is None


def test_el_autor_no_puede_provocar_un_bloqueo_de_alcance():
    """Aunque el verificador diga «fuera de alcance», nunca vio al autor."""
    verificador = VerificadorFalso(FUERA_DE_ALCANCE, "es una enfermedad común")

    with pytest.raises(TerminoFueraDeAlcanceError):
        buscar(termino="gripe", autor="Scheffer IE", verificador=verificador)

    assert verificador.sujetos == ["gripe"]


def test_un_termino_ambiguo_con_autor_sigue_avisando():
    verificador = VerificadorFalso(AMBIGUO, "sigla con varios usos")

    resultado, _, _ = buscar(termino="CDG", autor="Smith J", verificador=verificador)

    assert "sigla con varios usos" in resultado.aviso_alcance
    assert resultado.total == 3


def test_sin_ningun_criterio_la_busqueda_falla_antes_de_pubmed():
    client = ClientPubMedFalso()

    with pytest.raises(CriteriosVaciosError):
        buscar_y_resumir("", client=client, resumir=False, verificar_alcance=False)

    assert client.consultas == []


# ------------------------------------------------ filtrar lo ya buscado


def test_filtrar_los_resultados_de_una_busqueda_sin_repetirla():
    """Modo (a): afinar en pantalla, cero consultas nuevas."""
    resultado, client, _ = buscar(termino="epilepsy")
    consultas_tras_buscar = len(client.consultas)

    filtrados = filtrar_papers(resultado.papers, autor="Smith")

    assert [p.pmid for p in filtrados] == ["1", "3"]
    assert len(client.consultas) == consultas_tras_buscar  # ni una más


def test_el_json_expone_los_criterios():
    resultado, _, _ = buscar(termino="Dravet", autor="Scheffer IE")

    datos = resultado.to_dict()
    assert datos["criterios"] == {
        "termino": "Dravet",
        "autor": "Scheffer IE",
        "patogeno": None,
    }
    assert datos["query"] == '(Dravet) AND ("Scheffer IE"[AU])'
