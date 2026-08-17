"""Genera los PNG del icono a partir del SVG.

El SVG (`static/iconos/paper-search-icon.svg`) es la fuente; los PNG son
derivados, y existen solo porque el manifest de la PWA los necesita en tamaños
concretos. Si se retoca el icono, se retoca el SVG y se vuelve a ejecutar esto.

    python herramientas/generar_iconos.py
    python herramientas/generar_iconos.py --comprobar

El SVG se **parsea**, no se reimplementa: así los PNG no pueden quedar
desalineados del original por una copia a mano que se olvidó de actualizar. El
renderizador solo entiende los primitivos que usa este icono (rect con esquinas
opcionales, círculo con trazo, línea con trazo y cabeza redonda) y **falla si
encuentra otro**, en vez de dibujar de menos sin avisar.

Pillow se usa solo aquí, para generar. Los PNG van commiteados, así que no
hace falta en tiempo de ejecución y no entra en requirements.txt.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "static" / "iconos"
SVG = CARPETA / "paper-search-icon.svg"

SVG_NS = "{http://www.w3.org/2000/svg}"

#: Se dibuja a este múltiplo y se reduce: antialiasing sin depender de nada más.
SUPERMUESTREO = 4

#: Lo que pide el manifest. `maskable` va a sangre —sin esquinas redondeadas—
#: porque el sistema operativo le aplica su propia máscara: dejar las esquinas
#: redondas del SVG haría que se recortasen dos veces.
SALIDAS = (
    ("icono-192.png", 192, True),
    ("icono-512.png", 512, True),
    ("icono-maskable-512.png", 512, False),
)


class IconoError(Exception):
    """El SVG tiene algo que este renderizador no sabe dibujar."""


def _color(valor: str):
    valor = (valor or "").strip().lstrip("#")
    if len(valor) != 6:
        raise IconoError(f"Color no reconocido: {valor!r}. Se espera #rrggbb.")
    return tuple(int(valor[i : i + 2], 16) for i in (0, 2, 4)) + (255,)


def _num(elemento, atributo, heredado=None, por_defecto=None):
    valor = elemento.get(atributo, heredado)
    if valor is None:
        if por_defecto is None:
            raise IconoError(f"Falta el atributo «{atributo}» en <{elemento.tag}>.")
        return por_defecto
    return float(valor)


def dibujar(destino, lado: int, esquinas_redondeadas: bool):
    """Rasteriza el SVG en un lienzo de `lado` px."""
    from PIL import Image, ImageDraw

    raiz = ET.parse(SVG).getroot()
    caja = [float(v) for v in raiz.get("viewBox", "0 0 512 512").split()]
    lienzo = caja[2]

    px = lado * SUPERMUESTREO
    escala = px / lienzo
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    lapiz = ImageDraw.Draw(img)

    def e(valor):  # a coordenadas del lienzo ampliado
        return valor * escala

    def recorrer(nodo, relleno=None, trazo=None, grosor=None):
        relleno = nodo.get("fill", relleno)
        trazo = nodo.get("stroke", trazo)
        grosor = nodo.get("stroke-width", grosor)

        etiqueta = nodo.tag.replace(SVG_NS, "")

        if etiqueta in ("svg", "g"):
            for hijo in nodo:
                recorrer(hijo, relleno, trazo, grosor)
            return

        if etiqueta == "rect":
            x, y = _num(nodo, "x", por_defecto=0), _num(nodo, "y", por_defecto=0)
            ancho, alto = _num(nodo, "width"), _num(nodo, "height")
            rx = _num(nodo, "rx", por_defecto=0)
            caja_px = [e(x), e(y), e(x + ancho) - 1, e(y + alto) - 1]
            if rx and esquinas_redondeadas:
                lapiz.rounded_rectangle(caja_px, radius=e(rx), fill=_color(relleno))
            else:
                lapiz.rectangle(caja_px, fill=_color(relleno))
            return

        if etiqueta == "circle":
            cx, cy, r = _num(nodo, "cx"), _num(nodo, "cy"), _num(nodo, "r")
            ancho_trazo = e(float(grosor))
            lapiz.ellipse(
                [e(cx - r), e(cy - r), e(cx + r), e(cy + r)],
                outline=_color(trazo),
                width=round(ancho_trazo),
            )
            return

        if etiqueta == "line":
            x1, y1 = _num(nodo, "x1"), _num(nodo, "y1")
            x2, y2 = _num(nodo, "x2"), _num(nodo, "y2")
            ancho_trazo = e(float(grosor))
            color = _color(trazo)
            lapiz.line([e(x1), e(y1), e(x2), e(y2)], fill=color, width=round(ancho_trazo))
            # `stroke-linecap="round"`: PIL no tiene cabezas redondas, así que se
            # ponen a mano. Sin esto el mango acabaría en pico y el icono
            # rebasaría el margen de seguridad calculado para la máscara.
            radio = ancho_trazo / 2
            for cx, cy in ((e(x1), e(y1)), (e(x2), e(y2))):
                lapiz.ellipse([cx - radio, cy - radio, cx + radio, cy + radio], fill=color)
            return

        raise IconoError(
            f"El SVG usa <{etiqueta}>, que este generador no sabe dibujar. "
            f"Añádelo aquí o usa un rasterizador de SVG de verdad."
        )

    recorrer(raiz)
    img.resize((lado, lado), Image.LANCZOS).save(destino, "PNG", optimize=True)


def generar() -> list[Path]:
    escritos = []
    for nombre, lado, redondeadas in SALIDAS:
        destino = CARPETA / nombre
        dibujar(destino, lado, redondeadas)
        escritos.append(destino)
    return escritos


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="generar_iconos", description=__doc__)
    parser.add_argument(
        "--comprobar",
        action="store_true",
        help="No escribe: comprueba que los PNG coinciden con el SVG (código 1 si no)",
    )
    args = parser.parse_args(argv)

    if args.comprobar:
        import tempfile

        desfasados = []
        with tempfile.TemporaryDirectory() as tmp:
            for nombre, lado, redondeadas in SALIDAS:
                esperado = Path(tmp) / nombre
                dibujar(esperado, lado, redondeadas)
                actual = CARPETA / nombre
                if not actual.is_file() or actual.read_bytes() != esperado.read_bytes():
                    desfasados.append(nombre)
        if desfasados:
            print(
                "Estos PNG no coinciden con el SVG: " + ", ".join(desfasados)
                + "\nEjecuta `python herramientas/generar_iconos.py`.",
                file=sys.stderr,
            )
            return 1
        print("Al día: " + ", ".join(n for n, _, _ in SALIDAS))
        return 0

    for ruta in generar():
        print(f"escrito {ruta.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
