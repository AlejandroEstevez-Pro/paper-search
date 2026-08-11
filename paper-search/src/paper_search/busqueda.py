"""Búsqueda avanzada: término, autor y patógeno.

Los tres criterios se usan de dos maneras distintas, y la diferencia importa:

(a) **Filtro sobre resultados ya obtenidos** (`filtrar_papers`): se descarta en
    local lo que no encaja. No consulta PubMed, no gasta llamadas y **no puede
    encontrar nada que la búsqueda no hubiera traído ya**. Es afinar lo que hay
    en pantalla.

(b) **Criterio de búsqueda** (`construir_consulta`): entra en la consulta que
    se manda a PubMed, así que sí puede traer artículos nuevos.

Confundirlas en una herramienta bibliográfica médica es grave: filtrar 15
resultados por autor y ver 2 no significa que ese autor tenga 2 artículos sobre
el tema, sino que 2 de esos 15 son suyos. Por eso la interfaz dice siempre
"N de M resultados mostrados" y nunca un contador a secas.

**El guardarraíl de alcance solo ve el sujeto médico** (`sujeto_de_alcance`):
término + patógeno, nunca el autor. Un apellido no es un concepto médico y
pedirle a un clasificador que decida si «Sánchez J» cae dentro de las
enfermedades raras es una pregunta sin respuesta que solo puede producir
bloqueos falsos. Una búsqueda solo por autor se queda sin sujeto que clasificar
y pasa con aviso, sin gastar llamada (ver `alcance.py` y docs/decisions.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .models import Paper, PaperSearchError, plegar_texto

#: Caracteres que romperían la sintaxis de consulta de PubMed si llegan dentro
#: de un valor que nosotros metemos entre comillas o corchetes.
_PELIGROSOS = '"[]()'


class CriteriosVaciosError(PaperSearchError):
    """No se ha dado ningún criterio de búsqueda."""


@dataclass(frozen=True)
class Criterios:
    """Los criterios de una búsqueda avanzada, ya normalizados."""

    termino: str = ""
    autor: str = ""
    patogeno: str = ""

    @classmethod
    def de(
        cls,
        termino: str | None = None,
        *,
        autor: str | None = None,
        patogeno: str | None = None,
    ) -> "Criterios":
        return cls(
            termino=(termino or "").strip(),
            autor=(autor or "").strip(),
            patogeno=(patogeno or "").strip(),
        )

    @property
    def vacios(self) -> bool:
        return not (self.termino or self.autor or self.patogeno)

    @property
    def solo_autor(self) -> bool:
        """Caso límite del guardarraíl: hay autor pero ningún sujeto médico."""
        return bool(self.autor) and not (self.termino or self.patogeno)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "termino": self.termino or None,
            "autor": self.autor or None,
            "patogeno": self.patogeno or None,
        }


def _limpiar(valor: str) -> str:
    """Quita lo que rompería la consulta al envolver el valor."""
    return "".join(c for c in valor if c not in _PELIGROSOS).strip()


def construir_consulta(criterios: Criterios) -> str:
    """Arma la consulta para PubMed a partir de los criterios.

    El `termino` va **tal cual**: quien sabe escribir sintaxis de PubMed
    (`SCN1A OR SCN2A`, `"Dravet syndrome"[MeSH]`) puede seguir haciéndolo, como
    en las Fases 1 y 2. Los criterios nuevos sí se envuelven —el autor con la
    etiqueta de campo `[AU]`, el patógeno como frase entre comillas— y se les
    quitan antes los caracteres que romperían la sintaxis.

    Sin autor ni patógeno devuelve exactamente el término, para que una
    búsqueda normal produzca la misma consulta de siempre.
    """
    if criterios.vacios:
        raise CriteriosVaciosError(
            "Hace falta al menos un criterio: un término, un autor o un patógeno."
        )

    partes: list[str] = []
    if criterios.termino:
        partes.append(criterios.termino)
    if criterios.autor:
        partes.append(f'"{_limpiar(criterios.autor)}"[AU]')
    if criterios.patogeno:
        partes.append(f'"{_limpiar(criterios.patogeno)}"')

    if len(partes) == 1:
        return partes[0]
    return " AND ".join(f"({parte})" for parte in partes)


def sujeto_de_alcance(criterios: Criterios) -> str:
    """El texto que ve el guardarraíl: término + patógeno, nunca el autor.

    Cadena vacía significa "no hay nada médico que clasificar" (búsqueda solo
    por autor), y quien llama lo resuelve en local sin gastar una llamada.
    """
    return " ".join(
        parte for parte in (criterios.termino, criterios.patogeno) if parte
    ).strip()


# ------------------------------------------------------- filtros en local


def _coincide_autor(paper: Paper, autor_plegado: str) -> bool:
    return any(autor_plegado in plegar_texto(a) for a in paper.autores)


def _coincide_patogeno(paper: Paper, patogeno_plegado: str) -> bool:
    # Título y abstract: es donde se nombra al patógeno. La revista no cuenta,
    # que daría falsos positivos con revistas de microbiología.
    texto = plegar_texto(f"{paper.titulo}\n{paper.abstract}")
    return patogeno_plegado in texto


def filtrar_papers(
    papers: Iterable[Paper],
    *,
    autor: str | None = None,
    patogeno: str | None = None,
) -> tuple[Paper, ...]:
    """Filtra papers YA obtenidos, sin consultar PubMed.

    Los criterios se acumulan (AND) y la comparación ignora mayúsculas y
    tildes, para que «garcia» encuentre a «García». Sin criterios devuelve
    todo tal cual, conservando siempre el orden de entrada.

    Ojo con lo que significa el resultado: esto solo puede quitar artículos de
    la lista que ya se tenía, nunca traer otros. Ver el módulo.
    """
    lista: Sequence[Paper] = list(papers)

    autor_plegado = plegar_texto((autor or "").strip())
    patogeno_plegado = plegar_texto((patogeno or "").strip())

    if autor_plegado:
        lista = [p for p in lista if _coincide_autor(p, autor_plegado)]
    if patogeno_plegado:
        lista = [p for p in lista if _coincide_patogeno(p, patogeno_plegado)]

    return tuple(lista)
