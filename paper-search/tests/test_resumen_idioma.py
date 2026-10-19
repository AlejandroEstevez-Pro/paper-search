"""El resumen se genera en el idioma activo, con la verificación adaptada.

Lo que se protege aquí, por orden de importancia:

1. Que la **caché no cruce idiomas**. Servir un resumen español a quien pidió
   inglés no es un fallo cosmético: llega sin avisar y pareciendo recién hecho.
2. Que el **verificador use el prompt del idioma del resumen**. Sus reglas
   llevan ejemplos de la lengua («consulte», «you should»), y con los
   equivocados sigue respondiendo pero deja pasar lo que debía frenar.
3. Que el **aviso médico** salga en el idioma correcto y siga siendo
   obligatorio en los dos.
"""

from __future__ import annotations

import json

import pytest

from paper_search import (
    Paper,
    ResultadoBusqueda,
    abrir_db,
    buscar_y_resumir,
    texto_para_notebooklm,
    traducir,
)
from paper_search.cache import CacheResumenes
from paper_search.i18n import IDIOMAS
from paper_search.prompts import (
    CABECERA_CORRECCIONES,
    SISTEMA_RESUMEN,
    SISTEMA_VERIFICACION,
    sistema_resumen,
    sistema_verificacion,
)
from paper_search.summarizer import ResumenError
from paper_search.verificacion import _interpretar_respuesta, resumir_con_verificacion

PAPERS = (
    Paper(
        pmid="38123456",
        titulo="SCN1A variants in Dravet syndrome",
        autores=("Garcia A",),
        revista="Epilepsia",
        fecha="2024-03-15",
        abstract="Cohort of 42 patients.",
        orden_relevancia=0,
    ),
)


# ------------------------------------------------------------------ dobles


class BloqueTexto:
    type = "text"

    def __init__(self, text):
        self.text = text


class RespuestaFalsa:
    def __init__(self, texto):
        self.content = [BloqueTexto(texto)]
        self.stop_reason = "end_turn"
        self.stop_details = None


class MessagesEspia:
    """Guarda el `system` de cada llamada: es lo que se quiere comprobar."""

    def __init__(self, respuesta):
        self._respuesta = respuesta
        self.sistemas: list[str] = []
        self.prompts: list[str] = []

    def create(self, **kwargs):
        self.sistemas.append(kwargs.get("system", ""))
        self.prompts.append(kwargs["messages"][0]["content"])
        return self._respuesta


class ClientEspia:
    def __init__(self, respuesta):
        self.messages = MessagesEspia(respuesta)

    def with_options(self, **kwargs):
        return self


class ClientPubMedFalso:
    def __init__(self, papers=PAPERS):
        self.papers = list(papers)

    def buscar_papers(self, termino, *, max_resultados, dias):
        return list(self.papers)


def summarizer_espia(texto="Hallazgo [PMID: 38123456]."):
    from paper_search.summarizer import Summarizer

    cliente = ClientEspia(RespuestaFalsa(texto))
    return Summarizer(client=cliente), cliente


def buscar(idioma, resumen="Hallazgo [PMID: 38123456].", db=None):
    summarizer, cliente = summarizer_espia(resumen)
    resultado = buscar_y_resumir(
        "SCN1A",
        idioma=idioma,
        verificar_alcance=False,
        verificar_resumen=False,
        client=ClientPubMedFalso(),
        summarizer=summarizer,
        db=db,
    )
    return resultado, cliente


# -------------------------------------- el resumen se pide en el idioma activo


def test_en_espanol_se_usa_el_prompt_espanol():
    _, cliente = buscar("es")

    assert "Escribe en español" in cliente.messages.sistemas[0]


def test_en_ingles_se_usa_el_prompt_ingles():
    _, cliente = buscar("en")

    assert "Write in English" in cliente.messages.sistemas[0]
    assert "Escribe en español" not in cliente.messages.sistemas[0]


def test_el_mismo_termino_pide_prompts_distintos_segun_idioma():
    _, es = buscar("es")
    _, en = buscar("en")

    assert es.messages.sistemas[0] != en.messages.sistemas[0]


def test_un_idioma_desconocido_cae_al_de_referencia():
    _, cliente = buscar("klingon")

    assert "Escribe en español" in cliente.messages.sistemas[0]


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_el_prompt_del_resumen_conserva_las_reglas_en_los_dos(idioma):
    """Las reglas duras no pueden perderse al traducir el prompt."""
    prompt = sistema_resumen(idioma)

    assert "[PMID: 12345678]" in prompt          # el formato de cita
    # Las siete reglas siguen ahí: traducir no puede perder ninguna.
    for numero in range(1, 8):
        assert f"\n{numero}. " in prompt, numero


# --------------------------------------------- la caché no cruza idiomas


