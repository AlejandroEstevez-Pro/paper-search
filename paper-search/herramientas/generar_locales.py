"""Genera `_locales/<idioma>/messages.json` para la extensión de Chrome.

Toma la misma fuente de traducción que usa la web (`i18n/<idioma>.json`), así
que no hay dos diccionarios que mantener: se edita el JSON de siempre y se
vuelve a ejecutar esto.

    python herramientas/generar_locales.py
    python herramientas/generar_locales.py --salida ../chrome-extension/_locales
    python herramientas/generar_locales.py --comprobar

`--comprobar` no escribe nada: sale con código 1 si lo generado no coincide con
la fuente, para poder enterarse de que alguien tocó las traducciones y no
regeneró.

Recordatorio para la Fase 5.3: si la extensión trae `_locales/`, su
`manifest.json` tiene que declarar `"default_locale"`, y el valor que
corresponde aquí es el idioma de referencia (`es`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paper_search.i18n import IDIOMA_REFERENCIA, IDIOMAS  # noqa: E402
from paper_search.locales import (  # noqa: E402
    RUTA_LOCALES_POR_DEFECTO,
    GeneracionError,
    comprobar_al_dia,
    escribir_locales,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generar_locales",
        description=(
            "Genera los messages.json de chrome.i18n a partir de la fuente de "
            "traducción de paper-search (i18n/<idioma>.json)."
        ),
    )
    parser.add_argument(
        "--salida",
        default=None,
        help=f"Carpeta _locales de destino (por defecto {RUTA_LOCALES_POR_DEFECTO})",
    )
    parser.add_argument(
        "--comprobar",
        action="store_true",
        help="No escribe: solo comprueba si lo generado está al día (código 1 si no)",
    )
    args = parser.parse_args(argv)

    try:
        if args.comprobar:
            desfasados = comprobar_al_dia(args.salida)
            if desfasados:
                print(
                    "Los messages.json no coinciden con la fuente en: "
                    + ", ".join(desfasados)
                    + "\nEjecuta `python herramientas/generar_locales.py` para regenerarlos.",
                    file=sys.stderr,
                )
                return 1
            print(f"Al día: {', '.join(IDIOMAS)}")
            return 0

        escritos = escribir_locales(args.salida)
    except GeneracionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    for ruta in escritos:
        print(f"escrito {ruta}")
    print(f"default_locale para el manifest.json de la extensión: {IDIOMA_REFERENCIA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
