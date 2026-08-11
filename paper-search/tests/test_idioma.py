"""Tests del aviso de idioma (español, catalán, euskera, gallego).

Dos bloques:

1. Los casos pedidos en la especificación: una lengua por test, más los
   negativos (inglés, genes, nombres propios) y el término mixto.
2. Un corpus de regresión con las trampas reales del dominio. Los falsos
   positivos son el riesgo serio de esta función —avisar a quien ya busca en
   inglés entrena a ignorar todos los avisos, incluido el de alcance— así que
   la parte negativa del corpus es deliberadamente más grande que la positiva.
"""

from __future__ import annotations

import pytest

from paper_search import Paper, buscar_y_resumir, detectar_idioma
from paper_search.idioma import (
    CATALAN,
    ESPANOL,
    EUSKERA,
    GALLEGO,
    aviso_de_idioma,
)

# ------------------------------------------------- los cuatro casos positivos


def test_termino_en_espanol_dispara_el_aviso():
    resultado = detectar_idioma("síndrome de Dravet")

    assert resultado.avisa
    assert ESPANOL in resultado.lenguas


def test_termino_en_catalan_dispara_el_aviso():
    resultado = detectar_idioma("malaltia de Huntington")

    assert resultado.avisa
    assert CATALAN in resultado.lenguas


def test_termino_en_euskera_dispara_el_aviso():
    resultado = detectar_idioma("Dravet sindromea")

    assert resultado.avisa
    assert EUSKERA in resultado.lenguas


def test_termino_en_gallego_dispara_el_aviso():
    resultado = detectar_idioma("enfermidade de Huntington")

    assert resultado.avisa
    assert GALLEGO in resultado.lenguas


# --------------------------------------------------------- casos negativos


def test_termino_en_ingles_no_dispara():
    assert not detectar_idioma("Dravet syndrome").avisa
    assert not detectar_idioma("myoclonic epilepsy").avisa
    assert not detectar_idioma("muscular dystrophy").avisa


@pytest.mark.parametrize(
    "gen",
    ["SCN1A", "MECP2", "FBN1", "CACNA1A", "TSC1", "DMD", "COL1A1"],
)
def test_un_nombre_de_gen_nunca_dispara(gen):
    """Lo que más se busca en esta herramienta no puede disparar el aviso."""
    assert not detectar_idioma(gen).avisa


@pytest.mark.parametrize(
    "termino",
    [
        # El euskera es la trampa evidente: 'tz'/'tx' abundan en apellidos
        # centroeuropeos, y un detector estadístico clasifica
        # "Smith-Lemli-Opitz" como euskera con 0.70 de confianza.
        "Opitz",
        "Peutz-Jeghers",
        "Creutzfeldt-Jakob",
        "Smith-Lemli-Opitz",
        "Retzius",
        # Y el español/catalán/gallego lo son por las funcionales romances
        # que lleva el inglés médico estándar.
        "de novo mutations",
        "del 22q11 syndrome",
        "La Crosse encephalitis",
        "El Escorial criteria",
        "torsades de pointes",
    ],
)
def test_nombres_propios_y_locuciones_inglesas_no_disparan(termino):
    resultado = detectar_idioma(termino)

    assert not resultado.avisa, f"falso positivo: {resultado.evidencia}"


def test_las_funcionales_romances_solas_no_bastan():
    """`de`, `del`, `la` refuerzan, no disparan: son inglés médico corriente."""
    assert not detectar_idioma("de novo SCN1A variants").avisa
    # pero sí refuerzan cuando ya hay otra evidencia
    resultado = detectar_idioma("mutaciones de novo")
    assert resultado.avisa
    assert any(e.startswith("refuerzo:") for e in resultado.evidencia)


# ------------------------------------------------------------ término mixto


def test_termino_mixto_gen_mas_espanol_dispara():
    resultado = detectar_idioma("SCN1A síndrome de Dravet")

    assert resultado.avisa
    assert ESPANOL in resultado.lenguas


