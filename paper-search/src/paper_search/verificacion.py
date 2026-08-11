"""Verificación automática del resumen antes de mostrarlo.

Hasta ahora la única garantía de que el resumen no inventa nada ni aconseja al
lector era el prompt del resumidor. Este módulo añade una segunda barrera en
código, en dos capas:

1. **Comprobación determinista** (gratis, sin API): todos los PMIDs citados en
   el resumen deben pertenecer a la lista de artículos realmente recuperados de
   PubMed, y el resumen debe citar al menos una vez. Un PMID inventado se
   detecta aquí sin gastar una llamada.
2. **Llamada de verificación a la API de Claude**: comprueba lo que el código
   no puede — que toda afirmación clínica lleve su cita [PMID: ...] y que no
   haya consejo médico dirigido al lector.

Si alguna capa rechaza el resumen, se regenera pasándole al resumidor los
problemas concretos, hasta `MAX_INTENTOS`. Un fallo técnico de la llamada de
verificación (timeout, API caída) cuenta también como intento fallido, con su
propio tipo de problema (`no_verificado`): ningún resumen se entrega sin haber
superado la verificación ("fail-closed", al contrario que el guardarraíl de
alcance — ver docs/decisions.md). Agotados los intentos, se lanza
`ResumenError` (visible en CLI y web, nunca en silencio) y los papers reales se
conservan.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .models import PATRON_CITA, Paper, PaperSearchError
from .summarizer import (
    MODELO_POR_DEFECTO,
    FaltaAPIKeyError,
    ResumenError,
    Summarizer,
    _crear_client,
)

log = logging.getLogger(__name__)

MAX_TOKENS = 3000
TIMEOUT_SEGUNDOS = 30.0

#: 1 generación inicial + 2 regeneraciones con feedback.
MAX_INTENTOS = 3

APROBADO = "aprobado"
RECHAZADO = "rechazado"
#: Estado local (no lo emite el modelo): la verificación no se pudo hacer.
NO_CONCLUYENTE = "no_concluyente"

#: Caracteres del fragmento problemático que se citan en mensajes y feedback.
MAX_CARACTERES_FRAGMENTO = 160

SYSTEM_PROMPT = """\
Eres un verificador de calidad para resúmenes de literatura biomédica dirigidos
a personas sin formación médica. Recibirás un resumen y la lista de PMIDs de
los artículos reales en los que debe basarse. Comprueba dos cosas:

1. TRAZABILIDAD: toda afirmación clínica o factual (hallazgos, cifras,
   asociaciones gen-enfermedad, resultados de estudios) debe ir seguida de una
   cita [PMID: ...] cuyo número esté en la lista de PMIDs válidos. Frases de
   transición, encabezados y la advertencia de que faltan datos no necesitan
   cita.
2. SIN CONSEJO MÉDICO: el resumen no debe contener recomendaciones dirigidas
   al lector (tomar/evitar tratamientos, dosis, "consulte", "se recomienda",
   pronósticos personales...). Describir qué dicen los papers sobre un
   tratamiento SÍ está permitido; recomendárselo al lector NO.