@pytest.fixture
def db():
    conn = abrir_db(":memory:")
    yield conn
    conn.close()


def test_la_cache_no_sirve_un_resumen_espanol_a_quien_pide_ingles(db):
    cache = CacheResumenes(db)
    cache.guardar("SCN1A", ["38123456"], "Resumen en español", "modelo", "es")

    assert cache.buscar("SCN1A", ["38123456"], "en") is None
    assert cache.buscar("SCN1A", ["38123456"], "es").resumen == "Resumen en español"


def test_los_dos_idiomas_conviven_en_la_cache(db):
    cache = CacheResumenes(db)
    cache.guardar("SCN1A", ["1"], "Español", "modelo", "es")
    cache.guardar("SCN1A", ["1"], "English", "modelo", "en")

    assert cache.buscar("SCN1A", ["1"], "es").resumen == "Español"
    assert cache.buscar("SCN1A", ["1"], "en").resumen == "English"


def test_guardar_en_un_idioma_no_pisa_el_otro(db):
    cache = CacheResumenes(db)
    cache.guardar("SCN1A", ["1"], "Español", "modelo", "es")
    cache.guardar("SCN1A", ["1"], "English", "modelo", "en")
    cache.guardar("SCN1A", ["1"], "Español v2", "modelo", "es")

    assert cache.buscar("SCN1A", ["1"], "en").resumen == "English"


def test_una_busqueda_en_ingles_no_reutiliza_el_resumen_espanol_cacheado(db):
    """El caso completo, por la puerta de `buscar_y_resumir`."""
    buscar("es", "Resumen español [PMID: 38123456].", db=db)

    resultado, cliente = buscar("en", "English summary [PMID: 38123456].", db=db)

    assert resultado.resumen == "English summary [PMID: 38123456]."
    assert not resultado.desde_cache
    assert cliente.messages.sistemas  # se llamó al modelo, no salió de caché


def test_repetir_la_busqueda_en_el_mismo_idioma_si_usa_la_cache(db):
    """Se ceba la caché a mano: `buscar_y_resumir` solo escribe en ella los
    resúmenes que pasaron la verificación, y aquí está desactivada."""
    CacheResumenes(db).guardar(
        "SCN1A", ["38123456"], "English summary [PMID: 38123456].", "modelo", "en"
    )

    resultado, cliente = buscar("en", "no debería llamarse", db=db)

    assert resultado.desde_cache
    assert resultado.resumen == "English summary [PMID: 38123456]."
    assert cliente.messages.sistemas == []  # ni una llamada


def test_esa_misma_cache_no_responde_al_otro_idioma(db):
    """La otra mitad: cebada en inglés, una búsqueda en español no la usa."""
    CacheResumenes(db).guardar(
        "SCN1A", ["38123456"], "English summary [PMID: 38123456].", "modelo", "en"
    )

    resultado, cliente = buscar("es", "Resumen español [PMID: 38123456].", db=db)

    assert not resultado.desde_cache
    assert resultado.resumen == "Resumen español [PMID: 38123456]."
    assert cliente.messages.sistemas  # sí hubo llamada


def test_lo_ya_cacheado_antes_de_la_v3_cuenta_como_espanol(db):
    """La migración marca `es` lo que había, y no es una suposición: se generó
    con el prompt español, que era el único que existía."""
    filas = db.execute(
        "SELECT COUNT(*) AS n FROM resumenes_cache WHERE idioma <> 'es'"
    ).fetchone()

    assert filas["n"] == 0  # una BD nueva no trae nada raro
    columnas = {f["name"] for f in db.execute("PRAGMA table_info(resumenes_cache)")}
    assert "idioma" in columnas


