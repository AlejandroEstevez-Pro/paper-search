"""Servidor web local de paper-search (modo doble clic).

Interfaz de uso diario sin terminal: `run.bat` arranca este servidor y abre el
navegador en http://127.0.0.1:5000.

Igual que `cli.py`, este módulo es solo entrada/salida: la búsqueda y el
resumen los hace `buscar_y_resumir`, la misma función pública del paquete que
usa la CLI. Aquí no hay lógica de negocio duplicada.

El servidor escucha únicamente en 127.0.0.1: es una herramienta local para una
persona, no un servicio expuesto a la red. La clave de la API vive solo en este
proceso y nunca llega al navegador.
"""

from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, make_response, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from paper_search import (  # noqa: E402  (tras ajustar sys.path)
    DIAS_POR_DEFECTO,
    MAX_RESULTADOS_POR_DEFECTO,
    IDIOMAS,
    BaseDatosError,
    FavoritoError,
    Favoritos,
    LimiteAlcanzadoError,
    PaperSearchError,
    TerminoFueraDeAlcanceError,
    abrir_db,
    buscar_y_resumir,
    cargar_env,
    clave_fecha,
    cargar_idioma,
    normalizar_idioma,
    normalizar_orden,
    plegar_texto,
    traducir,
    segmentar_resumen,
    texto_para_notebooklm,
)
from paper_search.i18n import IDIOMA_REFERENCIA  # noqa: E402
from paper_search.orden import ETIQUETAS as ETIQUETAS_ORDEN  # noqa: E402
from paper_search.db import ahora_utc_iso  # noqa: E402
from paper_search.pwa import RUTA_ESTADO, politica  # noqa: E402

HOST = "127.0.0.1"
PUERTO = 5000

# Se carga aquí y no en main() para que las claves estén puestas aunque el
# servidor se arranque con `flask run` en vez de con `python app.py`. Lo
# exportado en el entorno tiene prioridad sobre el .env.
cargar_env()

app = Flask(__name__)



#: Cookie donde se recuerda el idioma elegido. Se prefiere a la sesión de
#: Flask porque la sesión exigiría un SECRET_KEY: un secreto más que
#: configurar y guardar en una herramienta cuyo objetivo es funcionar en local
#: sin configuración. La cookie no firma nada, y no hace falta: el valor se
#: normaliza al leerlo y solo puede acabar siendo uno de los idiomas conocidos.
COOKIE_IDIOMA = "idioma"
DIAS_COOKIE_IDIOMA = 365


def idioma_activo() -> str:
    """Idioma de esta petición: `?idioma=` > cookie > el de referencia.

    El parámetro de URL manda para que un enlace pueda conmutar el idioma y
    para que los tests puedan pedirlo sin montar estado; la cookie lo recuerda
    después, que es lo que hace que sobreviva a los POST de /buscar y a los
    redirect de favoritos sin tener que arrastrar el idioma en cada formulario.
    """
    return normalizar_idioma(
        request.args.get("idioma") or request.cookies.get(COOKIE_IDIOMA)
    )


@app.after_request
def recordar_idioma(respuesta):
    """Si la petición traía `?idioma=`, se recuerda en la cookie."""
    pedido = request.args.get("idioma")
    if pedido:
        respuesta.set_cookie(
            COOKIE_IDIOMA,
            normalizar_idioma(pedido),
            max_age=DIAS_COOKIE_IDIOMA * 24 * 3600,
            samesite="Lax",
        )
    return respuesta


#: Color de la barra de título de la ventana instalada y del fondo de arranque.
#: Es el mismo near-black del fondo del icono (`--color-text` del sistema de
#: diseño), para que la pantalla de arranque y el icono no hagan un escalón de
#: color al abrir la app instalada.
COLOR_TEMA = "#201f1d"
COLOR_FONDO = "#201f1d"


