"""Guardarraíl de alcance: solo genes y síndromes de enfermedades raras.

Antes de lanzar la búsqueda a PubMed, una llamada corta a la API de Claude
clasifica el término introducido. Tres veredictos posibles:

- ``dentro_de_alcance``: la búsqueda sigue sin más.
- ``ambiguo``: la búsqueda sigue, pero con un aviso visible.
- ``fuera_de_alcance``: la búsqueda se bloquea ANTES de tocar PubMed, con un
  mensaje claro (nunca un "sin resultados" genérico).

Si la llamada de verificación falla (timeout, API caída, clave ausente, JSON
irreconocible), la búsqueda NO se bloquea: se deja pasar con un aviso visible
("fail-open"). El razonamiento completo está en docs/decisions.md: el
guardarraíl delimita el alcance del producto, no protege contra resultados
inventados — los papers vienen de PubMed y el resumidor tiene sus propias
reglas.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import PaperSearchError
from .summarizer import MODELO_POR_DEFECTO, FaltaAPIKeyError, _crear_client

log = logging.getLogger(__name__)

MAX_TOKENS = 2000
TIMEOUT_SEGUNDOS = 15.0

DENTRO_DE_ALCANCE = "dentro_de_alcance"
AMBIGUO = "ambiguo"
FUERA_DE_ALCANCE = "fuera_de_alcance"
#: Veredicto local (no lo emite el modelo): la verificación no se pudo hacer.
NO_CONCLUYENTE = "no_concluyente"

VEREDICTOS_DEL_MODELO = (DENTRO_DE_ALCANCE, AMBIGUO, FUERA_DE_ALCANCE)

#: Motivo del veredicto local para una búsqueda sin sujeto médico (solo autor).
#: No hay nada que clasificar, así que no se llama a la API: se resuelve aquí.
MOTIVO_SIN_SUJETO = "la búsqueda no incluye ningún término de enfermedad ni patógeno"

SYSTEM_PROMPT = """\
Eres un clasificador para una herramienta de búsqueda bibliográfica en PubMed
especializada en enfermedades raras. Tu única tarea es decidir si el término de
búsqueda que te dan es plausible como (a) un gen humano, (b) un síndrome o
enfermedad rara, o (c) un término directamente relacionado con enfermedades
raras (p. ej. un mecanismo, fenotipo o tratamiento asociado a ellas).

Criterios:
- Genes (SCN1A, MECP2, FBN1...) y síndromes raros (Dravet, Rett, Marfan...):
  dentro de alcance.
- Enfermedades comunes sin relación con enfermedades raras (gripe, hipertensión,
  diabetes tipo 2...): fuera de alcance.
- Términos que no son médicos (nombres propios, objetos, conceptos generales):
  fuera de alcance.
- Si el término es médico pero no puedes determinar con confianza si se
  relaciona con enfermedades raras (siglas ambiguas, términos muy generales
  como "epilepsia"), márcalo como ambiguo: la herramienta lo dejará pasar
  con un aviso. Ante la duda entre ambiguo y fuera de alcance, elige ambiguo.