def test_termino_mixto_ingles_mas_espanol_dispara():
    """El inglés no cancela la evidencia: sigue mereciendo el aviso."""
    assert detectar_idioma("gene therapy terapia génica").avisa
    assert detectar_idioma("Dravet syndrome tratamiento").avisa


# -------------------------------------------------------- forma del aviso


def test_el_aviso_nombra_el_termino_y_sugiere_el_ingles():
    aviso = aviso_de_idioma("síndrome de Dravet")

    assert aviso is not None
    assert "síndrome de Dravet" in aviso
    assert "inglés" in aviso
    # Avisa, no bloquea: debe decir que la búsqueda se ha hecho igualmente.
    assert "igualmente" in aviso


def test_sin_deteccion_no_hay_aviso():
    assert aviso_de_idioma("Dravet syndrome") is None
    assert aviso_de_idioma("SCN1A") is None


def test_el_aviso_no_nombra_una_lengua_concreta():
    """Nombrarla sería acertar por azar: el vocabulario médico se solapa.

    Y decirle «parece estar en español» a quien escribió en euskera es un
    error visible, mientras que el consejo es idéntico en los cuatro casos.
    """
    for termino in ("síndrome de Dravet", "Huntington gaixotasuna",
                    "malaltia rara", "enfermidades raras"):
        aviso = aviso_de_idioma(termino)
        assert aviso is not None
        assert "lengua cooficial" in aviso


def test_la_lengua_detectada_sigue_disponible_en_el_resultado():
    """El aviso no la enseña, pero el dato existe para tests y depuración."""
    assert detectar_idioma("Huntington gaixotasuna").lenguas == (EUSKERA,)


def test_un_termino_castellano_no_se_marca_como_euskera():
    """«sindrome» a secas no es evidencia de euskera: se escribe igual."""
    assert detectar_idioma("síndrome de Dravet").lenguas == (ESPANOL,)


def test_el_termino_vacio_no_revienta():
    assert not detectar_idioma("").avisa
    assert not detectar_idioma("   ").avisa
    assert aviso_de_idioma("") is None


def test_sin_tildes_tambien_se_detecta():
    """Mucha gente escribe sin tildes en un campo de búsqueda."""
    assert detectar_idioma("sindrome de Dravet").avisa
    assert detectar_idioma("epilepsia mioclonica").avisa


# ------------------------------------------------- corpus de regresión

DEBE_AVISAR = [
    # español
    "síndrome de Dravet", "enfermedad de Huntington", "epilepsia mioclónica",
    "convulsiones febriles", "retraso del desarrollo", "esclerosis tuberosa",
    "mutaciones en el gen SCN1A", "tratamiento de la fibrosis quística",
    "miocardiopatía hipertrófica familiar", "displasia broncopulmonar",
    # catalán
    "distròfia muscular", "epilèpsia mioclònica", "convulsions febrils",
    "retard del desenvolupament", "esclerosi tuberosa", "malaltia rara",
    "mutacions en el gen SCN1A", "hipertensió pulmonar primària",
    "immunodeficiència combinada greu", "cardiopatia congènita en nens",
    # euskera
    "Huntington gaixotasuna", "epilepsia miokloniko", "muskulu distrofia",
    "garapen atzerapena", "gaixotasun arraroak", "sukarrezko konbultsioak",
    "gene mutazioak", "bihotzeko gaixotasun kongenitoa",
    "nerbio sistemaren nahasteak", "umeen gaixotasun arraroak",
    "giltzurrun gutxiegitasuna",
    # gallego
    "atraso do desenvolvemento", "enfermidades raras",
    "distrofia muscular conxénita", "converxencia xenética",
    "tratamento da fibrose quística", "cardiopatía conxénita",
    "trastornos do metabolismo", "enfermidade rara hereditaria",
    "insuficiencia renal crónica en nenos",
]

