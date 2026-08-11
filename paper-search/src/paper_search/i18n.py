"""Traducción de los textos de cara al usuario.

Fuente única: `paper-search/i18n/<idioma>.json`, un diccionario plano
clave → texto, más `i18n/meta.json` con lo que no depende del idioma
(descripción de cada clave y orden de sus placeholders). De ahí salen tanto
las plantillas de la web como los `_locales/<idioma>/messages.json` de la
extensión de Chrome (ver `herramientas/generar_locales.py`): **un solo
diccionario, dos formatos**, nunca dos listas de traducciones que mantener.

Decisiones que explican la forma de estos archivos:

- **Claves en `snake_case` sin puntos.** `chrome.i18n` solo admite letras,
  números y `_` en los nombres de mensaje. Con claves tipo `form.boton` el
  generador tendría que transformarlas, y `a.b_c` y `a_b.c` colisionarían en
  `a_b_c` sin avisar. Así la clave viaja igual a los dos formatos.
- **Placeholders `$nombre$`.** Es la sintaxis nativa de `chrome.i18n`, así que
  el generador copia el mensaje literal, sin reescribirlo. Con `{nombre}`
  habría que convertir, y una llave literal dentro de un texto se corrompería
  en silencio.
- **Sin Babel ni gettext.** Añadirían una dependencia y un flujo `.po/.mo`, y
  convertir gettext a `messages.json` es más trabajo que JSON a JSON.

Fallback: si falta la clave en el idioma pedido se usa el de referencia
(`es`), y si tampoco está, se devuelve la clave. Nunca lanza: una traducción a
medias degrada el texto, no tumba la página.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from .config import RAIZ_COMPONENTE

#: Carpeta con la fuente de traducción.
RUTA_I18N = RAIZ_COMPONENTE / "i18n"

#: Idioma de referencia: el único que tiene que estar completo. Es también el
#: que se usa como fallback y el `default_locale` de la extensión de Chrome.
IDIOMA_REFERENCIA = "es"

#: Idiomas disponibles, en el orden en que se ofrecen en el selector.
IDIOMAS = ("es", "en")

#: Nombre de cada idioma en su propia lengua (para el conmutador).
NOMBRES_IDIOMA = {"es": "Español", "en": "English"}

#: `$nombre$` — placeholders con la sintaxis de chrome.i18n.
PATRON_PLACEHOLDER = re.compile(r"\$([a-z][a-z0-9_]*)\$")

#: Claves válidas en los dos formatos: chrome.i18n solo admite [A-Za-z0-9_].
PATRON_CLAVE = re.compile(r"^[a-z][a-z0-9_]{2,}$")


class I18nError(Exception):
    """La fuente de traducción no se pudo leer o está mal formada."""


@functools.lru_cache(maxsize=None)
def cargar_idioma(idioma: str) -> dict[str, str]:
    """Lee `i18n/<idioma>.json`. Cacheado: se lee una vez por proceso."""
    ruta = RUTA_I18N / f"{idioma}.json"
    if not ruta.is_file():
        if idioma == IDIOMA_REFERENCIA:
            raise I18nError(
                f"Falta la fuente de traducción de referencia: {ruta}. "
                f"Sin ella no hay textos que mostrar."
            )
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise I18nError(f"{ruta} no es JSON válido: {exc}") from exc
    if not isinstance(datos, dict):
        raise I18nError(f"{ruta} debe ser un objeto de clave → texto.")
    return {str(k): str(v) for k, v in datos.items()}


@functools.lru_cache(maxsize=None)
def cargar_meta() -> dict[str, dict]:
    """Lee `i18n/meta.json`: descripción y placeholders de cada clave."""
    ruta = RUTA_I18N / "meta.json"
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise I18nError(f"{ruta} no es JSON válido: {exc}") from exc
    return datos


def normalizar_idioma(idioma: str | None) -> str:
    """Idioma válido a partir de una entrada cualquiera, o el de referencia.

    Acepta `es-ES` o `EN` y se queda con la parte principal, para poder
    alimentarla directamente desde una cookie o un parámetro de URL sin
    validar antes.
    """
    if not idioma:
        return IDIOMA_REFERENCIA
    principal = str(idioma).strip().lower().replace("_", "-").split("-")[0]
    return principal if principal in IDIOMAS else IDIOMA_REFERENCIA


def sustituir(plantilla: str, valores: dict[str, object]) -> str:
    """Cambia `$nombre$` por su valor. Un placeholder sin valor se deja igual.

    Dejarlo visible es deliberado: un `$termino$` en pantalla se ve y se
    corrige, mientras que sustituirlo por vacío escondería el fallo.
    """

    def reemplazo(coincidencia: re.Match[str]) -> str:
        nombre = coincidencia.group(1)
        if nombre in valores:
            return str(valores[nombre])
        return coincidencia.group(0)

    return PATRON_PLACEHOLDER.sub(reemplazo, plantilla)


def traducir(clave: str, idioma: str = IDIOMA_REFERENCIA, /, **valores: object) -> str:
    """Devuelve el texto de `clave` en `idioma`, con sus placeholders puestos.

    Nunca lanza. El orden de fallback es: idioma pedido → idioma de referencia
    → la propia clave. Devolver la clave es a propósito: un `form_boton_buscar`
    en pantalla señala exactamente qué falta y dónde, mientras que un texto
    vacío pasaría desapercibido.
    """
    idioma = normalizar_idioma(idioma)

    texto = cargar_idioma(idioma).get(clave)
    if texto is None and idioma != IDIOMA_REFERENCIA:
        texto = cargar_idioma(IDIOMA_REFERENCIA).get(clave)
    if texto is None:
        return clave

    return sustituir(texto, valores) if valores else texto


def claves_disponibles(idioma: str = IDIOMA_REFERENCIA) -> set[str]:
    """Claves definidas en un idioma. La usan los tests y el generador."""
    return set(cargar_idioma(normalizar_idioma(idioma)))


def placeholders_de(clave: str) -> tuple[str, ...]:
    """Placeholders declarados para `clave` en `meta.json`, en orden.

    El orden es el que el generador convierte en `$1`, `$2`… de chrome.i18n.
    Se declara y no se infiere del texto para que una traducción que reordene
    los placeholders no desplace el mapeo posicional.
    """
    entrada = cargar_meta().get(clave) or {}
    return tuple(entrada.get("placeholders") or ())


def descripcion_de(clave: str) -> str:
    """Descripción de la clave (contexto para quien traduce)."""
    entrada = cargar_meta().get(clave) or {}
    return str(entrada.get("descripcion") or "")


def limpiar_cache() -> None:
    """Olvida lo leído. Solo la usan los tests que escriben fuentes falsas."""
    cargar_idioma.cache_clear()
    cargar_meta.cache_clear()
