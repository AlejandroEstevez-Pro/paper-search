"""Tests del módulo de traducción y de la integridad de la fuente.

Buena parte de estos tests no prueban código sino los **datos**: que las dos
lenguas tengan las mismas claves, que ninguna clave rompa las reglas de
`chrome.i18n` y que los placeholders declarados y los usados coincidan. Son los
que evitan que la fuente y el generador de la Tarea 3 se separen sin avisar.
"""

from __future__ import annotations

import json

import pytest

from paper_search import i18n as mod
from paper_search.i18n import (
    IDIOMA_REFERENCIA,
    IDIOMAS,
    PATRON_CLAVE,
    PATRON_PLACEHOLDER,
    cargar_idioma,
    cargar_meta,
    claves_disponibles,
    normalizar_idioma,
    placeholders_de,
    sustituir,
    traducir,
)


# ------------------------------------------------------ integridad de la fuente


def test_el_idioma_de_referencia_existe_y_no_esta_vacio():
    assert len(cargar_idioma(IDIOMA_REFERENCIA)) > 50


def test_todos_los_idiomas_tienen_exactamente_las_mismas_claves():
    """Una clave de más o de menos en un idioma es una traducción a medias."""
    referencia = claves_disponibles(IDIOMA_REFERENCIA)
    for idioma in IDIOMAS:
        faltan = referencia - claves_disponibles(idioma)
        sobran = claves_disponibles(idioma) - referencia
        assert not faltan, f"{idioma}.json: faltan {sorted(faltan)}"
        assert not sobran, f"{idioma}.json: sobran {sorted(sobran)}"


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_ninguna_traduccion_esta_vacia(idioma):
    vacias = [c for c, t in cargar_idioma(idioma).items() if not t.strip()]

    assert vacias == []


def test_las_claves_son_validas_para_chrome_i18n():
    """chrome.i18n solo admite letras, números y `_`: nada de puntos.

    Es la razón de que el esquema use snake_case y no `area.clave`: así la
    clave viaja igual a los dos formatos, sin transformación que pueda
    colisionar.
    """
    invalidas = [c for c in claves_disponibles() if not PATRON_CLAVE.match(c)]

    assert invalidas == []


def test_ninguna_clave_usa_el_prefijo_reservado_de_chrome():
    """`@@` está reservado para los mensajes predefinidos de la extensión."""
    assert [c for c in claves_disponibles() if c.startswith("@@")] == []


def test_toda_clave_lleva_un_prefijo_de_area_conocido():
    areas = ("app_", "comun_", "nav_", "form_", "err_", "res_", "fil_",
             "ord_", "exp_", "fav_", "alc_", "idi_", "off_")
    sin_area = [c for c in claves_disponibles() if not c.startswith(areas)]

    assert sin_area == []


# ---------------------------------------------------------------- placeholders


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_los_placeholders_usados_estan_declarados_en_meta(idioma):
    """Un `$algo$` sin declarar no llegaría a chrome.i18n: se vería literal."""
    problemas = []
    for clave, texto in cargar_idioma(idioma).items():
        usados = set(PATRON_PLACEHOLDER.findall(texto))
        declarados = set(placeholders_de(clave))
        if usados - declarados:
            problemas.append((clave, sorted(usados - declarados)))

    assert problemas == []


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_los_placeholders_declarados_se_usan_de_verdad(idioma):
    """El sentido contrario: declarar de más también es una incoherencia."""
    problemas = []
    for clave, texto in cargar_idioma(idioma).items():
        usados = set(PATRON_PLACEHOLDER.findall(texto))
        declarados = set(placeholders_de(clave))
        if declarados - usados:
            problemas.append((clave, sorted(declarados - usados)))

    assert problemas == []


def test_las_dos_lenguas_usan_los_mismos_placeholders_por_clave():
    """Si el inglés olvida un `$termino$`, el dato desaparece de la pantalla."""
    problemas = []
    for clave in claves_disponibles():
        conjuntos = {
            idioma: set(PATRON_PLACEHOLDER.findall(cargar_idioma(idioma)[clave]))
            for idioma in IDIOMAS
        }
        if len(set(map(frozenset, conjuntos.values()))) > 1:
            problemas.append((clave, conjuntos))

    assert problemas == []


def test_meta_no_declara_claves_que_no_existen():
    huerfanas = [
        c for c in cargar_meta()
        if not c.startswith("_") and c not in claves_disponibles()
    ]

    assert huerfanas == []


# ------------------------------------------------------------- sustitución