No evalúes si la búsqueda dará resultados, solo si el término es plausible
dentro del alcance descrito. Responde únicamente con el JSON pedido."""

ESQUEMA_RESPUESTA = {
    "type": "object",
    "properties": {
        "veredicto": {
            "type": "string",
            "enum": [DENTRO_DE_ALCANCE, AMBIGUO, FUERA_DE_ALCANCE],
        },
        "motivo": {
            "type": "string",
            "description": "Una frase, en español, explicando el veredicto.",
        },
    },
    "required": ["veredicto", "motivo"],
    "additionalProperties": False,
}


class TerminoFueraDeAlcanceError(PaperSearchError):
    """El término no es plausible dentro del alcance (enfermedades raras)."""


@dataclass(frozen=True)
class VeredictoAlcance:
    """Resultado de la verificación de alcance de un término."""

    veredicto: str
    motivo: str

    @property
    def bloquea(self) -> bool:
        return self.veredicto == FUERA_DE_ALCANCE

    def aviso(self, termino: str) -> str | None:
        """Texto de aviso para CLI/web, o `None` si no hace falta avisar."""
        if self.veredicto == NO_CONCLUYENTE and self.motivo == MOTIVO_SIN_SUJETO:
            # Búsqueda solo por autor: no hay término de enfermedad que citar
            # en el mensaje, así que se explica la situación en vez de dejar
            # unas comillas vacías.
            return (
                "Esta búsqueda no incluye ningún término de enfermedad ni "
                "patógeno —solo filtros como el autor—, así que no se ha "
                "podido comprobar si está dentro del alcance de la herramienta "
                "(enfermedades raras). Los resultados pueden incluir trabajos "
                "ajenos a este ámbito. La búsqueda se ha ejecutado igualmente."
            )
        if self.veredicto == AMBIGUO:
            return (
                f"El término «{termino}» no se ha podido clasificar con "
                f"seguridad dentro del alcance de la herramienta (enfermedades "
                f"raras): {self.motivo} La búsqueda se ha ejecutado "
                f"igualmente; interpreta los resultados con cautela."
            )
        if self.veredicto == NO_CONCLUYENTE:
            return (
                f"No se ha podido comprobar si «{termino}» está dentro del "
                f"alcance de la herramienta (enfermedades raras): "
                f"{self.motivo}. La búsqueda se ha ejecutado igualmente."
            )
        return None

    def mensaje_bloqueo(self, termino: str) -> str:
        return (
            f"El término «{termino}» está fuera del alcance de esta "
            f"herramienta, que se limita a genes y síndromes relacionados con "
            f"enfermedades raras. Motivo: {self.motivo}\n"
            f"No se ha lanzado ninguna búsqueda en PubMed. Prueba con un gen "
            f"(p. ej. SCN1A) o un síndrome raro (p. ej. síndrome de Dravet)."
        )


class VerificadorAlcance:
    """Envuelve la llamada de clasificación del término de búsqueda."""

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
        self, termino: str, *, contador: Callable[[], None] | None = None
    ) -> VeredictoAlcance:
        """Clasifica `termino` y devuelve el veredicto.

        `contador` (si se pasa) se invoca una vez por llamada real a la API —
        es el gancho del límite diario de llamadas (ver `limites.py`).

        Nunca lanza excepciones por fallos de la llamada: cualquier problema
        (clave ausente, timeout, respuesta irreconocible) se devuelve como
        veredicto `NO_CONCLUYENTE`, y quien llama decide dejar pasar con aviso.
        """
        try:
            cliente = self.client.with_options(timeout=self.timeout)
            if contador is not None:
                contador()
            respuesta = cliente.messages.create(
                model=self.modelo,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                # La clasificación no necesita razonamiento profundo y así la
                # respuesta llega dentro del timeout.
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": ESQUEMA_RESPUESTA},
                },
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f'Término de búsqueda introducido por el usuario: "{termino}"'
                        ),
                    }
                ],
            )
        except FaltaAPIKeyError:
            return _no_concluyente("falta la clave de la API")
        except PaperSearchError as exc:
            # Cualquier otro fallo del paquete al crear el cliente perezoso
            # (p. ej. falta el paquete 'anthropic'). Se reporta su motivo real:
            # atribuirlo a la clave mandaba a revisar algo que sí estaba bien.
            return _no_concluyente(str(exc))
        except Exception as exc:  # errores de red o de la API de Anthropic
            log.warning("La verificación de alcance falló: %s: %s", exc.__class__.__name__, exc)
            return _no_concluyente(
                f"la llamada de verificación falló ({exc.__class__.__name__})"
            )

        return _interpretar_respuesta(respuesta)


def _no_concluyente(motivo: str) -> VeredictoAlcance:
    return VeredictoAlcance(veredicto=NO_CONCLUYENTE, motivo=motivo)


def veredicto_sin_sujeto() -> VeredictoAlcance:
    """Veredicto local para una búsqueda sin término ni patógeno.

    No se llama a la API: sin sujeto médico no hay nada que clasificar, y
    preguntar por un apellido sería una pregunta sin respuesta. Se deja pasar
    con aviso, igual que cualquier otra verificación no concluyente.
    """
    return _no_concluyente(MOTIVO_SIN_SUJETO)


def _interpretar_respuesta(respuesta: Any) -> VeredictoAlcance:
    """Convierte la respuesta del modelo en un veredicto, sin lanzar nunca."""
    if getattr(respuesta, "stop_reason", None) == "refusal":
        return _no_concluyente("el modelo declinó clasificar el término")

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

    veredicto = datos.get("veredicto") if isinstance(datos, dict) else None
    if veredicto not in VEREDICTOS_DEL_MODELO:
        return _no_concluyente("la respuesta de la verificación no traía un veredicto conocido")

    motivo = datos.get("motivo")
    if not isinstance(motivo, str) or not motivo.strip():
        motivo = "sin motivo indicado"

    return VeredictoAlcance(veredicto=veredicto, motivo=motivo.strip())
