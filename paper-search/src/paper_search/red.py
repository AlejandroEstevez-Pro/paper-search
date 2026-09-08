"""Modo de red local: llegar a paper-search desde el móvil de la misma wifi.

Por defecto el servidor escucha **solo en 127.0.0.1**, que únicamente alcanza
el propio equipo. Este módulo permite abrirlo al resto de la red local, pero
nunca por defecto: hay que pedirlo a propósito con `--red` (o
`PAPER_SEARCH_RED=1`), porque exponer el servidor a toda la wifi no debe
ocurrir por descuido.

Lo que se está aceptando al activarlo, y por eso se avisa en consola y no solo
en el README:

- **No hay autenticación de ningún tipo.** Cualquiera en esa wifi que sepa la
  IP entra, sin contraseña.
- Puede **leer tus favoritos y sus notas personales**, y el registro de todo lo
  que has buscado. Es información médica y personal.
- Puede **lanzar búsquedas que gastan tu clave de la API de Claude** y tu cuota
  diaria: cuesta dinero de verdad.

Nada de esto es un fallo del programa: es lo que significa abrir un servidor
sin autenticación a una red compartida. Por eso el modo está apagado por
defecto y por eso el aviso es difícil de pasar por alto.
"""

from __future__ import annotations

import ipaddress
import socket

#: Solo este equipo. Es el comportamiento por defecto y el que debe seguir
#: siéndolo.
HOST_LOCAL = "127.0.0.1"

#: Todas las interfaces: lo que hace falta para que el móvil pueda entrar.
HOST_TODAS = "0.0.0.0"

#: Variable de entorno que activa el modo, como alternativa al flag para
#: quien arranque con `flask run` y no con `python app.py`.
VARIABLE_RED = "PAPER_SEARCH_RED"

#: Flag de línea de comandos. Es la forma recomendada: vale para un arranque
#: concreto y no se queda puesta en un archivo, que es justo lo que hace que
#: algo así se active sin querer.
FLAG_RED = "--red"

#: Valores que cuentan como "sí" en la variable de entorno.
VALORES_SI = frozenset({"1", "true", "si", "sí", "yes", "on"})

#: Dirección de la red de documentación (RFC 5737). Se usa solo para que el
#: sistema operativo elija una interfaz de salida: con UDP, `connect` no envía
#: ni un paquete. Se prefiere a una IP real de un tercero para no dar a
#: entender que se contacta con nadie.
_DESTINO_FICTICIO = ("192.0.2.1", 1)


class RedError(Exception):
    """No se pudo averiguar la IP local de este equipo."""


def modo_red_activado(argv=None, entorno=None) -> bool:
    """¿Hay que escuchar en toda la red? Por defecto, NO.

    Se mira el flag y la variable de entorno. Cualquier otra cosa —incluido no
    decir nada— significa quedarse en 127.0.0.1.
    """
    argv = list(argv or [])
    entorno = entorno if entorno is not None else {}

    if FLAG_RED in argv:
        return True

    valor = str(entorno.get(VARIABLE_RED, "")).strip().lower()
    return valor in VALORES_SI


def host_para(activado: bool) -> str:
    """La interfaz en la que escuchar."""
    return HOST_TODAS if activado else HOST_LOCAL


def ip_local() -> str:
    """IP de este equipo en la red local, p. ej. `192.168.1.42`.

    Se abre un socket UDP «hacia» una dirección externa y se lee qué dirección
    de origen le asigna el sistema: eso devuelve la interfaz de la ruta por
    defecto, que es la que ve el móvil. No se envía ningún paquete ni se
    contacta con nadie.

    Se evita `gethostbyname(gethostname())` a propósito: devuelve 127.0.0.1 en
    muchas configuraciones de Linux, y en un portátil con VPN o con
    adaptadores virtuales suele devolver la interfaz equivocada — y una IP
    equivocada en pantalla es peor que no dar ninguna, porque manda a la
    persona a probar una dirección que no va a funcionar.

    Lanza `RedError` con un mensaje que explica qué hacer si no se puede.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(_DESTINO_FICTICIO)
        direccion = sock.getsockname()[0]
    except OSError as exc:
        raise RedError(
            "No se ha podido averiguar la IP de este equipo en la red local "
            f"({exc.__class__.__name__}: {exc}). Comprueba que estás conectado "
            "a la wifi. Puedes mirarla a mano con `ipconfig` (Windows) o "
            "`ip addr` (Linux/macOS) y usarla directamente."
        ) from exc
    finally:
        sock.close()

    try:
        analizada = ipaddress.ip_address(direccion)
    except ValueError as exc:
        raise RedError(
            f"El sistema devolvió «{direccion}», que no es una dirección IP "
            f"válida. Mírala a mano con `ipconfig` o `ip addr`."
        ) from exc

    if analizada.is_loopback:
        raise RedError(
            "Este equipo solo tiene dirección de loopback (127.0.0.1), así que "
            "no hay ninguna IP por la que el móvil pueda entrar. Conéctate a "
            "la wifi y vuelve a intentarlo."
        )

    return direccion


def url_para_el_movil(puerto: int) -> str:
    """La URL exacta que hay que escribir en el móvil."""
    return f"http://{ip_local()}:{puerto}"


def texto_arranque(puerto: int, activado: bool) -> str:
    """Lo que se imprime en consola al arrancar.

    En modo normal, una línea. En modo red, la URL para el móvil y la
    advertencia — con el detalle de qué queda expuesto, no un «ten cuidado»
    genérico que nadie lee.
    """
    if not activado:
        return (
            f"paper-search — servidor local en http://{HOST_LOCAL}:{puerto}\n"
            "Cierra esta ventana (o pulsa Ctrl+C) para detenerlo."
        )

    try:
        url = url_para_el_movil(puerto)
        linea_url = f"  Desde el móvil, abre:  {url}"
    except RedError as exc:
        # Que no se sepa la IP no impide arrancar: el servidor ya está
        # escuchando en toda la red, así que el aviso tiene que salir igual.
        linea_url = f"  No se ha podido detectar la IP de este equipo.\n  {exc}"

    regla = "=" * 68
    return "\n".join([
        f"paper-search — servidor local en http://{HOST_LOCAL}:{puerto}",
        "",
        regla,
        "  MODO RED LOCAL ACTIVADO — el servidor es accesible desde toda la wifi",
        regla,
        linea_url,
        "",
        "  Cualquiera conectado a esta red puede entrar. NO hay contraseña:",
        "    · puede leer tus favoritos y tus notas personales,",
        "    · puede ver todo lo que has buscado,",
        "    · puede lanzar búsquedas que gastan tu clave de la API y tu",
        "      cuota diaria, y eso cuesta dinero.",
        "",
        "  Úsalo solo en una red de confianza y apágalo cuando termines:",
        f"  sin {FLAG_RED} vuelve a escuchar solo en este equipo.",
        regla,
        "",
        "Cierra esta ventana (o pulsa Ctrl+C) para detenerlo.",
    ])
