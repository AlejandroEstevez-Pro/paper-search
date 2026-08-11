"""Generación del resumen en lenguaje llano a partir de los abstracts.

El resumen lo escribe un modelo de Anthropic a partir *exclusivamente* de los
abstracts que le pasamos, con la instrucción de citar el PMID concreto detrás
de cada afirmación. Si la clave no está puesta o la API falla, se lanza un
error explícito: nunca se devuelve un resumen aproximado o de memoria.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

from .models import PaperSearchError, Paper

MODELO_POR_DEFECTO = "claude-opus-5"
MAX_TOKENS = 16000

#: Cuántos caracteres de cada abstract se envían al modelo. Los abstracts de
#: PubMed rara vez pasan de ~2500 caracteres; el corte es una red de seguridad
#: y se marca de forma visible para que el modelo sepa que está truncado.
MAX_CARACTERES_ABSTRACT = 6000

SYSTEM_PROMPT = """\
Eres un asistente que resume literatura biomédica sobre enfermedades raras para \
personas sin formación médica (pacientes, familias, investigadores de otras áreas).

Reglas que no puedes romper:

1. Usa ÚNICAMENTE la información de los abstracts que te doy en el mensaje. No \
   añadas datos de tu memoria, ni cites papers que no estén en la lista, ni \
   inventes cifras, nombres o conclusiones.
2. Cada afirmación del resumen debe terminar con el PMID que la respalda, en el \
   formato [PMID: 12345678]. Si una afirmación se apoya en varios papers, ponlos \
   todos: [PMID: 12345678, 23456789].
3. Escribe en español y en lenguaje llano. Cuando un término técnico sea \
   inevitable, explícalo entre paréntesis la primera vez.
4. Agrupa los hallazgos por tema si los papers tratan líneas distintas (por \
   ejemplo genética, tratamiento, modelos animales, historia natural). Usa un \
   encabezado corto por tema.
5. NO des consejo médico, ni recomendaciones de tratamiento, ni pronósticos. \
   Limítate a describir qué dicen los papers.
6. Si los abstracts no bastan para decir algo con claridad, dilo explícitamente \
   en vez de rellenar el hueco.
7. Si algún artículo no trae abstract, no supongas su contenido: menciónalo como \
   "sin abstract disponible" si es relevante.

