"""paper-search — busca en PubMed y resume hallazgos recientes con trazabilidad.

API pública del paquete:

    from paper_search import buscar_y_resumir
    resultado = buscar_y_resumir("SCN1A", max_resultados=10, dias=365)
    print(resultado.resumen)
    for paper in resultado.papers:
        print(paper.pmid, paper.titulo)

No es una herramienta de diagnóstico ni de asesoramiento médico: es una ayuda
de búsqueda y síntesis bibliográfica, y cada afirmación del resumen se puede
rastrear hasta un PMID concreto.
"""

from __future__ import annotations

import sqlite3

from .alcance import (
    TerminoFueraDeAlcanceError,
    VeredictoAlcance,
    VerificadorAlcance,
    veredicto_sin_sujeto,
)
from .busqueda import (
    Criterios,
    CriteriosVaciosError,
    construir_consulta,
    filtrar_papers,
    sujeto_de_alcance,
)
from .cache import CacheResumenes, CacheVeredictos, ResumenCacheado
from .config import RUTA_ENV, cargar_env
from .db import BaseDatosError, abrir_db, ruta_db_por_defecto
from .exportar import texto_para_notebooklm
from .favoritos import Favorito, FavoritoError, Favoritos
from .i18n import (
    IDIOMA_REFERENCIA,
    IDIOMAS,
    cargar_idioma,
    normalizar_idioma,
    traducir,
)
from .idioma import ResultadoIdioma, aviso_de_idioma, detectar_idioma
from .limites import LimiteAlcanzadoError, LimitesUso
from .orden import (
    ORDEN_FECHA,
    ORDEN_POR_DEFECTO,
    ORDEN_RELEVANCIA,
    ORDENES,
    OrdenDesconocidoError,
    clave_fecha,
    normalizar_orden,
    ordenar_papers,
)
from .registro import (
    RESULTADO_BLOQUEADA_ALCANCE,
    RESULTADO_BLOQUEADA_LIMITE,
    RESULTADO_ERROR_PUBMED,
    RESULTADO_ERROR_RESUMEN,
    RESULTADO_EXITO,
    RESULTADO_SIN_RESULTADOS,
    RegistroAcciones,
)
from .models import (
    AVISO_NO_DIAGNOSTICO,
    Paper,
    PaperSearchError,
    ParteCita,
    ResultadoBusqueda,
    Segmento,
    plegar_texto,
    segmentar_resumen,
    url_de_pmid,
)
from .pubmed_client import (
    MENSAJE_FALTA_EMAIL,
    FaltaEmailNCBIError,
    PubMedClient,
    PubMedError,
    RateLimiter,
    RespuestaInvalidaError,
)
from .summarizer import (
    MENSAJE_FALTA_API_KEY,
    FaltaAPIKeyError,
    ResumenError,
    Summarizer,
)
from .verificacion import (
    Problema,
    VerificadorResumen,
    resumir_con_verificacion,
)

__all__ = [
    "AVISO_NO_DIAGNOSTICO",
    "RUTA_ENV",
    "BaseDatosError",
    "CacheResumenes",
    "CacheVeredictos",
    "Criterios",
    "CriteriosVaciosError",
    "FaltaAPIKeyError",
    "FaltaEmailNCBIError",
    "Favorito",
    "FavoritoError",
    "Favoritos",
    "LimiteAlcanzadoError",
    "LimitesUso",
    "IDIOMAS",
    "IDIOMA_REFERENCIA",
    "MENSAJE_FALTA_API_KEY",
    "MENSAJE_FALTA_EMAIL",
    "ORDENES",
    "ORDEN_FECHA",
    "ORDEN_POR_DEFECTO",
    "ORDEN_RELEVANCIA",
    "OrdenDesconocidoError",
    "Paper",
    "PaperSearchError",
    "ParteCita",
    "Problema",
    "PubMedClient",
    "PubMedError",
    "RateLimiter",
    "RegistroAcciones",
    "RespuestaInvalidaError",
    "ResultadoBusqueda",
    "ResultadoIdioma",
    "ResumenCacheado",
    "ResumenError",
    "Segmento",
    "Summarizer",
    "TerminoFueraDeAlcanceError",
    "VeredictoAlcance",
    "VerificadorAlcance",
    "VerificadorResumen",
    "abrir_db",
    "aviso_de_idioma",
    "buscar_y_resumir",
    "cargar_env",
    "cargar_idioma",
    "clave_fecha",
    "construir_consulta",
    "detectar_idioma",
    "filtrar_papers",
    "normalizar_idioma",
    "normalizar_orden",
    "ordenar_papers",
    "plegar_texto",
    "resumir_con_verificacion",
    "ruta_db_por_defecto",
    "segmentar_resumen",
    "sujeto_de_alcance",
    "texto_para_notebooklm",
    "traducir",
    "url_de_pmid",
]

