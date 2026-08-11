"""Tests del generador de `_locales/<idioma>/messages.json` (chrome.i18n).

Lo que se protege: que lo generado sea JSON válido, que tenga **exactamente**
las mismas claves que la fuente, y que el `message` sea el texto de la fuente
sin tocar. Si el generador empezara a reescribir textos, dejaría de haber una
sola fuente de traducción, que es justo lo que se quiso evitar.
"""

from __future__ import annotations

import json

import pytest

from paper_search import locales as mod_locales
from paper_search.i18n import (
    IDIOMA_REFERENCIA,
    IDIOMAS,
    PATRON_CLAVE,
    cargar_idioma,
    claves_disponibles,
    placeholders_de,
)
from paper_search.locales import (
    GeneracionError,
    comprobar_al_dia,
    escribir_locales,
    generar_messages,
    mensaje_chrome,
)


# ------------------------------------------------------- forma de la salida


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_lo_generado_es_json_valido(idioma, tmp_path):
    escribir_locales(tmp_path, (idioma,))

    ruta = tmp_path / idioma / "messages.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))

    assert isinstance(datos, dict)
    assert datos


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_tiene_las_mismas_claves_que_la_fuente(idioma):
    """El requisito explícito de la tarea."""
    generado = set(generar_messages(idioma))

    assert generado == claves_disponibles(IDIOMA_REFERENCIA)


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_cada_entrada_tiene_message_no_vacio(idioma):
    vacias = [c for c, e in generar_messages(idioma).items() if not e["message"].strip()]

    assert vacias == []


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_el_message_es_el_texto_de_la_fuente_sin_tocar(idioma):
    """Nada de reescribir textos: `message` es literalmente la fuente."""
    fuente = cargar_idioma(idioma)
    generado = generar_messages(idioma)

    for clave, texto in fuente.items():
        assert generado[clave]["message"] == texto


def test_las_claves_generadas_valen_para_chrome_i18n():
    invalidas = [c for c in generar_messages("es") if not PATRON_CLAVE.match(c)]

    assert invalidas == []


# ---------------------------------------------------------- placeholders


def test_los_placeholders_se_mapean_a_posiciones_en_el_orden_declarado():
    entrada = mensaje_chrome("fil_contador", "$visibles$ de $total$ mostrados")

    assert entrada["placeholders"] == {
        "visibles": {"content": "$1"},
        "total": {"content": "$2"},
    }


def test_el_orden_sale_de_meta_y_no_del_orden_del_texto():
    """Una traducción que reordene los placeholders no debe desplazar el mapeo.

    `meta.json` declara ["visibles", "total"]; aquí el texto los pone al revés
    y el mapeo posicional tiene que seguir siendo el mismo.
    """
    assert placeholders_de("fil_contador") == ("visibles", "total")

    entrada = mensaje_chrome("fil_contador", "Showing $total$ minus $visibles$")

    assert entrada["placeholders"]["visibles"] == {"content": "$1"}
    assert entrada["placeholders"]["total"] == {"content": "$2"}


def test_una_clave_sin_placeholders_no_lleva_el_bloque():
    entrada = mensaje_chrome("form_boton_buscar", "Buscar")

    assert "placeholders" not in entrada


def test_un_placeholder_sin_declarar_es_un_error_explicito():
    """Sin declarar, chrome.i18n lo enseñaría literal: mejor fallar al generar."""
    with pytest.raises(GeneracionError) as excinfo:
        mensaje_chrome("form_boton_buscar", "Hola $inventado$")

    assert "inventado" in str(excinfo.value)
    assert "meta.json" in str(excinfo.value)


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_todo_placeholder_del_texto_esta_en_el_bloque(idioma):
    import re

    for clave, entrada in generar_messages(idioma).items():
        usados = set(re.findall(r"\$([a-z][a-z0-9_]*)\$", entrada["message"]))
        declarados = set(entrada.get("placeholders", {}))
        assert usados <= declarados, f"{clave}: faltan {sorted(usados - declarados)}"


