"""Favoritos: papers marcados por el usuario, con una nota personal opcional.

Se apoya en la tabla `papers`, que la Fase 2 ya rellena en cada búsqueda (ver
`registro.py`). Por eso marcar un favorito **no vuelve a consultar PubMed**:
los metadatos ya están en local, y listar favoritos es un JOIN.

La consecuencia de ese diseño es que solo se puede marcar lo que haya salido
antes en alguna búsqueda. No es una limitación accidental: un favorito con un
PMID que nadie ha visto no tendría ni título que enseñar. Lo impide la clave
ajena de la migración v2 (`PRAGMA foreign_keys = ON` está activo desde
`abrir_db`), y aquí se traduce a un `FavoritoError` con mensaje claro.

`nota` es NULL cuando no hay nota, nunca la cadena vacía: así "sin nota" tiene
una sola representación posible. Desmarcar borra la fila y con ella la nota
(decisión registrada en docs/decisions.md); quien llama es responsable de pedir
confirmación antes, que es lo que hacen la CLI y la web.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from .db import ahora_utc_iso
from .i18n import IDIOMA_REFERENCIA, traducir
from .models import Paper, PaperSearchError


class FavoritoError(PaperSearchError):
    """No se pudo marcar o anotar un favorito (PMID desconocido, etc.)."""


@dataclass(frozen=True)
class Favorito:
    """Un paper marcado, con su nota y los metadatos que ya teníamos."""

    paper: Paper
    nota: str | None
    creado_en: str
    actualizado_en: str

    @property
    def pmid(self) -> str:
        return self.paper.pmid

    @property
    def tiene_nota(self) -> bool:
        return bool(self.nota and self.nota.strip())

    def to_dict(self) -> dict:
        return {
            **self.paper.to_dict(),
            "nota": self.nota,
            "creado_en": self.creado_en,
            "actualizado_en": self.actualizado_en,
        }


def _limpiar_nota(nota: str | None) -> str | None:
    """Normaliza la nota: vacía o solo espacios se guarda como NULL."""
    if nota is None:
        return None
    limpia = nota.strip()
    return limpia or None


class Favoritos:
    """Operaciones sobre la tabla `favoritos`."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        ahora: Callable[[], str] = ahora_utc_iso,
        idioma: str = IDIOMA_REFERENCIA,
    ) -> None:
        self.conn = conn
        self._ahora = ahora
        # Idioma de los mensajes de error de cara al usuario. Por defecto el de
        # referencia, así que la CLI no cambia; la web pasa el idioma activo.
        self.idioma = idioma

    # ------------------------------------------------------------- consultas

    def es_favorito(self, pmid: str) -> bool:
        fila = self.conn.execute(
            "SELECT 1 FROM favoritos WHERE pmid = ?", (str(pmid).strip(),)
        ).fetchone()
        return fila is not None

    def pmids(self) -> set[str]:
        """PMIDs marcados. La usa la web para pintar el botón de cada fila."""
        return {
            fila["pmid"] for fila in self.conn.execute("SELECT pmid FROM favoritos")
        }

    def listar(self) -> list[Favorito]:
        """Favoritos con sus metadatos, del más reciente al más antiguo.

        Sale de un JOIN con `papers`: no se consulta PubMed en ningún caso.
        """
        filas = self.conn.execute(
            "SELECT f.pmid, f.nota, f.creado_en, f.actualizado_en, "
            "       p.titulo, p.autores, p.revista, p.fecha, p.abstract "
            "FROM favoritos f "
            "JOIN papers p ON p.pmid = f.pmid "
            "ORDER BY f.creado_en DESC, f.pmid DESC"
        ).fetchall()
        return [_fila_a_favorito(fila) for fila in filas]

    def obtener(self, pmid: str) -> Favorito | None:
        pmid = str(pmid).strip()
        fila = self.conn.execute(
            "SELECT f.pmid, f.nota, f.creado_en, f.actualizado_en, "
            "       p.titulo, p.autores, p.revista, p.fecha, p.abstract "
            "FROM favoritos f "
            "JOIN papers p ON p.pmid = f.pmid "
            "WHERE f.pmid = ?",
            (pmid,),
        ).fetchone()
        return _fila_a_favorito(fila) if fila is not None else None

    # ---------------------------------------------------------- modificación

    def marcar(self, pmid: str, nota: str | None = None) -> Favorito:
        """Marca un paper como favorito. Idempotente: re-marcar no duplica.

        Lanza `FavoritoError` si el PMID no está en `papers`, es decir, si no
        ha salido en ninguna búsqueda previa.
        """
        pmid = _exigir_pmid(pmid, self.idioma)
        ahora = self._ahora()
        nota_limpia = _limpiar_nota(nota)
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO favoritos (pmid, nota, creado_en, actualizado_en) "
                    "VALUES (?, ?, ?, ?) "
                    # Re-marcar no reinicia `creado_en` ni pisa la nota que ya
                    # hubiera, salvo que se pase una nueva explícitamente.
                    "ON CONFLICT (pmid) DO UPDATE SET "
                    "  nota = COALESCE(excluded.nota, favoritos.nota), "
                    "  actualizado_en = excluded.actualizado_en",
                    (pmid, nota_limpia, ahora, ahora),
                )
        except sqlite3.IntegrityError as exc:
            raise FavoritoError(
                traducir("fav_err_pmid_desconocido", self.idioma, pmid=pmid)
            ) from exc

        favorito = self.obtener(pmid)
        if favorito is None:  # pragma: no cover - imposible tras el INSERT
            raise FavoritoError(f"No se pudo releer el favorito {pmid}.")
        return favorito

    def desmarcar(self, pmid: str) -> bool:
        """Quita el favorito (y su nota). Devuelve si había algo que quitar."""
        pmid = _exigir_pmid(pmid, self.idioma)
        with self.conn:
            cursor = self.conn.execute("DELETE FROM favoritos WHERE pmid = ?", (pmid,))
        return cursor.rowcount > 0

    def anotar(self, pmid: str, nota: str | None) -> Favorito:
        """Escribe o reemplaza la nota de un favorito ya marcado.

        Una nota vacía la borra (queda NULL). Lanza `FavoritoError` si el paper
        no está marcado: anotar no marca por su cuenta, para que no se creen
        favoritos por escribir una nota de más.
        """
        pmid = _exigir_pmid(pmid, self.idioma)
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE favoritos SET nota = ?, actualizado_en = ? WHERE pmid = ?",
                (_limpiar_nota(nota), self._ahora(), pmid),
            )
        if cursor.rowcount == 0:
            raise FavoritoError(
                traducir("fav_err_no_marcado", self.idioma, pmid=pmid)
            )
        favorito = self.obtener(pmid)
        if favorito is None:  # pragma: no cover - imposible tras el UPDATE
            raise FavoritoError(f"No se pudo releer el favorito {pmid}.")
        return favorito


def _exigir_pmid(pmid: str, idioma: str = IDIOMA_REFERENCIA) -> str:
    limpio = str(pmid or "").strip()
    if not limpio:
        raise FavoritoError(traducir("fav_err_pmid_vacio", idioma))
    if not limpio.isdigit():
        raise FavoritoError(traducir("fav_err_pmid_invalido", idioma, pmid=limpio))
    return limpio


def _fila_a_favorito(fila: sqlite3.Row) -> Favorito:
    try:
        autores = tuple(json.loads(fila["autores"]))
    except (ValueError, TypeError):  # pragma: no cover - datos corruptos
        autores = ()
    return Favorito(
        paper=Paper(
            pmid=fila["pmid"],
            titulo=fila["titulo"],
            autores=autores,
            revista=fila["revista"],
            fecha=fila["fecha"],
            abstract=fila["abstract"],
        ),
        nota=fila["nota"],
        creado_en=fila["creado_en"],
        actualizado_en=fila["actualizado_en"],
    )