Sé estricto con estas dos reglas y no señales ningún otro tipo de problema
(estilo, longitud, orden...). Responde únicamente con el JSON pedido."""

#: Tipos de problema que puede señalar el modelo.
TIPOS_DEL_MODELO = ("afirmacion_sin_pmid", "consejo_medico")

ESQUEMA_RESPUESTA = {
    "type": "object",
    "properties": {
        "aprobado": {"type": "boolean"},
        "problemas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": list(TIPOS_DEL_MODELO)},
                    "fragmento": {
                        "type": "string",
                        "description": (
                            "Cita literal del trozo problemático del resumen."
                        ),
                    },
                    "detalle": {"type": "string"},
                },
                "required": ["tipo", "fragmento", "detalle"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["aprobado", "problemas"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Problema:
    """Un motivo concreto de rechazo del resumen."""

    tipo: str
    fragmento: str
    detalle: str


@dataclass(frozen=True)
class ResultadoVerificacion:
    """Salida de una pasada del verificador de la API."""

    estado: str  # APROBADO | RECHAZADO | NO_CONCLUYENTE
    problemas: tuple[Problema, ...] = ()
    #: Causa breve cuando `estado == NO_CONCLUYENTE`.
    motivo: str = ""


class VerificadorResumen:
    """Envuelve la llamada de verificación del resumen generado."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        modelo: str = MODELO_POR_DEFECTO,
        max_tokens: int = MAX_TOKENS,
        timeout: float = TIMEOUT_SEGUNDOS,
    ) -> None:
        self.modelo = modelo
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = client

    @property
    def client(self) -> Any:
        """Cliente de Anthropic, creado de forma perezosa."""
        if self._client is None:
            self._client = _crear_client()
        return self._client

    def verificar(
        self,
        resumen: str,
        pmids_validos: Sequence[str],
        *,
        contador: Callable[[], None] | None = None,
    ) -> ResultadoVerificacion:
        """Verifica `resumen` contra la lista real de PMIDs.

        `contador` (si se pasa) se invoca una vez por llamada real a la API —
        es el gancho del límite diario de llamadas (ver `limites.py`).

        Nunca lanza excepciones por fallos de la llamada: cualquier problema
        (clave ausente, timeout, respuesta irreconocible) se devuelve como
        `NO_CONCLUYENTE`, y el bucle de reintentos lo trata como intento
        fallido (fail-closed).
        """
        prompt = (
            f"PMIDs válidos: {', '.join(pmids_validos)}\n\n"
            f"Resumen a verificar:\n---\n{resumen}\n---"
        )
        try:
            cliente = self.client.with_options(timeout=self.timeout)
            if contador is not None:
                contador()
            respuesta = cliente.messages.create(
                model=self.modelo,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                # Revisión acotada a dos reglas: no necesita razonamiento
                # profundo, y así la respuesta llega dentro del timeout.
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": ESQUEMA_RESPUESTA},
                },
                messages=[{"role": "user", "content": prompt}],
            )
        except FaltaAPIKeyError:
            return _no_concluyente("falta la clave de la API")
        except PaperSearchError as exc:
            # Cualquier otro fallo del paquete al crear el cliente perezoso
            # (p. ej. falta el paquete 'anthropic'). Se reporta su motivo real:
            # atribuirlo a la clave mandaba a revisar algo que sí estaba bien.
            return _no_concluyente(str(exc))
        except Exception as exc:  # errores de red o de la API de Anthropic
            log.warning(
                "La verificación del resumen falló: %s: %s", exc.__class__.__name__, exc
            )
            return _no_concluyente(
                f"la llamada de verificación falló ({exc.__class__.__name__})"
            )

        return _interpretar_respuesta(respuesta)


def problemas_deterministas(
    resumen: str, pmids_validos: Sequence[str]
) -> tuple[Problema, ...]:
    """Comprobaciones de trazabilidad que no necesitan ninguna API.

    - El resumen debe citar al menos un PMID (regla del brief: ningún resumen
      sin sus PMIDs de respaldo).
    - Todo PMID citado debe estar en la lista de artículos recuperados: un
      PMID ajeno es, por definición, invención o contaminación de memoria.
    """
    citas = PATRON_CITA.findall(resumen)
    if not citas:
        return (
            Problema(
                tipo="sin_citas",
                fragmento=_recortar(resumen),
                detalle=(
                    "el resumen no contiene ninguna cita [PMID: ...]; cada "
                    "afirmación debe terminar con el PMID que la respalda"
                ),
            ),
        )

    validos = set(pmids_validos)
    problemas: list[Problema] = []
    for cita in citas:
        for pmid in re.findall(r"\d+", cita):
            if pmid not in validos:
                problemas.append(
                    Problema(
                        tipo="pmid_desconocido",
                        fragmento=cita,
                        detalle=(
                            f"el PMID {pmid} no está en la lista de artículos "
                            f"recuperados de PubMed; solo se pueden citar los "
                            f"PMIDs proporcionados"
                        ),
                    )
                )
    return tuple(problemas)


