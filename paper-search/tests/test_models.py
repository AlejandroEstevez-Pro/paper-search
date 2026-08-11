"""Tests de las estructuras de datos y del troceado del resumen.

`segmentar_resumen` es lo que permite a la interfaz web resaltar las citas
`[PMID: ...]` sin tocar el texto que escribió el modelo.
"""

from __future__ import annotations

from paper_search import segmentar_resumen


def texto_de(parrafos) -> str:
    """Reconstruye el resumen a partir de los segmentos."""
    return "\n\n".join("".join(seg.texto for seg in parrafo) for parrafo in parrafos)


def test_separa_la_cita_del_texto_que_la_rodea():
    (parrafo,) = segmentar_resumen("Hay 42 variantes nuevas [PMID: 38123456].")

    assert [(s.texto, s.es_cita) for s in parrafo] == [
        ("Hay 42 variantes nuevas ", False),
        ("[PMID: 38123456]", True),
        (".", False),
    ]


def test_reconoce_una_cita_con_varios_pmids():
    (parrafo,) = segmentar_resumen("Dos estudios coinciden [PMID: 38123456, 38999999].")

    citas = [s.texto for s in parrafo if s.es_cita]
    assert citas == ["[PMID: 38123456, 38999999]"]


def test_un_parrafo_por_bloque_separado_por_linea_en_blanco():
    parrafos = segmentar_resumen(
        "Genética\n\nPrimer hallazgo [PMID: 1111111].\n\nSegundo hallazgo [PMID: 2222222]."
    )

    assert len(parrafos) == 3


def test_no_se_pierde_ni_se_altera_nada_del_texto():
    resumen = (
        "Idea general del tema, en dos frases [PMID: 38123456].\n\n"
        "Tratamiento: no hay ensayos concluyentes [PMID: 38999999, 38123456]. "
        "Un artículo no trae abstract."
    )

    assert texto_de(segmentar_resumen(resumen)) == resumen


def test_un_resumen_sin_citas_se_devuelve_entero_como_texto():
    (parrafo,) = segmentar_resumen("Los abstracts no bastan para decir nada con claridad.")

    assert len(parrafo) == 1
    assert parrafo[0].es_cita is False


def test_un_resumen_vacio_no_da_parrafos():
    assert segmentar_resumen("") == ()
    assert segmentar_resumen("\n\n   \n\n") == ()


def test_no_marca_como_cita_un_corchete_que_no_lleva_pmids():
    (parrafo,) = segmentar_resumen("Se citó el trabajo previo [ver PMID: pendiente].")

    assert [s.es_cita for s in parrafo] == [False]