def test_sustituir_cambia_los_placeholders():
    assert sustituir("Hola $nombre$", {"nombre": "Ana"}) == "Hola Ana"


def test_sustituir_admite_varios_y_repetidos():
    texto = sustituir("$a$ y $b$ y otra vez $a$", {"a": "1", "b": "2"})

    assert texto == "1 y 2 y otra vez 1"


def test_un_placeholder_sin_valor_se_queda_visible():
    """Visible se ve y se corrige; vaciarlo escondería el fallo."""
    assert sustituir("Hola $nombre$", {}) == "Hola $nombre$"


def test_sustituir_no_toca_un_dolar_suelto():
    assert sustituir("Cuesta 5$ o 6$", {}) == "Cuesta 5$ o 6$"


def test_los_valores_no_se_reinterpretan_como_placeholders():
    """Un valor que contenga `$x$` no debe expandirse otra vez."""
    texto = sustituir("Buscaste $termino$", {"termino": "$otro$"})

    assert texto == "Buscaste $otro$"


# ----------------------------------------------------------------- traducir


def test_traducir_devuelve_el_texto_del_idioma_pedido():
    assert traducir("form_boton_buscar", "es") == "Buscar"
    assert traducir("form_boton_buscar", "en") == "Search"


def test_el_idioma_por_defecto_es_el_de_referencia():
    assert traducir("form_boton_buscar") == traducir("form_boton_buscar", "es")


def test_traducir_pone_los_placeholders():
    texto = traducir("fil_contador", "es", visibles=2, total=15)

    assert texto == "2 de 15 resultados mostrados"


def test_traducir_pone_los_placeholders_en_ingles():
    assert traducir("fil_contador", "en", visibles=2, total=15) == "2 of 15 results shown"


# ------------------------------------------------------------------ fallback


def test_una_clave_que_falta_en_un_idioma_cae_al_de_referencia(monkeypatch):
    """Fallback documentado: idioma pedido → es → la propia clave.

    Se sustituye el cargador entero en vez de mutar el diccionario cacheado:
    tocarlo dejaría el estado sucio para el resto de la suite.
    """
    fuentes = {
        "es": {"clave_de_prueba": "solo en español", "otra": "hay en ambas"},
        "en": {"otra": "in both"},  # `clave_de_prueba` NO está traducida
    }
    monkeypatch.setattr(mod, "cargar_idioma", lambda idioma: fuentes.get(idioma, {}))

    assert traducir("clave_de_prueba", "en") == "solo en español"
    assert traducir("otra", "en") == "in both"


def test_el_fallback_tambien_pone_los_placeholders(monkeypatch):
    fuentes = {"es": {"saludo": "Hola $nombre$"}, "en": {}}
    monkeypatch.setattr(mod, "cargar_idioma", lambda idioma: fuentes.get(idioma, {}))

    assert traducir("saludo", "en", nombre="Ana") == "Hola Ana"


def test_una_clave_inexistente_devuelve_la_clave_y_no_revienta():
    """Se ve en pantalla qué falta y dónde, en vez de un hueco mudo."""
    assert traducir("no_existe_esta_clave", "es") == "no_existe_esta_clave"
    assert traducir("no_existe_esta_clave", "en") == "no_existe_esta_clave"


def test_un_idioma_desconocido_cae_al_de_referencia():
    assert traducir("form_boton_buscar", "klingon") == "Buscar"


def test_traducir_nunca_lanza_con_entradas_raras():
    for idioma in (None, "", "  ", "xx", "es-ES", "EN", "en_GB", 123):
        assert isinstance(traducir("form_boton_buscar", idioma), str)


# -------------------------------------------------------- normalizar_idioma


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("es", "es"), ("en", "en"), ("ES", "es"), ("  en  ", "en"),
        ("es-ES", "es"), ("en-GB", "en"), ("en_US", "en"),
        (None, "es"), ("", "es"), ("fr", "es"), ("klingon", "es"),
    ],
)
def test_normalizar_idioma(entrada, esperado):
    assert normalizar_idioma(entrada) == esperado


# --------------------------------------------------- la fuente es JSON válido


@pytest.mark.parametrize("nombre", [f"{i}.json" for i in IDIOMAS] + ["meta.json"])
def test_los_archivos_de_la_fuente_son_json_valido_y_utf8(nombre):
    ruta = mod.RUTA_I18N / nombre

    datos = json.loads(ruta.read_text(encoding="utf-8"))

    assert isinstance(datos, dict)
