# Extensión de Chrome de paper-search

Extensión para buscar en tu paper-search local desde cualquier página.

> Este commit trae solo el esqueleto: manifest, iconos, traducciones y
> permisos. Todavía no hace nada — el menú contextual y el popup llegan en el
> commit siguiente.

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

## Estructura

```
extension/
├── manifest.json     # MV3: permisos, iconos, default_locale
├── _locales/         # GENERADO desde paper-search/i18n/
└── iconos/           # GENERADOS desde el SVG de paper-search
```

`_locales/` e `iconos/` son artefactos: se regeneran con las herramientas de
`paper-search/herramientas/`, no se editan aquí.
