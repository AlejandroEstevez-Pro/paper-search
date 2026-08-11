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

from flask import Flask, jsonify, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from paper_search import (  # noqa: E402  (tras ajustar sys.path)
    DIAS_POR_DEFECTO,
    MAX_RESULTADOS_POR_DEFECTO,
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
    normalizar_orden,
    plegar_texto,
    segmentar_resumen,
    texto_para_notebooklm,
)
from paper_search.orden import ETIQUETAS as ETIQUETAS_ORDEN  # noqa: E402

HOST = "127.0.0.1"
PUERTO = 5000

# Se carga aquí y no en main() para que las claves estén puestas aunque el
# servidor se arranque con `flask run` en vez de con `python app.py`. Lo
# exportado en el entorno tiene prioridad sobre el .env.
cargar_env()

app = Flask(__name__)


@app.context_processor
def utilidades_de_plantilla():
    """Etiquetas del selector de orden y la clave de fecha con la que ordena.

    La plantilla escribe `data-fecha` con la misma función que usa el servidor
    (`clave_fecha`), para que el reordenado del navegador y el del servidor no
    puedan discrepar.
    """
    return {
        "etiquetas_orden": ETIQUETAS_ORDEN,
        "clave_fecha": clave_fecha,
        "plegar_texto": plegar_texto,
    }


@app.get("/")
def inicio() -> str:
    return render_template(
        "index.html",
        termino="",
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

    max_resultados, error = _entero_positivo(max_crudo, "El máximo de resultados")
    if error is None:
        dias, error = _entero_positivo(dias_crudo, "La ventana en días")
    else:
        dias = DIAS_POR_DEFECTO

    if not (termino or autor or patogeno):
        error = (
            "Escribe un gen, síndrome o término de búsqueda, o usa la búsqueda "
            "avanzada para buscar por autor o patógeno."
        )

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
            db=db,
            forzar=forzar,
        )
        # Qué papers de esta búsqueda ya están en favoritos, para pintar el
        # botón en el estado correcto desde el primer render.
        if db is not None:
            marcados = Favoritos(db).pmids()
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
        lista = Favoritos(db).listar()
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
        favoritos = Favoritos(db)
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
        Favoritos(db).anotar(pmid, nota)
    except FavoritoError as exc:
        lista = Favoritos(db).listar()
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
        Favoritos(db).desmarcar(pmid)
    except FavoritoError as exc:
        lista = Favoritos(db).listar()
        return render_template("favoritos.html", lista=lista, error=str(exc)), 400
    finally:
        db.close()
    return redirect(url_for("ver_favoritos"))


def _entero_positivo(valor: str, etiqueta: str) -> tuple[int, str | None]:
    """Convierte un campo del formulario, devolviendo (valor, mensaje de error)."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return 0, f"{etiqueta} tiene que ser un número entero."
    if numero <= 0:
        return 0, f"{etiqueta} tiene que ser mayor que 0."
    return numero, None


def main() -> None:
    print(f"paper-search — servidor local en http://{HOST}:{PUERTO}")
    print("Cierra esta ventana (o pulsa Ctrl+C) para detenerlo.")
    app.run(host=HOST, port=PUERTO, debug=False)


if __name__ == "__main__":
    main()