NO_DEBE_AVISAR = [
    # inglés del dominio
    "Dravet syndrome", "myoclonic epilepsy", "muscular dystrophy",
    "developmental delay", "febrile seizures", "tuberous sclerosis",
    "SCN1A gene mutations", "rare disease treatment",
    "Duchenne muscular dystrophy", "spinal muscular atrophy",
    "22q11.2 deletion syndrome", "in vitro fertilization",
    "de novo mutations", "de novo SCN1A variants", "del 22q11 syndrome",
    "La Crosse encephalitis", "El Escorial criteria", "torsades de pointes",
    "tetralogy of Fallot",
    # latín médico, que se usa igual en inglés
    "osteogenesis imperfecta", "epidermolysis bullosa", "situs inversus",
    "cutis laxa",
    # genes y acrónimos
    "SCN1A", "MECP2", "FBN1", "CACNA1A", "TSC1", "DMD",
    # nombres propios de síndromes
    "Dravet", "Rett", "Marfan", "Angelman", "Prader-Willi", "Ehlers-Danlos",
    "Rett syndrome", "Marfan syndrome", "Smith-Lemli-Opitz", "Opitz",
    "Retzius", "Kartagener", "Waardenburg", "Creutzfeldt-Jakob",
    "Wolff-Parkinson-White", "Charcot-Marie-Tooth", "von Hippel-Lindau",
    "Peutz-Jeghers", "Rendu-Osler-Weber", "Schwartz-Jampel",
]


@pytest.mark.parametrize("termino", DEBE_AVISAR)
def test_regresion_terminos_que_deben_avisar(termino):
    assert detectar_idioma(termino).avisa


@pytest.mark.parametrize("termino", NO_DEBE_AVISAR)
def test_regresion_terminos_que_no_deben_avisar(termino):
    resultado = detectar_idioma(termino)

    assert not resultado.avisa, f"falso positivo: {resultado.evidencia}"


def test_ningun_falso_positivo_en_todo_el_corpus():
    """El número que importa: 0 falsos positivos sobre el corpus completo."""
    falsos = [t for t in NO_DEBE_AVISAR if detectar_idioma(t).avisa]

    assert falsos == []


# ------------------------------------------- orquestación (buscar_y_resumir)


class ClientPubMedFalso:
    def __init__(self, papers):
        self.papers = list(papers)
        self.llamadas: list[dict] = []

    def buscar_papers(self, termino, *, max_resultados, dias):
        self.llamadas.append(
            {"termino": termino, "max_resultados": max_resultados, "dias": dias}
        )
        return list(self.papers)


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


def buscar(termino, **kwargs):
    """Búsqueda con todo mockeado: aquí solo interesa el aviso de idioma."""
    pubmed = ClientPubMedFalso(PAPERS)
    resultado = buscar_y_resumir(
        termino,
        resumir=False,          # el resumen tiene sus propios tests
        verificar_alcance=False,  # el alcance también
        client=pubmed,
        **kwargs,
    )
    return resultado, pubmed


def test_el_aviso_no_bloquea_la_busqueda():
    """Igual que el aviso de alcance ambiguo: informa y deja pasar."""
    resultado, pubmed = buscar("síndrome de Dravet")

    assert resultado.aviso_idioma is not None
    # PubMed se llamó, y con el término tal cual: no se traduce nada.
    assert len(pubmed.llamadas) == 1
    assert pubmed.llamadas[0]["termino"] == "síndrome de Dravet"
    assert resultado.total == 1


def test_un_termino_en_ingles_no_trae_aviso():
    resultado, _ = buscar("Dravet syndrome")

    assert resultado.aviso_idioma is None


def test_el_aviso_se_calcula_sin_clave_ni_verificacion_de_alcance():
    """Es local y gratis: no depende de ANTHROPIC_API_KEY ni gasta llamadas."""
    resultado, _ = buscar("enfermidade rara hereditaria")

    assert resultado.aviso_idioma is not None


def test_el_json_del_resultado_incluye_el_aviso_de_idioma():
    resultado, _ = buscar("síndrome de Dravet")

    datos = resultado.to_dict()
    assert "aviso_idioma" in datos
    assert "inglés" in datos["aviso_idioma"]


def test_sin_aviso_el_campo_del_json_es_nulo():
    resultado, _ = buscar("SCN1A")

    assert resultado.to_dict()["aviso_idioma"] is None
