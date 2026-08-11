"""Generador del formato `chrome.i18n` a partir de la fuente de traducción.

La extensión de Chrome de la Fase 5.3 necesita las mismas cadenas que la web,
pero en `_locales/<idioma>/messages.json`, que es un formato distinto:

    {
      "alc_aviso_ambiguo": {
        "message": "El término «$termino$» … : $motivo$ …",
        "description": "Aviso cuando …",
        "placeholders": {
          "termino": { "content": "$1" },
          "motivo":  { "content": "$2" }
        }
      }
    }

Este módulo lo produce **desde `i18n/<idioma>.json`**, sin copiar ni reescribir
ningún texto: `message` es literalmente el valor de la fuente. Por eso los
placeholders se escriben ya como `$nombre$` (la sintaxis de chrome.i18n) y las
claves en `snake_case` sin puntos (lo único que admite chrome.i18n): así no
hay transformación que pueda corromper un texto o colisionar dos claves.

Lo único que sí se construye aquí es el bloque `placeholders`, que mapea cada
nombre a su posición `$1`, `$2`… La posición sale del orden declarado en
`meta.json`, no del orden de aparición en el texto, para que una traducción que
reordene los placeholders siga apuntando al argumento correcto.

Uso desde la línea de comandos:

    python herramientas/generar_locales.py            # a paper-search/_locales/
    python herramientas/generar_locales.py --salida ../chrome-extension/_locales
    python herramientas/generar_locales.py --comprobar   # ¿está al día?
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import RAIZ_COMPONENTE
from .i18n import (
    IDIOMA_REFERENCIA,
    IDIOMAS,
    PATRON_CLAVE,
    PATRON_PLACEHOLDER,
    cargar_idioma,
    descripcion_de,
    placeholders_de,
)

#: Destino por defecto. La extensión de la Fase 5.3 puede apuntar aquí o pedir
#: otra ruta con `--salida`: la fuente no se mueve por eso.
RUTA_LOCALES_POR_DEFECTO = RAIZ_COMPONENTE / "_locales"


class GeneracionError(Exception):
    """La fuente no se puede convertir a formato chrome.i18n."""


def _validar_clave(clave: str) -> None:
    if not PATRON_CLAVE.match(clave):
        raise GeneracionError(
            f"La clave «{clave}» no vale para chrome.i18n, que solo admite "
            f"letras, números y guion bajo. Renómbrala en i18n/*.json."
        )


def mensaje_chrome(clave: str, texto: str) -> dict:
    """Convierte una entrada de la fuente en una entrada de messages.json."""
    _validar_clave(clave)

    entrada: dict[str, object] = {"message": texto}

    descripcion = descripcion_de(clave)
    if descripcion:
        entrada["description"] = descripcion

    declarados = placeholders_de(clave)
    usados = set(PATRON_PLACEHOLDER.findall(texto))
    sin_declarar = usados - set(declarados)
    if sin_declarar:
        raise GeneracionError(
            f"La clave «{clave}» usa los placeholders {sorted(sin_declarar)} "
            f"pero no están declarados en i18n/meta.json. Sin declararlos, "
            f"chrome.i18n los mostraría literales."
        )

    if declarados:
        # `content: "$N$"` es la posición en la lista de sustituciones que
        # recibe chrome.i18n.getMessage(clave, [v1, v2, ...]).
        entrada["placeholders"] = {
            nombre: {"content": f"${indice}"}
            for indice, nombre in enumerate(declarados, start=1)
        }

    return entrada


def generar_messages(idioma: str) -> dict:
    """`messages.json` completo de un idioma, como diccionario.

    Un idioma incompleto se completa con el de referencia: la extensión no
    debe quedarse con huecos, y es el mismo fallback que aplica la web.
    """
    referencia = cargar_idioma(IDIOMA_REFERENCIA)
    propio = cargar_idioma(idioma)
    if not referencia:
        raise GeneracionError(
            "La fuente de traducción de referencia está vacía: no hay nada que generar."
        )

    return {
        clave: mensaje_chrome(clave, propio.get(clave, texto_ref))
        for clave, texto_ref in sorted(referencia.items())
    }


def escribir_locales(
    salida: Path | str | None = None, idiomas: tuple[str, ...] = IDIOMAS
) -> list[Path]:
    """Escribe `<salida>/<idioma>/messages.json`. Devuelve las rutas escritas."""
    raiz = Path(salida) if salida is not None else RUTA_LOCALES_POR_DEFECTO
    escritos: list[Path] = []
    for idioma in idiomas:
        carpeta = raiz / idioma
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / "messages.json"
        ruta.write_text(_serializar(generar_messages(idioma)), encoding="utf-8")
        escritos.append(ruta)
    return escritos


def _serializar(datos: dict) -> str:
    """JSON con acentos legibles y salto final, para que el diff sea limpio."""
    return json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def comprobar_al_dia(
    salida: Path | str | None = None, idiomas: tuple[str, ...] = IDIOMAS
) -> list[str]:
    """Devuelve los idiomas cuyo `messages.json` no coincide con la fuente.

    Lista vacía significa que lo generado está al día. Sirve para que un
    control de calidad detecte que alguien tocó `i18n/*.json` sin regenerar.
    """
    raiz = Path(salida) if salida is not None else RUTA_LOCALES_POR_DEFECTO
    desfasados: list[str] = []
    for idioma in idiomas:
        ruta = raiz / idioma / "messages.json"
        esperado = _serializar(generar_messages(idioma))
        if not ruta.is_file() or ruta.read_text(encoding="utf-8") != esperado:
            desfasados.append(idioma)
    return desfasados
