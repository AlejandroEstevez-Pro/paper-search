"""Política de caché de la PWA.

La decisión de **qué estrategia le toca a cada petición** vive aquí, en Python,
y no dentro del service worker. Motivo práctico: sin un navegador (ni Node) en
la suite, el JavaScript del service worker no se puede ejecutar en los tests.
Sacando la política a Python se prueba de verdad la parte que decide, y en el
`sw.js` queda solo la mecánica de `caches.match` / `fetch`, que son unas pocas
líneas de código estándar. La política viaja al service worker serializada
como JSON (ver la ruta `/sw.js` en `app.py`).

Contexto que explica las decisiones: **paper-search se sirve desde 127.0.0.1**,
así que "sin conexión" son dos situaciones muy distintas y conviene no
mezclarlas:

1. **Sin internet, con el servidor local encendido.** La página carga entera y
   los favoritos funcionan completos —el SQLite es local—; solo fallan PubMed y
   la API de Claude. Esto ya funcionaba antes de la PWA y no necesita caché.
2. **Servidor local apagado.** No hay nada que responda. Aquí sí entra el
   service worker, y lo que puede ofrecer es limitado: HTML guardado, de solo
   lectura.

Por eso `navigator.onLine` no sirve para decidir qué avisar: dice si hay
internet, no si Flask está vivo, y se equivocaría en los dos sentidos. La
página distingue las dos situaciones con un ping a `/api/estado`.
"""

from __future__ import annotations

#: Sube cuando cambie cualquier recurso precacheado: el nombre de la caché
#: lleva la versión, así que al activarse se borran las cachés anteriores.
VERSION_CACHE = "v1"

#: Cache-first: se sirve de la caché y se refresca por detrás. Para lo que no
#: cambia dentro de una misma versión (CSS, iconos).
ESTRATEGIA_ESTATICO = "estatico"

#: Network-first con reserva en caché. Para las navegaciones: si el servidor
#: responde manda él, y si no se enseña la última copia guardada.
ESTRATEGIA_RED_PRIMERO = "red_primero"

#: Ni se cachea ni se sirve de caché: se deja pasar tal cual. Para todo lo que
#: cambia estado o consulta a un tercero.
ESTRATEGIA_SIN_CACHE = "sin_cache"

#: Rutas que se guardan al navegar para poder enseñarlas con el servidor caído.
NAVEGACIONES_CACHEABLES = ("/", "/favoritos")

#: Página que se sirve cuando no hay ni red ni copia guardada de esa ruta.
RUTA_OFFLINE = "/offline"

#: Endpoint mínimo para saber si el servidor local está vivo. Nunca se cachea:
#: una respuesta guardada diría que está encendido cuando no lo está.
RUTA_ESTADO = "/api/estado"


def estrategia_para(ruta: str, metodo: str = "GET") -> str:
    """Qué estrategia de caché le toca a una petición.

    Regla que manda sobre todas: **cualquier método que no sea GET no se toca**.
    Un POST servido desde caché sería inventar un resultado —una búsqueda que
    no se hizo, una nota que no se guardó— y este proyecto no hace eso ni
    cuando el fallo es de red.
    """
    if metodo.upper() != "GET":
        return ESTRATEGIA_SIN_CACHE

    limpia = (ruta or "/").split("?")[0]

    if limpia == RUTA_ESTADO:
        return ESTRATEGIA_SIN_CACHE
    if limpia.startswith("/static/") or limpia == "/manifest.json":
        return ESTRATEGIA_ESTATICO
    if limpia == RUTA_OFFLINE or limpia in NAVEGACIONES_CACHEABLES:
        return ESTRATEGIA_RED_PRIMERO
    return ESTRATEGIA_SIN_CACHE


def recursos_a_precachear() -> tuple[str, ...]:
    """Lo que se guarda al instalar el service worker.

    Es lo mínimo para que la app abra con el servidor apagado: la hoja de
    estilos, los iconos y la página de «sin conexión». Nada de contenido: los
    resultados y los favoritos se guardan solo cuando se visitan de verdad.
    """
    return (
        RUTA_OFFLINE,
        "/static/classical.css",
        "/static/paper-search.css",
        # Es lo que enciende el aviso de «copia guardada» y deshabilita los
        # formularios: sin precachearlo, la página servida desde caché se
        # vería normal y editable, que es justo lo que hay que evitar.
        "/static/conexion.js",
        # El SVG es el favicon: una sola copia sirve para todos los tamaños.
        "/static/iconos/paper-search-icon.svg",
        "/static/iconos/icono-192.png",
        "/static/iconos/icono-512.png",
        "/static/iconos/icono-maskable-512.png",
    )


def politica() -> dict:
    """La política completa, tal como viaja al service worker en JSON."""
    return {
        "version": VERSION_CACHE,
        "precache": list(recursos_a_precachear()),
        "navegaciones_cacheables": list(NAVEGACIONES_CACHEABLES),
        "ruta_offline": RUTA_OFFLINE,
        "ruta_estado": RUTA_ESTADO,
    }