def test_una_clave_invalida_para_chrome_es_un_error():
    with pytest.raises(GeneracionError) as excinfo:
        mensaje_chrome("form.boton", "Buscar")

    assert "chrome.i18n" in str(excinfo.value)


# -------------------------------------------------------------- descripción


def test_la_descripcion_de_meta_llega_a_messages_json():
    entrada = generar_messages("es")["alc_aviso_ambiguo"]

    assert "description" in entrada
    assert "clasificador" in entrada["description"]


def test_sin_descripcion_no_se_escribe_el_campo():
    entrada = mensaje_chrome("app_nombre", "paper-search")

    assert "description" not in entrada


# ---------------------------------------- un idioma incompleto se completa


def test_un_idioma_incompleto_se_rellena_con_el_de_referencia(monkeypatch):
    """La extensión no debe quedarse con huecos: mismo fallback que la web."""
    completo = {"a_uno": "uno", "a_dos": "dos"}
    incompleto = {"a_uno": "one"}
    # Se parchea donde se USA (locales), no donde se define: locales.py
    # importó el nombre, así que tocar i18n.cargar_idioma no le afectaría.
    monkeypatch.setattr(
        mod_locales, "cargar_idioma", lambda i: incompleto if i == "en" else completo
    )

    generado = generar_messages("en")

    assert set(generado) == {"a_uno", "a_dos"}
    assert generado["a_uno"]["message"] == "one"
    assert generado["a_dos"]["message"] == "dos"  # sin traducir, cae al español


def test_sin_fuente_de_referencia_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.setattr(mod_locales, "cargar_idioma", lambda i: {})

    with pytest.raises(GeneracionError):
        generar_messages("es")


# -------------------------------------------------------------- escritura


def test_escribe_un_archivo_por_idioma(tmp_path):
    escritos = escribir_locales(tmp_path)

    assert len(escritos) == len(IDIOMAS)
    for idioma in IDIOMAS:
        assert (tmp_path / idioma / "messages.json").is_file()


def test_la_estructura_de_carpetas_es_la_que_espera_chrome(tmp_path):
    escribir_locales(tmp_path)

    # _locales/<idioma>/messages.json, exactamente.
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(IDIOMAS)
    assert (tmp_path / "es" / "messages.json").exists()


def test_el_archivo_es_utf8_y_no_escapa_los_acentos(tmp_path):
    escribir_locales(tmp_path, ("es",))

    crudo = (tmp_path / "es" / "messages.json").read_text(encoding="utf-8")

    assert "síndrome" in crudo or "término" in crudo
    assert "\\u00e9" not in crudo


def test_generar_dos_veces_da_exactamente_lo_mismo(tmp_path):
    """Determinista: si no cambia la fuente, no cambia el diff."""
    escribir_locales(tmp_path)
    primero = (tmp_path / "es" / "messages.json").read_text(encoding="utf-8")
    escribir_locales(tmp_path)
    segundo = (tmp_path / "es" / "messages.json").read_text(encoding="utf-8")

    assert primero == segundo


# ---------------------------------------------------------- comprobar_al_dia


def test_comprobar_dice_que_esta_al_dia_tras_generar(tmp_path):
    escribir_locales(tmp_path)

    assert comprobar_al_dia(tmp_path) == []


def test_comprobar_detecta_que_falta_el_archivo(tmp_path):
    assert set(comprobar_al_dia(tmp_path)) == set(IDIOMAS)


def test_comprobar_detecta_un_archivo_desfasado(tmp_path):
    escribir_locales(tmp_path)
    (tmp_path / "en" / "messages.json").write_text("{}", encoding="utf-8")

    assert comprobar_al_dia(tmp_path) == ["en"]


def test_los_locales_del_repo_estan_al_dia():
    """Si alguien edita i18n/*.json y no regenera, este test lo dice."""
    desfasados = comprobar_al_dia()

    assert desfasados == [], (
        f"Ejecuta `python herramientas/generar_locales.py`: {desfasados}"
    )
