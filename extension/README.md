# Extensión de Chrome de paper-search

Selecciona un gen o un síndrome en cualquier página, botón derecho, y se abre
paper-search con el término ya puesto. También hay un popup con un campo para
escribirlo a mano.

> **No es una herramienta de diagnóstico ni de asesoramiento médico.** Es un
> atajo para llegar a paper-search sin teclear; todo lo demás —el filtro de
> alcance, el aviso de idioma, el resumen y su verificación— lo sigue haciendo
> el servidor.

## Instalar en modo desarrollador

La extensión no está en la Chrome Web Store: se carga a mano.

1. Arranca paper-search (doble clic en `paper-search/run.bat`). La extensión
   necesita que el servidor esté escuchando en `http://127.0.0.1:5000`.
2. Abre `chrome://extensions` en Chrome o Edge.
3. Activa el interruptor **Modo de desarrollador** (arriba a la derecha).
4. Pulsa **Cargar descomprimida** y elige esta carpeta (`extension/`).
5. Ancla el icono a la barra si quieres tenerlo a mano.

Para actualizarla después de tocar el código, vuelve a `chrome://extensions` y
pulsa el botón de recargar de la tarjeta de la extensión.

## Qué permisos pide, y por qué

| Permiso | Para qué |
|---|---|
| `contextMenus` | Añadir la entrada del botón derecho. |
| `http://127.0.0.1:5000/*` | Preguntar a `/api/estado` si paper-search está arrancado. |

Nada más. En concreto **no pide acceso a las páginas que visitas**: la entrada
del menú se declara con `contexts: ["selection"]`, así que Chrome le entrega el
texto seleccionado sin que la extensión lea nada. No hay content scripts, ni
`activeTab`, ni `scripting`, ni `<all_urls>`. La extensión no puede ver lo que
estás leyendo.

## Si paper-search no está arrancado

El popup lo dice antes de que intentes nada, con el mismo mensaje que usa la
web: *«No se ha podido contactar con paper-search en tu ordenador. Comprueba
que está arrancado (doble clic en run.bat)»*.

Desde el menú contextual aparece un `!` en el icono y la pestaña se abre
igualmente: la propia web tiene una página de «sin conexión» que explica el
problema completo, y duplicar aquí ese texto sería mantener dos.

Se comprueba preguntando al servidor, no con `navigator.onLine`: eso dice si
hay internet, que es otra cosa. Sin wifi pero con paper-search arrancado, los
favoritos funcionan; con wifi pero sin arrancarlo, no funciona nada.

## Idiomas

Los textos salen de `_locales/`, que **se generan** desde la misma fuente de
traducción que la web:

```bash
cd ../paper-search
python herramientas/generar_locales.py
```

No se editan a mano: si falta un mensaje, se añade a `paper-search/i18n/es.json`
y `en.json` y se regenera. Hay un test que falla si se quedan atrás.

La extensión elige idioma por el del **navegador** (es lo que hace
`chrome.i18n`), mientras que la web lo recuerda en una cookie. Pueden discrepar:
si tienes el navegador en español y la web en inglés, el menú saldrá en español
y la página en inglés. Es deliberado —una preferencia que elegiste a mano debe
ganar a la que deduce el navegador— pero conviene saberlo.

## Estructura

```
extension/
├── manifest.json     # MV3: permisos, iconos, default_locale
├── background.js     # service worker: el menú contextual
├── popup.html/js/css # lanzador y estado del servidor
├── comun.js          # lo compartido: ping de estado y URL de búsqueda
├── _locales/         # GENERADO desde paper-search/i18n/
└── iconos/           # GENERADOS desde el SVG de paper-search
```

`_locales/` e `iconos/` son artefactos: se regeneran con las herramientas de
`paper-search/herramientas/`, no se editan aquí.
