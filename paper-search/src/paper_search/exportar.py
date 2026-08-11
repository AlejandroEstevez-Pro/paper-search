"""Exportación del resultado a texto plano, para pegarlo en NotebookLM.

NotebookLM (y Gemini Notebook) aceptan texto pegado como fuente, así que no
hace falta ninguna integración por API: basta con producir un texto limpio y
que la persona lo pegue. Se descartó usar una librería no oficial de NotebookLM
por el riesgo sobre una cuenta de Google real (ver docs/decisions.md).

"Limpio" significa sin nada de la interfaz —ni HTML, ni clases CSS, ni botones,
ni el aviso de "servido desde caché"— pero **con todo el contenido**: el
término buscado, el resumen íntegro con sus citas `[PMID: ...]`, las
referencias con su enlace a PubMed y el aviso de que esto no es una herramienta
de diagnóstico.

Esas tres cosas no son decoración:

- El **término** va de encabezado porque una fuente pegada en NotebookLM pierde
  todo el contexto de dónde salió; sin él, dentro de dos semanas es un texto
  huérfano.
- Los **PMIDs y enlaces** son la regla de trazabilidad del proyecto: un resumen
  sin forma de verificarlo no debe salir de aquí, y menos aún hacia una
  herramienta donde se mezclará con otras fuentes.
- El **aviso médico** viaja con el texto justamente porque el texto va a viajar:
  separado de esta interfaz, nada recordaría que no es asesoramiento médico.

El texto no depende de si el resumen se generó ahora o vino de la caché: es el
mismo contenido, y meter metadatos de caché haría que dos exportaciones del
mismo resumen no coincidieran.
"""

from __future__ import annotations

from .models import AVISO_NO_DIAGNOSTICO, ResultadoBusqueda

#: Ancho de las líneas separadoras. Texto plano, sin Markdown: NotebookLM lo
#: trata como fuente y los `#` o `**` solo añadirían ruido al pegarlo.
_REGLA = "=" * 60


def _cabecera(resultado: ResultadoBusqueda) -> list[str]:
    """Qué se buscó, campo a campo, para que la fuente se explique sola."""
    lineas = ["BÚSQUEDA EN PUBMED — paper-search", _REGLA]

    criterios = resultado.criterios
    termino = getattr(criterios, "termino", "") if criterios else ""
    autor = getattr(criterios, "autor", "") if criterios else ""
    patogeno = getattr(criterios, "patogeno", "") if criterios else ""

    if termino:
        lineas.append(f"Término: {termino}")
    if autor:
        lineas.append(f"Autor: {autor}")
    if patogeno:
        lineas.append(f"Patógeno: {patogeno}")
    if not (termino or autor or patogeno):
        # Resultado construido sin criterios (uso como librería): al menos se
        # dice qué consulta se lanzó.
        lineas.append(f"Término: {resultado.query}")
    elif resultado.query and resultado.query != termino:
        # La consulta montada difiere de lo tecleado: se enseña, porque explica
        # por qué salieron estos artículos y no otros.
        lineas.append(f"Consulta enviada a PubMed: {resultado.query}")

    if resultado.dias:
        lineas.append(
            f"Ventana: artículos de los últimos {resultado.dias} días"
        )
    lineas.append(f"Artículos recuperados: {resultado.total}")
    return lineas


def _referencias(resultado: ResultadoBusqueda) -> list[str]:
    lineas = ["", _REGLA, f"REFERENCIAS ({resultado.total})", _REGLA]
    for i, paper in enumerate(resultado.papers, start=1):
        lineas.append(f"[{i}] {paper.titulo}")
        detalle = " · ".join(
            parte for parte in (paper.revista, paper.anio or paper.fecha) if parte
        )
        cabecera = paper.autores_texto
        if detalle:
            cabecera = f"{cabecera} — {detalle}"
        lineas.append(f"    {cabecera}")
        lineas.append(f"    PMID {paper.pmid} — {paper.url}")
        lineas.append("")
    return lineas


def texto_para_notebooklm(resultado: ResultadoBusqueda) -> str:
    """Devuelve el resultado como texto plano listo para pegar como fuente.

    Incluye siempre el término buscado, el resumen (o el motivo de que no lo
    haya), las referencias con PMID y enlace, y el aviso de no diagnóstico.
    Nunca incluye marcado de la página ni metadatos de caché.
    """
    lineas = _cabecera(resultado)

    lineas += ["", _REGLA, "RESUMEN", _REGLA]
    if resultado.resumen:
        lineas.append(resultado.resumen)
    elif resultado.error_resumen:
        # Se exporta igual: las referencias son reales y valen como fuente. Lo
        # que no se hace nunca es dejar el hueco sin explicar.
        lineas.append(
            "No se generó resumen para esta búsqueda. Motivo: "
            f"{resultado.error_resumen}"
        )
    else:
        lineas.append(
            "No se generó resumen para esta búsqueda. Las referencias de abajo "
            "vienen directamente de PubMed."
        )

    if resultado.aviso_alcance:
        lineas += ["", "AVISO DE ALCANCE: " + resultado.aviso_alcance]
    if resultado.aviso_idioma:
        lineas += ["", "AVISO DE IDIOMA: " + resultado.aviso_idioma]

    if resultado.papers:
        lineas += _referencias(resultado)

    lineas += ["", _REGLA, "AVISO", _REGLA, resultado.aviso or AVISO_NO_DIAGNOSTICO]

    return "\n".join(lineas).strip() + "\n"
