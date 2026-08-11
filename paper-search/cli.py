"""Interfaz de línea de comandos de paper-search.

Este módulo es solo argparse + impresión: toda la lógica vive en
`src/paper_search/`.

    python cli.py buscar "SCN1A" --max 15 --dias 365
    python cli.py buscar "síndrome de Dravet" --max 10 --formato json
    python cli.py buscar "Dravet syndrome" --autor "Scheffer IE" --orden relevancia
    python cli.py favoritos marcar 38123456 --nota "Revisar la tabla 2"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from paper_search import (  # noqa: E402  (tras ajustar sys.path)
    AVISO_NO_DIAGNOSTICO,
    DIAS_POR_DEFECTO,
    MAX_RESULTADOS_POR_DEFECTO,
    MENSAJE_FALTA_API_KEY,
    ORDEN_POR_DEFECTO,
    ORDENES,
    BaseDatosError,
    FavoritoError,
    Favoritos,
    LimiteAlcanzadoError,
    PaperSearchError,
    ResultadoBusqueda,
    TerminoFueraDeAlcanceError,
    abrir_db,
    buscar_y_resumir,
    cargar_env,
)
from paper_search.orden import ETIQUETAS as ETIQUETAS_ORDEN  # noqa: E402

# Códigos de salida: 0 correcto, 1 error de uso, 2 fallo de una API externa,
# 3 límite diario de uso alcanzado.
EXIT_OK = 0
EXIT_USO = 1
EXIT_FALLO_API = 2
EXIT_LIMITE = 3


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper-search",
        description=(
            "Busca en PubMed y resume los hallazgos recientes en lenguaje llano, "
            "siempre con el PMID de respaldo. NO es una herramienta de diagnóstico "
            "ni de asesoramiento médico."
        ),
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)

    buscar = subparsers.add_parser(
        "buscar",
        help="Busca artículos sobre un gen, síndrome o término libre.",
    )
    buscar.add_argument(
        "termino",
        nargs="?",
        default="",
        help="Gen o síndrome a buscar (p. ej. SCN1A)",
    )
    buscar.add_argument(
        "--autor",
        help=(
            "Filtra por autor (campo [AU] de PubMed, p. ej. «Scheffer IE»). "
            "El autor NO se le manda al filtro de alcance: un apellido no es "
            "un concepto médico."
        ),
    )
    buscar.add_argument(
        "--patogeno",
        help=(
            "Filtra por patógeno (p. ej. «Toxoplasma gondii»). Sí cuenta para "
            "el filtro de alcance, junto con el término."
        ),
    )
    buscar.add_argument(
        "--max",
        type=int,
        default=MAX_RESULTADOS_POR_DEFECTO,
        dest="max_resultados",
        help=f"Número máximo de papers a traer (por defecto {MAX_RESULTADOS_POR_DEFECTO})",
    )
    buscar.add_argument(
        "--dias",
        type=int,
        default=DIAS_POR_DEFECTO,
        help=f'Ventana de "recientes", en días (por defecto {DIAS_POR_DEFECTO})',
    )
    buscar.add_argument(
        "--orden",
        choices=ORDENES,
        default=ORDEN_POR_DEFECTO,
        help=(
            f"Criterio de ordenación de los resultados (por defecto "
            f"{ORDEN_POR_DEFECTO}). Se aplica en local: no cambia qué "
            f"artículos trae la búsqueda ni gasta llamadas de más."
        ),
    )
    buscar.add_argument(
        "--formato",
        choices=("texto", "json"),
        default="texto",
        help="Cómo imprimir el resultado (por defecto texto)",
    )
    buscar.add_argument(
        "--forzar",
        action="store_true",
        help=(
            "Regenera el resumen aunque haya uno vigente en la caché local "
            "(también ignora el veredicto de alcance cacheado)"
        ),
    )

    favoritos = subparsers.add_parser(
        "favoritos",
        help="Gestiona los papers marcados como favoritos.",
        description=(
            "Los favoritos se guardan en la base de datos local. Solo se pueden "
            "marcar papers que hayan aparecido en alguna búsqueda previa: sus "
            "datos ya están guardados, así que no se vuelve a consultar PubMed."
        ),
    )
    acciones = favoritos.add_subparsers(dest="accion", required=True)

    acciones.add_parser("listar", help="Lista los favoritos con sus notas.")

    marcar = acciones.add_parser("marcar", help="Marca un paper como favorito.")
    marcar.add_argument("pmid", help="PMID del paper (p. ej. 38123456)")
    marcar.add_argument("--nota", help="Nota personal opcional")

    desmarcar = acciones.add_parser(
        "desmarcar",
        help="Quita un paper de favoritos (y borra su nota).",
    )
    desmarcar.add_argument("pmid", help="PMID del paper")
    desmarcar.add_argument(
        "--si",
        action="store_true",
        help="No preguntar antes de borrar la nota asociada",
    )

    nota = acciones.add_parser("nota", help="Añade o edita la nota de un favorito.")
    nota.add_argument("pmid", help="PMID del paper")
    nota.add_argument("texto", nargs="?", help="Texto de la nota")
    nota.add_argument(
        "--borrar", action="store_true", help="Borra la nota, dejándola vacía"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    # Las claves que no estén exportadas se toman del .env, si existe. Lo
    # exportado en la terminal siempre tiene prioridad.
    cargar_env()

    parser = construir_parser()
    args = parser.parse_args(argv)

    if args.comando == "favoritos":
        return comando_favoritos(args)
    return comando_buscar(args, parser)


def comando_buscar(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.max_resultados <= 0:
        parser.error("--max debe ser mayor que 0")
    if args.dias <= 0:
        parser.error("--dias debe ser mayor que 0")
    if not (args.termino or args.autor or args.patogeno):
        parser.error(
            "hace falta al menos un criterio: un término, --autor o --patogeno"
        )

    # Comprobación única de la clave, al principio. Sin ella no tiene sentido
    # intentar el filtro de alcance ni el resumen (ambos usan la API de
    # Claude): se avisa UNA vez aquí y se pide solo la búsqueda de PubMed, en
    # vez de dejar que cada componente falle por su cuenta y repita el aviso.
    sin_clave = not os.environ.get("ANTHROPIC_API_KEY")
    if sin_clave:
        print(f"Aviso: {MENSAJE_FALTA_API_KEY}", file=sys.stderr)

    # La BD local (caché, límites, registro) es una comodidad: si no se puede
    # abrir se avisa y la búsqueda sigue sin persistencia, nunca en silencio.
    try:
        db = abrir_db()
    except BaseDatosError as exc:
        print(
            f"Aviso: {exc}\nSe continúa sin caché ni registro local.",
            file=sys.stderr,
        )
        db = None

    try:
        resultado = buscar_y_resumir(
            args.termino,
            autor=args.autor,
            patogeno=args.patogeno,
            max_resultados=args.max_resultados,
            dias=args.dias,
            orden=args.orden,
            resumir=not sin_clave,
            verificar_alcance=not sin_clave,
            db=db,
            forzar=args.forzar,
        )
    except LimiteAlcanzadoError as exc:
        # El mensaje ya dice qué límite se alcanzó y cuándo se resetea.
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_LIMITE
    except TerminoFueraDeAlcanceError as exc:
        # Término fuera del alcance (enfermedades raras): no es un fallo de
        # las APIs sino de la entrada, así que sale con el código de uso.
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USO
    except PaperSearchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FALLO_API
    except KeyboardInterrupt:  # pragma: no cover - interacción manual
        print("\nBúsqueda cancelada.", file=sys.stderr)
        return EXIT_FALLO_API
    finally:
        if db is not None:
            db.close()

    if args.formato == "json":
        print(json.dumps(resultado.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(formatear_texto(resultado))

    if resultado.error_resumen:
        print(f"\nError: {resultado.error_resumen}", file=sys.stderr)
        return EXIT_FALLO_API
    if sin_clave:
        # El aviso ya salió al principio; el código de salida sigue señalando
        # que no hubo resumen, igual que antes de consolidar el aviso.
        return EXIT_FALLO_API
    return EXIT_OK


def formatear_texto(resultado: ResultadoBusqueda) -> str:
    """Renderiza el resultado en modo texto: resumen + referencias."""
    lineas: list[str] = []
    lineas.append(f'Búsqueda: "{resultado.query}"')
    if resultado.dias:
        lineas.append(
            f"Artículos encontrados: {resultado.total} "
            f"(publicados en los últimos {resultado.dias} días)"
        )
        lineas.append(f"Orden: {ETIQUETAS_ORDEN.get(resultado.orden, resultado.orden)}")
    else:
        lineas.append(f"Artículos encontrados: {resultado.total}")
    lineas.append("")

    if resultado.aviso_idioma:
        lineas.append(f"AVISO DE IDIOMA: {resultado.aviso_idioma}")
        lineas.append("")

    if resultado.aviso_alcance:
        lineas.append(f"AVISO DE ALCANCE: {resultado.aviso_alcance}")
        lineas.append("")

    if resultado.total == 0:
        lineas.append(
            "PubMed no ha devuelto ningún artículo para este término y esta "
            "ventana temporal."
        )
        lineas.append(
            "Prueba a ampliar --dias, a subir --max o a usar otro término "
            "(por ejemplo el nombre del gen en vez del síndrome)."
        )
        lineas.append("")
        lineas.append(resultado.aviso)
        return "\n".join(lineas)

    lineas.append("=" * 72)
    lineas.append("RESUMEN")
    lineas.append("=" * 72)
    if resultado.desde_cache:
        lineas.append(
            f"(Servido desde la caché local — generado originalmente el "
            f"{_fecha_legible(resultado.cache_creado_en)}. "
            f"Usa --forzar para regenerarlo.)"
        )
        lineas.append("")
    if resultado.resumen:
        lineas.append(resultado.resumen)
    elif resultado.error_resumen:
        lineas.append(
            "No se ha generado resumen. Motivo:\n"
            f"{resultado.error_resumen}\n\n"
            "Las referencias de abajo vienen directamente de PubMed y son "
            "verificables por su PMID."
        )
    else:
        # Sin resumen y sin motivo propio: no se pidió (p. ej. falta la clave
        # de la API, avisado ya al inicio de la ejecución).
        lineas.append(
            "No se ha generado resumen para esta búsqueda (ver el aviso del "
            "inicio). Las referencias de abajo vienen directamente de PubMed "
            "y son verificables por su PMID."
        )
    lineas.append("")

    lineas.append("=" * 72)
    lineas.append(f"REFERENCIAS ({resultado.total})")
    lineas.append("=" * 72)
    for i, paper in enumerate(resultado.papers, start=1):
        lineas.append(f"[{i}] {paper.titulo}")
        cabecera = paper.autores_texto
        detalle = " · ".join(
            parte for parte in (paper.revista, paper.anio or paper.fecha) if parte
        )
        if detalle:
            cabecera = f"{cabecera} — {detalle}"
        lineas.append(f"    {cabecera}")
        lineas.append(f"    PMID {paper.pmid} — {paper.url}")
        lineas.append("")

    lineas.append(resultado.aviso)
    return "\n".join(lineas)


# --------------------------------------------------------------- favoritos


def comando_favoritos(args: argparse.Namespace) -> int:
    """Listar, marcar, desmarcar y anotar favoritos.

    A diferencia de `buscar`, aquí la base de datos local no es una comodidad
    sino el sitio donde viven los favoritos: si no se puede abrir, no hay nada
    que hacer y se dice, en vez de continuar como si nada.
    """
    try:
        db = abrir_db()
    except BaseDatosError as exc:
        print(
            f"Error: {exc}\nLos favoritos se guardan en esa base de datos, "
            f"así que no se puede continuar.",
            file=sys.stderr,
        )
        return EXIT_FALLO_API

    favoritos = Favoritos(db)
    try:
        if args.accion == "listar":
            return _favoritos_listar(favoritos)
        if args.accion == "marcar":
            return _favoritos_marcar(favoritos, args)
        if args.accion == "desmarcar":
            return _favoritos_desmarcar(favoritos, args)
        return _favoritos_nota(favoritos, args)
    except FavoritoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USO
    except PaperSearchError as exc:  # pragma: no cover - defensivo
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FALLO_API
    finally:
        db.close()


def _favoritos_listar(favoritos: Favoritos) -> int:
    lista = favoritos.listar()
    if not lista:
        print(
            "No tienes ningún paper en favoritos todavía.\n"
            "Marca uno con: python cli.py favoritos marcar <PMID>"
        )
        return EXIT_OK

    print(f"FAVORITOS ({len(lista)})")
    print("=" * 72)
    for i, favorito in enumerate(lista, start=1):
        paper = favorito.paper
        print(f"[{i}] {paper.titulo}")
        detalle = " · ".join(
            parte for parte in (paper.revista, paper.anio or paper.fecha) if parte
        )
        cabecera = paper.autores_texto
        if detalle:
            cabecera = f"{cabecera} — {detalle}"
        print(f"    {cabecera}")
        print(f"    PMID {paper.pmid} — {paper.url}")
        if favorito.tiene_nota:
            print(f"    Nota: {favorito.nota}")
        print(f"    Marcado el {_fecha_legible(favorito.creado_en)}")
        print()
    print(AVISO_NO_DIAGNOSTICO)
    return EXIT_OK


def _favoritos_marcar(favoritos: Favoritos, args: argparse.Namespace) -> int:
    favorito = favoritos.marcar(args.pmid, nota=args.nota)
    print(f"Marcado como favorito: {favorito.paper.titulo}")
    print(f"PMID {favorito.pmid} — {favorito.paper.url}")
    if favorito.tiene_nota:
        print(f"Nota: {favorito.nota}")
    return EXIT_OK


def _favoritos_desmarcar(favoritos: Favoritos, args: argparse.Namespace) -> int:
    favorito = favoritos.obtener(args.pmid)
    if favorito is None:
        print(f"El PMID {args.pmid} no estaba en favoritos. No se ha cambiado nada.")
        return EXIT_OK

    # Solo se pregunta si hay algo que perder: la nota. Quitar un favorito sin
    # nota se deshace volviendo a marcarlo.
    if favorito.tiene_nota and not args.si:
        print(f"Este favorito tiene una nota, que se borrará:\n  «{favorito.nota}»")
        if not _confirmar("¿Seguro que quieres desmarcarlo? [s/N]: "):
            print("Cancelado. El favorito y su nota siguen ahí.")
            return EXIT_OK

    favoritos.desmarcar(args.pmid)
    print(f"Quitado de favoritos: PMID {args.pmid}")
    return EXIT_OK


def _favoritos_nota(favoritos: Favoritos, args: argparse.Namespace) -> int:
    if args.borrar:
        texto = None
    elif args.texto is not None:
        texto = args.texto
    else:
        print(
            "Error: hace falta el texto de la nota, o --borrar para dejarla "
            "vacía.",
            file=sys.stderr,
        )
        return EXIT_USO

    favorito = favoritos.anotar(args.pmid, texto)
    if favorito.tiene_nota:
        print(f"Nota guardada en el PMID {favorito.pmid}:\n  «{favorito.nota}»")
    else:
        print(f"Nota borrada del PMID {favorito.pmid}.")
    return EXIT_OK


def _confirmar(pregunta: str) -> bool:
    """Pregunta sí/no. Sin terminal interactiva responde que NO, por seguridad."""
    if not sys.stdin.isatty():
        print(
            "(no hay terminal interactiva: no se desmarca nada; usa --si para "
            "confirmarlo sin preguntar)"
        )
        return False
    try:
        respuesta = input(pregunta)
    except EOFError:  # pragma: no cover - depende del entorno
        return False
    return respuesta.strip().lower() in ("s", "si", "sí")


def _fecha_legible(iso: str | None) -> str:
    """`2026-08-10T14:03:00+00:00` → `2026-08-10 14:03 UTC` (para humanos)."""
    if not iso:
        return "fecha desconocida"
    return f"{iso[:10]} {iso[11:16]} UTC"


if __name__ == "__main__":
    raise SystemExit(main())