def test_la_tabla_vieja_se_conserva_intacta(db):
    """La v3 no destruye nada: deja la anterior como `resumenes_cache_legacy`."""
    tablas = {
        f["name"] for f in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert "resumenes_cache_legacy" in tablas


def test_la_clave_ajena_de_acciones_sigue_apuntando_a_la_tabla_viva(db):
    """Si la v3 hubiera dejado la FK apuntando a la tabla vieja, CUALQUIER
    búsqueda que tocara la caché fallaría al escribir el registro."""
    from paper_search.registro import RESULTADO_EXITO, RegistroAcciones

    cache_id = CacheResumenes(db).guardar("SCN1A", ["1"], "x", "modelo", "en")

    RegistroAcciones(db).registrar(
        termino="SCN1A", resultado=RESULTADO_EXITO, cache_id=cache_id
    )  # no debe lanzar


# ------------------------------ la verificación se adapta al idioma del resumen


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_el_verificador_declara_las_dos_reglas_en_ambos_idiomas(idioma):
    """Traducir el prompt no puede perder ninguna de las dos reglas."""
    prompt = sistema_verificacion(idioma)

    assert "PMID" in prompt
    assert "\n1." in prompt and "\n2." in prompt


def test_el_verificador_espanol_busca_patrones_de_espanol():
    prompt = sistema_verificacion("es")

    assert "consulte" in prompt
    assert "se recomienda" in prompt


def test_el_verificador_ingles_busca_patrones_de_ingles():
    """El motivo de traducirlo: «consulte» no aparece en un texto inglés, y
    con los ejemplos equivocados el guardarraíl deja pasar el consejo médico."""
    prompt = sistema_verificacion("en")

    assert "you should" in prompt.lower()
    assert "consult your doctor" in prompt.lower()
    assert "consulte" not in prompt


def test_el_verificador_dice_en_que_idioma_viene_el_resumen():
    assert "EN ESPAÑOL" in sistema_verificacion("es")
    assert "IN ENGLISH" in sistema_verificacion("en")


def test_el_verificador_recibe_el_prompt_del_idioma_del_resumen():
    """La comprobación de extremo a extremo: lo que llega a la API."""
    from paper_search.verificacion import VerificadorResumen

    cliente = ClientEspia(RespuestaFalsa('{"aprobado": true, "problemas": []}'))
    VerificadorResumen(client=cliente).verificar("Summary", ["1"], idioma="en")

    assert "IN ENGLISH" in cliente.messages.sistemas[0]


def test_el_feedback_de_regeneracion_va_en_el_idioma_del_resumen():
    """Va dentro del prompt del resumidor: en español pidiéndole corregir un
    texto inglés sería el mismo desajuste que se acaba de arreglar."""
    from paper_search.verificacion import Problema, _formatear_correcciones

    problemas = [Problema(tipo="consejo_medico", fragmento="x", detalle="y")]

    assert "verificador automático" in _formatear_correcciones(problemas, "es")
    assert "automatic checker" in _formatear_correcciones(problemas, "en")


# ---------------- el rechazo de consejo médico funciona igual en los dos idiomas


CONSEJO_EN = (
    "SCN1A variants cause Dravet syndrome [PMID: 38123456]. "
    "You should consult your doctor before stopping sodium channel blockers."
)
CONSEJO_ES = (
    "Las variantes de SCN1A causan el síndrome de Dravet [PMID: 38123456]. "
    "Consulte a su médico antes de retirar los bloqueantes de canales de sodio."
)

RECHAZO_EN = json.dumps(
    {
        "aprobado": False,
        "problemas": [
            {
                "tipo": "consejo_medico",
                "fragmento": "You should consult your doctor",
                "detalle": "advice aimed at the reader",
            }
        ],
    }
)


class VerificadorGuionizado:
    """Verificador con respuestas prefijadas, una por intento."""

    def __init__(self, *respuestas):
        self._respuestas = list(respuestas)
        self.idiomas: list[str] = []

    def verificar(self, resumen, pmids, *, idioma=None, contador=None):
        self.idiomas.append(idioma)
        return _interpretar_respuesta(RespuestaFalsa(self._respuestas.pop(0)))


@pytest.mark.parametrize(
    ("idioma", "consejo"), [("es", CONSEJO_ES), ("en", CONSEJO_EN)]
)
def test_un_resumen_con_consejo_medico_no_se_entrega(idioma, consejo):
    """El requisito de fondo, en los dos idiomas: rechazado es rechazado.

    Se guioniza el veredicto porque lo que se protege aquí es el bucle, no el
    criterio del modelo; que el prompt inglés busque los patrones ingleses está
    cubierto por los tests de arriba.
    """
    summarizer, _ = summarizer_espia(consejo)
    verificador = VerificadorGuionizado(RECHAZO_EN, RECHAZO_EN, RECHAZO_EN)

    with pytest.raises(ResumenError) as excinfo:
        resumir_con_verificacion(
            "SCN1A",
            PAPERS,
            summarizer=summarizer,
            verificador=verificador,
            idioma=idioma,
        )

    assert "consejo_medico" in str(excinfo.value)
    assert verificador.idiomas == [idioma] * 3  # el verificador supo el idioma


def test_al_regenerar_en_ingles_el_feedback_llega_en_ingles():
    """Si el consejo se caza al primer intento, la corrección que se le pide al
    resumidor tiene que ir en su idioma o el segundo intento sale mestizo."""
    summarizer, cliente = summarizer_espia(CONSEJO_EN)
    verificador = VerificadorGuionizado(
        RECHAZO_EN, json.dumps({"aprobado": True, "problemas": []})
    )

    resumen = resumir_con_verificacion(
        "SCN1A",
        PAPERS,
        summarizer=summarizer,
        verificador=verificador,
        idioma="en",
    )

    assert resumen == CONSEJO_EN
    segundo_prompt = cliente.messages.prompts[1]
    assert "An automatic checker rejected" in segundo_prompt
    assert "verificador automático" not in segundo_prompt


# ------------------- lo compartido NO se duplica (anclaje anti-desincronización)


def test_los_dos_idiomas_declaran_los_mismos_prompts():
    for tabla in (SISTEMA_RESUMEN, SISTEMA_VERIFICACION, CABECERA_CORRECCIONES):
        assert set(tabla) == set(IDIOMAS)


def test_los_codigos_de_problema_no_dependen_del_idioma():
    """Es el anclaje: el prompt cambia de lengua, pero los códigos con los que
    responde el modelo son los mismos, y por ahí no pueden divergir."""
    from paper_search.verificacion import ESQUEMA_RESPUESTA, TIPOS_DEL_MODELO

    enum = ESQUEMA_RESPUESTA["properties"]["problemas"]["items"]["properties"]["tipo"]

    assert enum["enum"] == list(TIPOS_DEL_MODELO)
    assert TIPOS_DEL_MODELO == ("afirmacion_sin_pmid", "consejo_medico")


def test_la_comprobacion_determinista_no_depende_del_idioma():
    """Los PMIDs se comprueban en código, igual en los dos idiomas."""
    from paper_search.verificacion import problemas_deterministas

    for resumen in ("Hallazgo [PMID: 999].", "Finding [PMID: 999]."):
        problemas = problemas_deterministas(resumen, ["111"])
        assert [p.tipo for p in problemas] == ["pmid_desconocido"]


def test_los_prompts_no_viven_en_la_fuente_de_traduccion():
    """`i18n/*.json` se compila al messages.json de la extensión de Chrome: un
    prompt ahí acabaría empaquetado y en manos de quien traduzca la interfaz."""
    from paper_search.i18n import claves_disponibles

    for clave in claves_disponibles():
        assert not clave.startswith("prompt_")
    assert "Escribe en español y en lenguaje llano" not in str(
        [traducir(c, "es") for c in claves_disponibles()]
    )


# ------------------------------------------------- disclaimer en ambos idiomas


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_el_resultado_trae_el_aviso_medico_traducido(idioma):
    resultado, _ = buscar(idioma)

    assert resultado.aviso == traducir("comun_aviso_no_diagnostico", idioma)
    assert resultado.aviso.strip()


def test_el_aviso_medico_es_distinto_en_cada_idioma():
    es, _ = buscar("es")
    en, _ = buscar("en")

    assert es.aviso != en.aviso
    assert "no es una herramienta de diagnóstico" in es.aviso.lower()
    assert "not a diagnostic tool" in en.aviso.lower()


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_el_aviso_medico_sigue_siendo_obligatorio(idioma):
    """En los dos idiomas y pase lo que pase: también sin resumen."""
    resultado = ResultadoBusqueda(
        query="SCN1A",
        papers=PAPERS,
        dias=365,
        error_resumen="la API falló",
        aviso=traducir("comun_aviso_no_diagnostico", idioma),
    )

    texto = texto_para_notebooklm(resultado, idioma)

    assert traducir("comun_aviso_no_diagnostico", idioma) in texto


# ------------------------------------------------------------- exportación


def test_el_texto_exportado_sale_entero_en_ingles():
    """Antes el andamiaje iba fijo en español y el disclaimer también: con un
    resumen inglés dentro salía un documento mestizo."""
    resultado, _ = buscar("en", "English summary [PMID: 38123456].")

    texto = texto_para_notebooklm(resultado, "en")

    assert "PUBMED SEARCH" in texto
    assert "SUMMARY" in texto
    assert "REFERENCES" in texto
    assert "NOTICE" in texto
    assert "not a diagnostic tool" in texto.lower()
    for espanol in ("BÚSQUEDA EN PUBMED", "RESUMEN", "REFERENCIAS", "Término:"):
        assert espanol not in texto


def test_el_texto_exportado_en_espanol_no_cambia():
    """No-regresión: en español el documento sigue siendo el de siempre."""
    resultado, _ = buscar("es", "Resumen español [PMID: 38123456].")

    texto = texto_para_notebooklm(resultado, "es")

    assert "BÚSQUEDA EN PUBMED — paper-search" in texto
    assert "RESUMEN" in texto
    assert "REFERENCIAS (1)" in texto
    assert "AVISO" in texto
    assert "Término: SCN1A" in texto


def test_las_citas_del_texto_exportado_siguen_en_texto_plano():
    resultado, _ = buscar("en", "English summary [PMID: 38123456].")

    texto = texto_para_notebooklm(resultado, "en")

    assert "[PMID: 38123456]" in texto
    assert "<a " not in texto