Formato de salida: texto plano, sin preámbulo. Empieza directamente con el \
resumen. Un párrafo inicial de dos o tres frases con la idea general, y después \
los temas."""


class ResumenError(PaperSearchError):
    """No se pudo generar el resumen (API caída, respuesta vacía, rechazo...)."""


class FaltaAPIKeyError(ResumenError):
    """No está definida la variable de entorno ANTHROPIC_API_KEY."""


MENSAJE_FALTA_API_KEY = (
    "Falta ANTHROPIC_API_KEY, necesaria para generar el resumen en lenguaje "
    "llano.\n"
    "Consíguela en https://console.anthropic.com/ y ponla de una de estas dos "
    "formas:\n"
    "  1. En un archivo .env en la carpeta paper-search/ (copia .env.example a "
    ".env y rellena la clave).\n"
    "  2. Como variable de entorno, que tiene prioridad sobre el .env:\n"
    '       PowerShell:  $env:ANTHROPIC_API_KEY = "sk-ant-..."\n'
    '       bash/zsh:    export ANTHROPIC_API_KEY="sk-ant-..."\n'
    "Los resultados de PubMed (títulos, autores, PMIDs) sí se pueden consultar "
    "sin esta clave."
)


class Summarizer:
    """Envuelve la llamada al modelo para producir el resumen trazable."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        modelo: str = MODELO_POR_DEFECTO,
        max_tokens: int = MAX_TOKENS,
    ) -> None:
        self.modelo = modelo
        self.max_tokens = max_tokens
        self._client = client

    @property
    def client(self) -> Any:
        """Cliente de Anthropic, creado de forma perezosa."""
        if self._client is None:
            self._client = _crear_client()
        return self._client

    def resumir(
        self,
        termino: str,
        papers: Sequence[Paper],
        *,
        correcciones: str | None = None,
        contador: Callable[[], None] | None = None,
    ) -> str:
        """Devuelve el resumen en lenguaje llano de `papers`.

        `correcciones` es un bloque de feedback del verificador de resúmenes
        (ver `verificacion.py`) que se añade al prompt al regenerar un resumen
        rechazado. `contador` (si se pasa) se invoca una vez por llamada real
        a la API — es el gancho del límite diario de llamadas (`limites.py`).

        Lanza `FaltaAPIKeyError` si no hay clave y `ResumenError` si la API
        falla o responde algo inutilizable.
        """
        if not papers:
            raise ValueError(
                "No hay papers que resumir. Comprueba antes si la búsqueda "
                "devolvió resultados."
            )

        prompt = construir_prompt(termino, papers, correcciones=correcciones)

        try:
            cliente = self.client
            if contador is not None:
                contador()
            respuesta = cliente.messages.create(
                model=self.modelo,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except PaperSearchError:
            raise
        except Exception as exc:  # errores de red o de la API de Anthropic
            raise ResumenError(
                f"La API de Anthropic falló al generar el resumen "
                f"({exc.__class__.__name__}: {exc}). No se ha generado ningún "
                f"resumen; las referencias de PubMed de abajo sí son reales."
            ) from exc

        return _extraer_texto(respuesta)


def construir_prompt(
    termino: str,
    papers: Sequence[Paper],
    *,
    correcciones: str | None = None,
) -> str:
    """Arma el mensaje de usuario con los abstracts y sus PMIDs."""
    bloques: list[str] = []
    for i, paper in enumerate(papers, start=1):
        abstract = paper.abstract.strip()
        if len(abstract) > MAX_CARACTERES_ABSTRACT:
            abstract = abstract[:MAX_CARACTERES_ABSTRACT] + " [...abstract truncado]"
        if not abstract:
            abstract = "(sin abstract disponible)"
        bloques.append(
            f"### Artículo {i}\n"
            f"PMID: {paper.pmid}\n"
            f"Título: {paper.titulo}\n"
            f"Autores: {paper.autores_texto}\n"
            f"Revista: {paper.revista or 'no disponible'}\n"
            f"Fecha: {paper.fecha or 'no disponible'}\n"
            f"Abstract: {abstract}"
        )

    prompt = (
        f'Término de búsqueda: "{termino}"\n'
        f"Artículos recuperados de PubMed: {len(papers)}\n\n"
        + "\n\n".join(bloques)
        + "\n\nResume los hallazgos de estos artículos siguiendo las reglas del "
        "sistema. Recuerda citar el PMID detrás de cada afirmación."
    )
    if correcciones:
        prompt += "\n\n" + correcciones
    return prompt


def _crear_client() -> Any:
    """Crea el cliente de Anthropic leyendo la clave del entorno."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise FaltaAPIKeyError(MENSAJE_FALTA_API_KEY)
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ResumenError(
            "Falta el paquete 'anthropic'. Instálalo con "
            "`pip install -r requirements.txt`."
        ) from exc
    return anthropic.Anthropic()


def _extraer_texto(respuesta: Any) -> str:
    """Saca el texto de la respuesta, comprobando antes que sea utilizable."""
    if getattr(respuesta, "stop_reason", None) == "refusal":
        detalles = getattr(respuesta, "stop_details", None)
        motivo = getattr(detalles, "explanation", None) or "sin explicación"
        raise ResumenError(
            f"El modelo declinó generar el resumen ({motivo}). No se muestra "
            f"ningún resumen; consulta directamente los abstracts en PubMed."
        )

    partes = [
        bloque.text
        for bloque in getattr(respuesta, "content", []) or []
        if getattr(bloque, "type", None) == "text" and getattr(bloque, "text", "").strip()
    ]
    texto = "\n".join(partes).strip()
    if not texto:
        raise ResumenError(
            "La API de Anthropic devolvió una respuesta vacía. No se ha "
            "generado ningún resumen."
        )
    return texto