def resumir_con_verificacion(
    termino: str,
    papers: Sequence[Paper],
    *,
    summarizer: Summarizer,
    verificador: VerificadorResumen,
    max_intentos: int = MAX_INTENTOS,
    contador: Callable[[], None] | None = None,
) -> str:
    """Genera el resumen y no lo da por bueno hasta que pasa la verificación.

    Cada rechazo regenera el resumen pasando los problemas concretos al
    resumidor; un fallo técnico de la verificación cuenta como intento fallido
    (fail-closed). Agotados `max_intentos`, lanza `ResumenError` con los
    problemas del último intento: nunca se entrega un resumen rechazado ni se
    falla en silencio.
    """
    pmids = tuple(paper.pmid for paper in papers)
    problemas: tuple[Problema, ...] = ()

    for _intento in range(max_intentos):
        correcciones = _formatear_correcciones(problemas) if problemas else None
        resumen = summarizer.resumir(
            termino, papers, correcciones=correcciones, contador=contador
        )

        problemas = problemas_deterministas(resumen, pmids)
        if problemas:
            continue

        resultado = verificador.verificar(resumen, pmids, contador=contador)
        if resultado.estado == APROBADO:
            return resumen
        if resultado.estado == NO_CONCLUYENTE:
            # Fail-closed: sin verificación completada no hay resumen. El
            # problema lleva su propio tipo para que la regeneración (y el
            # mensaje final si se agotan los intentos) expliquen la causa.
            problemas = (
                Problema(
                    tipo="no_verificado",
                    fragmento=_recortar(resumen),
                    detalle=f"no se pudo verificar: {resultado.motivo}",
                ),
            )
            continue
        problemas = resultado.problemas or (
            Problema(
                tipo="rechazo_sin_detalle",
                fragmento=_recortar(resumen),
                detalle="el verificador rechazó el resumen sin detallar los problemas",
            ),
        )

    raise ResumenError(_mensaje_intentos_agotados(max_intentos, problemas))


def _no_concluyente(motivo: str) -> ResultadoVerificacion:
    return ResultadoVerificacion(estado=NO_CONCLUYENTE, motivo=motivo)


def _interpretar_respuesta(respuesta: Any) -> ResultadoVerificacion:
    """Convierte la respuesta del modelo en un resultado, sin lanzar nunca."""
    if getattr(respuesta, "stop_reason", None) == "refusal":
        return _no_concluyente("el modelo declinó verificar el resumen")

    texto = next(
        (
            bloque.text
            for bloque in getattr(respuesta, "content", []) or []
            if getattr(bloque, "type", None) == "text"
            and getattr(bloque, "text", "").strip()
        ),
        "",
    )
    if not texto:
        return _no_concluyente("la respuesta de la verificación llegó vacía")

    try:
        datos = json.loads(texto)
    except ValueError:
        return _no_concluyente("la respuesta de la verificación no era JSON válido")

    if not isinstance(datos, dict) or not isinstance(datos.get("aprobado"), bool):
        return _no_concluyente("la respuesta de la verificación no traía un veredicto")

    if datos["aprobado"]:
        return ResultadoVerificacion(estado=APROBADO)

    problemas = tuple(
        Problema(
            tipo=str(item.get("tipo", "problema")),
            fragmento=_recortar(str(item.get("fragmento", ""))),
            detalle=str(item.get("detalle", "")),
        )
        for item in datos.get("problemas") or []
        if isinstance(item, dict)
    )
    return ResultadoVerificacion(estado=RECHAZADO, problemas=problemas)


def _formatear_correcciones(problemas: Sequence[Problema]) -> str:
    lineas = [
        "Un verificador automático rechazó el intento anterior de este resumen "
        "por los problemas siguientes. Corrígelos sin introducir información "
        "nueva ni citas que no estén en los artículos de arriba:"
    ]
    lineas.extend(
        f"- [{p.tipo}] «{p.fragmento}»: {p.detalle}" for p in problemas
    )
    return "\n".join(lineas)


def _mensaje_intentos_agotados(
    max_intentos: int, problemas: Sequence[Problema]
) -> str:
    lineas = [
        f"El resumen generado no superó la verificación automática tras "
        f"{max_intentos} intentos y se ha descartado. Problemas detectados en "
        f"el último intento:"
    ]
    lineas.extend(f"- [{p.tipo}] «{p.fragmento}»: {p.detalle}" for p in problemas)
    lineas.append(
        "No se muestra ningún resumen; las referencias de PubMed sí son "
        "reales y verificables por su PMID."
    )
    return "\n".join(lineas)


def _recortar(texto: str) -> str:
    texto = texto.strip()
    if len(texto) <= MAX_CARACTERES_FRAGMENTO:
        return texto
    return texto[:MAX_CARACTERES_FRAGMENTO] + "[...]"