@app.get("/manifest.json")
def manifest():
    """Manifest de la PWA, servido por Flask y no como archivo estático.

    Así el nombre y la descripción que se ven al instalar pasan por el mismo
    sistema de traducción que el resto (i18n del punto 5.1) en vez de quedar
    fijos en un idioma.
    """
    idioma = idioma_activo()
    datos = {
        "id": "/?fuente=pwa",
        "name": traducir("app_nombre", idioma),
        "short_name": traducir("app_nombre", idioma),
        "description": traducir("app_descripcion", idioma),
        "lang": idioma,
        # `start_url` distinto de "/" para poder distinguir en el registro las
        # aperturas desde la app instalada de las del navegador.
        "start_url": "/?fuente=pwa",
        "scope": "/",
        "display": "standalone",
        "background_color": COLOR_FONDO,
        "theme_color": COLOR_TEMA,
        "icons": [
            {
                "src": url_for("static", filename="iconos/icono-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("static", filename="iconos/icono-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                # `maskable` deja que Android recorte el icono a su forma sin
                # comerse el dibujo: por eso este lleva más margen.
                "src": url_for("static", filename="iconos/icono-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    respuesta = jsonify(datos)
    # El tipo que pide la especificación de Web App Manifest.
    respuesta.headers["Content-Type"] = "application/manifest+json"
    return respuesta


@app.get("/sw.js")
def service_worker():
    """Service worker, servido desde la RAÍZ y no como archivo estático.

    Un service worker solo controla su propia carpeta hacia abajo: desde
    `/static/sw.js` su alcance sería `/static/` y no vería ni la portada ni
    los favoritos. Por eso se sirve en `/sw.js`.

    Se renderiza como plantilla para inyectarle la política de caché, que vive
    en `pwa.py` y es la que sí se puede probar sin navegador.
    """
    cuerpo = render_template("sw.js", politica=politica())
    respuesta = app.response_class(cuerpo, mimetype="text/javascript")
    # Sin esto el navegador se quedaría con un service worker viejo hasta 24 h.
    respuesta.headers["Cache-Control"] = "no-cache"
    respuesta.headers["Service-Worker-Allowed"] = "/"
    return respuesta


@app.get(RUTA_ESTADO)
def estado():
    """¿Está vivo el servidor local? Es la única forma fiable de saberlo.

    `navigator.onLine` responde a otra pregunta —si hay internet— y aquí se
    equivocaría en los dos sentidos: sin wifi pero con el servidor encendido
    los favoritos funcionan perfectamente, y con wifi pero el servidor apagado
    no funciona nada. La página pregunta por las dos cosas por separado.
    """
    respuesta = jsonify({"estado": "vivo", "version": __import__("paper_search").__version__})
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@app.get("/offline")
def offline():
    """Página de reserva cuando no hay ni servidor ni copia guardada.

    Lleva dentro los textos de TODOS los idiomas y elige por la cookie: es la
    única página que tiene que funcionar con el servidor apagado, así que no
    puede pedirle la traducción a nadie. Los textos siguen saliendo de la
    misma fuente (i18n/<idioma>.json), no son literales de la plantilla.
    """
    claves = [c for c in cargar_idioma(IDIOMA_REFERENCIA) if c.startswith("off_")]
    textos = {
        idioma: {clave: traducir(clave, idioma) for clave in claves}
        for idioma in IDIOMAS
    }
    return render_template(
        "offline.html",
        textos_offline=textos,
        idioma_referencia=IDIOMA_REFERENCIA,
        color_tema=COLOR_TEMA,
    )


#: Textos que necesita el JavaScript de la página. Viajan como JSON en vez de
#: quedar escritos en el .js: la fuente de traducción sigue siendo una sola.
CLAVES_JS = (
    "form_boton_buscando",
    "exp_boton_copiar",
    "exp_boton_copiado",
    "fav_boton_marcado",
    "fav_boton_sin_marcar",
    "fav_confirmar_borrar_nota",
    "fav_error_guardar",
    "fav_error_servidor",
    "fil_contador",
    # Avisos de conexión (ver static/conexion.js).
    "off_copia_aviso",
    "off_sin_internet",
    "off_buscar_sin_conexion",
    "off_solo_lectura",
)


@app.context_processor
def utilidades_de_plantilla():
    """Todo lo que las plantillas necesitan y no viene del resultado.

    `t` es la función de traducción: `t('form_boton_buscar')`. Recibe ya
    resuelto el idioma de la petición, así que las plantillas nunca lo pasan.

    La plantilla escribe `data-fecha` con la misma función que usa el servidor
    (`clave_fecha`), para que el reordenado del navegador y el del servidor no
    puedan discrepar.
    """
    idioma = idioma_activo()

    def t(clave: str, **valores) -> str:
        return traducir(clave, idioma, **valores)

    return {
        "t": t,
        "idioma": idioma,
        "idiomas": IDIOMAS,
        "textos_js": {clave: t(clave) for clave in CLAVES_JS},
        "color_tema": COLOR_TEMA,
        "ruta_estado": RUTA_ESTADO,
        "generado_en": ahora_utc_iso(),
        "etiquetas_orden": {
            "fecha": t("ord_fecha"),
            "relevancia": t("ord_relevancia"),
        },
        "clave_fecha": clave_fecha,
        "plegar_texto": plegar_texto,
    }


@app.get("/")
def inicio() -> str:
    """Portada. Acepta `?termino=` para llegar con el formulario relleno.

    Lo usa la extensión de Chrome: al buscar desde el menú contextual abre esta
    URL con el término seleccionado. Con `?buscar=1` la página además envía el
    formulario sola (ver `index.html`), así que basta un clic.

    La búsqueda de verdad sigue siendo el POST a `/buscar`, y eso es
    deliberado: un GET que buscara gastaría cuota diaria y llamadas a Claude
    reales, y quedaría al alcance de una precarga del navegador, de un marcador
    o de una revisita del historial. Esta URL, en cambio, solo pinta un
    formulario: es inofensiva por muchas veces que se cargue.
    """
    return render_template(
        "index.html",
        termino=(request.args.get("termino") or "").strip(),
        autobuscar=request.args.get("buscar") == "1",
        max_resultados=MAX_RESULTADOS_POR_DEFECTO,
        dias=DIAS_POR_DEFECTO,
    )


@app.post("/buscar")
def buscar():
    termino = (request.form.get("termino") or "").strip()
    max_crudo = request.form.get("max_resultados") or str(MAX_RESULTADOS_POR_DEFECTO)
    dias_crudo = request.form.get("dias") or str(DIAS_POR_DEFECTO)
    forzar = request.form.get("forzar") == "1"
    autor = (request.form.get("autor") or "").strip()
    patogeno = (request.form.get("patogeno") or "").strip()
    # Un valor desconocido cae al orden por defecto en vez de dar error: es una
    # preferencia de visualización, no un dato de la búsqueda.
    orden = normalizar_orden(request.form.get("orden"))

    idioma = idioma_activo()
    max_resultados, error = _entero_positivo(max_crudo, t_err("err_campo_max"), idioma)
    if error is None:
        dias, error = _entero_positivo(dias_crudo, t_err("err_campo_dias"), idioma)
    else:
        dias = DIAS_POR_DEFECTO

    if not (termino or autor or patogeno):
        error = traducir("err_sin_criterios", idioma)

    # Los valores del formulario se devuelven tal cual los escribió la persona
    # para no perder lo que tenía puesto cuando hay un error.
    contexto = {
        "termino": termino,
        "max_resultados": max_crudo,
        "dias": dias_crudo,
        "autor": autor,
        "patogeno": patogeno,
    }

    if error is not None:
        return render_template("index.html", error=error, **contexto), 400

    # La BD local (caché, límites, registro) es una comodidad: si no se puede
    # abrir, la búsqueda sigue sin persistencia (no hay dónde mostrar un aviso
    # mejor que el log del servidor).
    try:
        db = abrir_db()
    except BaseDatosError as exc:
        app.logger.warning("Sin base de datos local: %s", exc)
        db = None

    marcados: set[str] = set()
    try:
        resultado = buscar_y_resumir(
            termino,
            autor=autor,
            patogeno=patogeno,
            max_resultados=max_resultados,
            dias=dias,
            orden=orden,
            idioma=idioma,
            db=db,
            forzar=forzar,
        )
        # Qué papers de esta búsqueda ya están en favoritos, para pintar el
        # botón en el estado correcto desde el primer render.
        if db is not None:
            marcados = Favoritos(db, idioma=idioma).pmids()
    except LimiteAlcanzadoError as exc:
        # Límite diario de uso propio: 429, el código HTTP de "demasiadas
        # peticiones". El mensaje ya dice qué límite fue y cuándo se resetea.
        return render_template("index.html", error=str(exc), **contexto), 429
    except TerminoFueraDeAlcanceError as exc:
        # Término fuera del alcance (enfermedades raras): la búsqueda se
        # bloqueó antes de tocar PubMed. Es un problema de la entrada, no de
        # las APIs, así que se trata como los errores de formulario (400).
        return render_template("index.html", error=str(exc), **contexto), 400
    except PaperSearchError as exc:
        # Fallo de PubMed: no hay datos reales que enseñar, así que se dice
        # claramente en vez de mostrar una página vacía.
        return render_template("index.html", error=str(exc), **contexto), 502
    finally:
        if db is not None:
            db.close()

    # `parrafos` vacío significa "no hay resumen": la plantilla enseña entonces
    # el motivo junto a las referencias, que sí son reales.
    # El texto de exportación lo arma el servidor y viaja ya hecho a la
    # página: así lo que se copia es exactamente lo que cubren los tests, en
    # vez de reconstruirlo en JavaScript desde el DOM ya maquetado.
    return render_template(
        "index.html",
        resultado=resultado,
        parrafos=segmentar_resumen(resultado.resumen or ""),
        favoritos=marcados,
        texto_exportado=texto_para_notebooklm(resultado),
        **contexto,
    )


# ---------------------------------------------------------------- favoritos


@app.get("/favoritos")
def ver_favoritos():
    """Vista «Mis favoritos»: los papers marcados, con sus notas editables."""
    try:
        db = abrir_db()
    except BaseDatosError as exc:
        return render_template("favoritos.html", lista=[], error=str(exc)), 500
    try:
        lista = Favoritos(db, idioma=idioma_activo()).listar()
    finally:
        db.close()
    return render_template("favoritos.html", lista=lista)


@app.post("/favoritos/alternar")
def alternar_favorito():
    """Marca o desmarca un paper sin recargar la página de resultados.

    Devuelve JSON porque se llama desde el botón de cada resultado: recargar
    perdería la búsqueda que hay en pantalla (es un POST, no una URL).

    Desmarcar un favorito con nota se hace en dos pasos: la primera llamada
    responde `requiere_confirmacion` con el texto de la nota, para que el
    navegador pueda avisar de lo que se va a perder antes de insistir.
    """
    datos = request.get_json(silent=True) or {}
    pmid = str(datos.get("pmid") or "").strip()
    confirmado = bool(datos.get("confirmado"))

    try:
        db = abrir_db()
    except BaseDatosError as exc:
        return jsonify({"error": str(exc)}), 500

    try:
        favoritos = Favoritos(db, idioma=idioma_activo())
        actual = favoritos.obtener(pmid)
        if actual is not None:
            if actual.tiene_nota and not confirmado:
                return jsonify(
                    {
                        "favorito": True,
                        "requiere_confirmacion": True,
                        "nota": actual.nota,
                    }
                )
            favoritos.desmarcar(pmid)
            return jsonify({"favorito": False})

        favorito = favoritos.marcar(pmid)
        return jsonify({"favorito": True, "nota": favorito.nota})
    except FavoritoError as exc:
        # PMID que no salió en ninguna búsqueda: es un error de la petición,
        # no del servidor.
        return jsonify({"error": str(exc)}), 400
    finally:
        db.close()


@app.post("/favoritos/nota")
def guardar_nota():
    """Guarda la nota desde la vista de favoritos (formulario normal)."""
    pmid = (request.form.get("pmid") or "").strip()
    nota = request.form.get("nota")

    try:
        db = abrir_db()
    except BaseDatosError as exc:
        return render_template("favoritos.html", lista=[], error=str(exc)), 500

    try:
        Favoritos(db, idioma=idioma_activo()).anotar(pmid, nota)
    except FavoritoError as exc:
        lista = Favoritos(db, idioma=idioma_activo()).listar()
        return render_template("favoritos.html", lista=lista, error=str(exc)), 400
    finally:
        db.close()
    return redirect(url_for("ver_favoritos"))


@app.post("/favoritos/quitar")
def quitar_favorito():
    """Desmarca desde la vista de favoritos. La confirmación la pide el
    navegador antes de enviar (ver `favoritos.html`)."""
    pmid = (request.form.get("pmid") or "").strip()

    try:
        db = abrir_db()
    except BaseDatosError as exc:
        return render_template("favoritos.html", lista=[], error=str(exc)), 500
    try:
        Favoritos(db, idioma=idioma_activo()).desmarcar(pmid)
    except FavoritoError as exc:
        lista = Favoritos(db, idioma=idioma_activo()).listar()
        return render_template("favoritos.html", lista=lista, error=str(exc)), 400
    finally:
        db.close()
    return redirect(url_for("ver_favoritos"))


def t_err(clave: str) -> str:
    """Nombre de un campo del formulario, en el idioma de la petición."""
    return traducir(clave, idioma_activo())


def _entero_positivo(
    valor: str, etiqueta: str, idioma: str
) -> tuple[int, str | None]:
    """Convierte un campo del formulario, devolviendo (valor, mensaje de error)."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return 0, traducir("err_no_entero", idioma, campo=etiqueta)
    if numero <= 0:
        return 0, traducir("err_no_positivo", idioma, campo=etiqueta)
    return numero, None


def main() -> None:
    print(f"paper-search — servidor local en http://{HOST}:{PUERTO}")
    print("Cierra esta ventana (o pulsa Ctrl+C) para detenerlo.")
    app.run(host=HOST, port=PUERTO, debug=False)


if __name__ == "__main__":
    main()