__version__ = "0.1.0"

MAX_RESULTADOS_POR_DEFECTO = 15
DIAS_POR_DEFECTO = 730


def buscar_y_resumir(
    termino: str = "",
    *,
    autor: str | None = None,
    patogeno: str | None = None,
    max_resultados: int = MAX_RESULTADOS_POR_DEFECTO,
    dias: int = DIAS_POR_DEFECTO,
    orden: str = ORDEN_POR_DEFECTO,
    idioma: str = IDIOMA_REFERENCIA,
    resumir: bool = True,
    verificar_alcance: bool = True,
    verificar_resumen: bool = True,
    db: sqlite3.Connection | None = None,
    forzar: bool = False,
    client: PubMedClient | None = None,
    summarizer: Summarizer | None = None,
    verificador_alcance: VerificadorAlcance | None = None,
    verificador_resumen: VerificadorResumen | None = None,
    limites: LimitesUso | None = None,
) -> ResultadoBusqueda:
    """Busca en PubMed y devuelve los papers con su resumen en lenguaje llano.

    Antes de tocar PubMed, un guardarraíl comprueba que el término es plausible
    dentro del alcance de la herramienta (enfermedades raras). Un término fuera
    de alcance lanza `TerminoFueraDeAlcanceError` sin hacer ninguna búsqueda;
    un término ambiguo, o una verificación que no se pudo completar, dejan
    pasar la búsqueda con el aviso en `aviso_alcance` (fail-open, ver
    docs/decisions.md).

    Si el término parece escrito en español, catalán, euskera o gallego, se
    devuelve además un aviso en `aviso_idioma` sugiriendo reescribirlo en
    inglés (PubMed indexa sobre todo en inglés). La detección es local y no
    gasta llamadas; nunca traduce el término ni bloquea la búsqueda.

    El resumen generado pasa además una verificación automática (trazabilidad
    de PMIDs y ausencia de consejo médico, ver `verificacion.py`): un resumen
    rechazado se regenera con feedback hasta `MAX_INTENTOS`, y un fallo técnico
    de la verificación cuenta como intento fallido (fail-closed). Si no la
    supera, se descarta con el motivo en `error_resumen`: nunca se entrega un
    resumen sin verificar.

    Con una conexión en `db` (ver `abrir_db`), los veredictos de alcance y los
    resúmenes verificados se sirven desde la caché local cuando existen y no
    han caducado; `forzar=True` ignora ambas cachés y regenera. Un resumen
    servido desde caché llega con `desde_cache=True` y su fecha original en
    `cache_creado_en`. La misma conexión activa los límites diarios de uso
    (`limites.py`): si están agotados se lanza `LimiteAlcanzadoError` antes de
    tocar ninguna API. Cada búsqueda — también las bloqueadas y las fallidas —
    queda anotada en el registro de acciones (`registro.py`). Sin `db` (uso
    como librería pura) no hay caché, límites ni persistencia de ningún tipo.

    Sin `NCBI_EMAIL` se lanza `FaltaEmailNCBIError` antes de hacer NADA: ni
    se cuenta la búsqueda en los límites ni se gasta la llamada del filtro de
    alcance en una búsqueda que no podría llegar a PubMed.

    Los fallos de PubMed se propagan como `PubMedError`: sin datos reales no
    hay resultado que devolver. En cambio, un fallo al generar el resumen (por
    ejemplo, falta `ANTHROPIC_API_KEY`) no descarta los papers ya obtenidos:
    se devuelven con `resumen=None` y el motivo en `error_resumen`, para que
    quien llama decida cómo presentarlo. Nunca se rellena `resumen` con texto
    aproximado.
    """
    # Lo primero: sin email de contacto no se puede consultar PubMed, y es
    # mejor saberlo antes de que el filtro de alcance gaste una llamada de pago.
    client = client or PubMedClient()

    criterios = Criterios.de(termino, autor=autor, patogeno=patogeno)
    # La consulta que se manda a PubMed (término + autor[AU] + patógeno) y el
    # sujeto que ve el guardarraíl (término + patógeno, SIN el autor) son cosas
    # distintas a propósito. Ver `busqueda.py`.
    consulta = construir_consulta(criterios)
    sujeto = sujeto_de_alcance(criterios)

    # Contador de llamadas reales a Claude de ESTA búsqueda: alimenta el
    # límite diario y la columna `llamadas_claude` del registro de acciones.
    llamadas_consumidas = 0

    def _contar() -> None:
        nonlocal llamadas_consumidas
        llamadas_consumidas += 1
        if limites is not None:
            limites.registrar_llamada_claude()

    registro = RegistroAcciones(db) if db is not None else None

    def _registrar(resultado_tipo, *, detalle=None, desde_cache=False, pmids_lista=None, cache_id=None):
        if registro is None:
            return
        registro.registrar(
            termino=consulta,
            resultado=resultado_tipo,
            max_resultados=max_resultados,
            dias=dias,
            detalle=detalle,
            desde_cache=desde_cache,
            llamadas_claude=llamadas_consumidas,
            pmids=pmids_lista,
            cache_id=cache_id,
        )

    # Límites diarios propios del usuario (búsquedas y llamadas a Claude).
    # Se comprueban al inicio: una búsqueda en marcha se termina aunque cruce
    # el límite a mitad. Cada llamada real a Claude pasa por `_contar`.
    if limites is None and db is not None:
        limites = LimitesUso(db)
    if limites is not None:
        try:
            limites.comprobar()
        except LimiteAlcanzadoError as exc:
            _registrar(RESULTADO_BLOQUEADA_LIMITE, detalle=str(exc))
            raise
        limites.registrar_busqueda()

    # Aviso de idioma: local, determinista y gratis (no gasta llamada ni
    # depende de la clave), así que se calcula siempre, incluso cuando el
    # guardarraíl de alcance está desactivado. Solo informa: ni traduce el
    # término ni bloquea la búsqueda. Se mira el sujeto médico y no el autor:
    # un apellido no está "escrito en" ningún idioma.
    aviso_idioma = aviso_de_idioma(sujeto, idioma) if sujeto else None

    aviso_alcance: str | None = None
    if verificar_alcance:
        if not sujeto:
            # Solo autor: no hay nada médico que clasificar. Se resuelve aquí,
            # sin llamar a la API y sin cachear un veredicto que no dice nada
            # del término (no lo hay), y se deja pasar con aviso.
            veredicto = veredicto_sin_sujeto()
        else:
            verificador_alcance = verificador_alcance or VerificadorAlcance()
            cache_veredictos = CacheVeredictos(db) if db is not None else None

            veredicto = None
            if cache_veredictos is not None and not forzar:
                veredicto = cache_veredictos.buscar(sujeto)
            if veredicto is None:
                veredicto = verificador_alcance.verificar(sujeto, contador=_contar)
                if cache_veredictos is not None:
                    cache_veredictos.guardar(sujeto, veredicto)

        if veredicto.bloquea:
            _registrar(RESULTADO_BLOQUEADA_ALCANCE, detalle=veredicto.motivo)
            raise TerminoFueraDeAlcanceError(veredicto.mensaje_bloqueo(sujeto, idioma))
        aviso_alcance = veredicto.aviso(sujeto, idioma)

    try:
        papers = tuple(
            client.buscar_papers(consulta, max_resultados=max_resultados, dias=dias)
        )
    except PubMedError as exc:
        _registrar(RESULTADO_ERROR_PUBMED, detalle=str(exc))
        raise

    # `papers` se mantiene SIEMPRE en el orden canónico de PubMed (relevancia):
    # es el que alimenta los PMIDs, la caché, el registro y el prompt del
    # resumen, de modo que dos búsquedas iguales con distinta ordenación de
    # pantalla produzcan exactamente el mismo resumen y el mismo acierto de
    # caché. `papers_mostrados` es solo la vista.
    orden = normalizar_orden(orden)
    papers_mostrados = ordenar_papers(papers, orden)

    pmids = [paper.pmid for paper in papers]
    if registro is not None and papers:
        registro.guardar_papers(papers)

    if not papers or not resumir:
        _registrar(
            RESULTADO_SIN_RESULTADOS if not papers else RESULTADO_EXITO,
            pmids_lista=pmids or None,
        )
        return ResultadoBusqueda(
            query=consulta,
            papers=papers_mostrados,
            orden=orden,
            criterios=criterios,
            aviso=traducir("comun_aviso_no_diagnostico", idioma),
            dias=dias,
            aviso_alcance=aviso_alcance,
            aviso_idioma=aviso_idioma,
        )

    summarizer = summarizer or Summarizer()
    cache_resumenes = CacheResumenes(db) if db is not None else None

    if cache_resumenes is not None and not forzar:
        cacheado = cache_resumenes.buscar(consulta, pmids, idioma)
        if cacheado is not None:
            _registrar(
                RESULTADO_EXITO,
                desde_cache=True,
                pmids_lista=pmids,
                cache_id=cacheado.id,
            )
            return ResultadoBusqueda(
                query=consulta,
                papers=papers_mostrados,
                orden=orden,
                criterios=criterios,
                aviso=traducir("comun_aviso_no_diagnostico", idioma),
                resumen=cacheado.resumen,
                dias=dias,
                aviso_alcance=aviso_alcance,
                aviso_idioma=aviso_idioma,
                desde_cache=True,
                cache_creado_en=cacheado.creado_en,
            )

    try:
        if verificar_resumen:
            verificador_resumen = verificador_resumen or VerificadorResumen()
            resumen = resumir_con_verificacion(
                sujeto or consulta,
                papers,
                summarizer=summarizer,
                verificador=verificador_resumen,
                idioma=idioma,
                contador=_contar,
            )
        else:
            resumen = summarizer.resumir(
                sujeto or consulta, papers, idioma=idioma, contador=_contar
            )
    except ResumenError as exc:
        _registrar(RESULTADO_ERROR_RESUMEN, detalle=str(exc), pmids_lista=pmids)
        return ResultadoBusqueda(
            query=consulta,
            papers=papers_mostrados,
            orden=orden,
            criterios=criterios,
            aviso=traducir("comun_aviso_no_diagnostico", idioma),
            dias=dias,
            error_resumen=str(exc),
            aviso_alcance=aviso_alcance,
            aviso_idioma=aviso_idioma,
        )

    # Solo se cachean resúmenes que pasaron la verificación: con
    # `verificar_resumen=False` la caché no debe blanquear texto sin verificar.
    cache_id = None
    if cache_resumenes is not None and verificar_resumen:
        cache_id = cache_resumenes.guardar(
            consulta, pmids, resumen, summarizer.modelo, idioma
        )

    _registrar(RESULTADO_EXITO, pmids_lista=pmids, cache_id=cache_id)
    return ResultadoBusqueda(
        query=consulta,
        papers=papers_mostrados,
        orden=orden,
        criterios=criterios,
        aviso=traducir("comun_aviso_no_diagnostico", idioma),
        resumen=resumen,
        dias=dias,
        aviso_alcance=aviso_alcance,
        aviso_idioma=aviso_idioma,
    )
