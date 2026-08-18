/* Lo que comparten el service worker y el popup.
 *
 * Ni un texto de cara al usuario vive aquí: todos salen de `_locales/`, que
 * genera `paper-search/herramientas/generar_locales.py` desde la misma fuente
 * que la web. Si un mensaje hace falta y no está, se añade a `i18n/es.json` y
 * se regenera — nunca se escribe suelto en este archivo.
 */

/** Dónde escucha paper-search. Debe coincidir con `host_permissions`. */
export const SERVIDOR = "http://127.0.0.1:5000";

/** Endpoint mínimo de la PWA para saber si Flask está vivo (ver pwa.py). */
export const RUTA_ESTADO = "/api/estado";

/**
 * Cuánto se espera al ping antes de darlo por caído.
 *
 * Corto a propósito: el servidor es local, así que si está en marcha responde
 * en milisegundos. Esperar más solo alarga el tiempo hasta poder avisar.
 */
export const TIMEOUT_MS = 1500;

/** Texto traducido. `chrome.i18n` resuelve contra `_locales/`. */
export function texto(clave, sustituciones) {
  return chrome.i18n.getMessage(clave, sustituciones) || clave;
}

/**
 * ¿Responde el servidor local?
 *
 * Es la misma señal que usa la PWA y por el mismo motivo: `navigator.onLine`
 * dice si hay internet, no si Flask está arrancado, y se equivocaría en los
 * dos sentidos —sin wifi pero con el servidor vivo la app funciona, y con wifi
 * pero el servidor apagado no funciona nada—. La única forma de saberlo es
 * preguntarle al servidor.
 */
export async function servidorVivo() {
  const aborto = new AbortController();
  const reloj = setTimeout(() => aborto.abort(), TIMEOUT_MS);
  try {
    const respuesta = await fetch(SERVIDOR + RUTA_ESTADO, {
      cache: "no-store",
      signal: aborto.signal,
    });
    return respuesta.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(reloj);
  }
}

/**
 * URL de búsqueda para un término.
 *
 * Apunta a la portada con el término puesto y `buscar=1`, no a `/buscar`:
 *
 * - La búsqueda de verdad sigue siendo un POST que envía la propia página. Un
 *   GET que buscara gastaría cuota diaria y llamadas a Claude de verdad, y
 *   quedaría al alcance de una precarga del navegador, un marcador o una
 *   revisita del historial.
 * - El guardarraíl de alcance y el aviso de idioma los sigue aplicando el
 *   servidor, en su sitio. La extensión no los reimplementa ni los esquiva:
 *   solo rellena el formulario.
 *
 * No se manda `idioma`: la web recuerda el que el usuario eligió en su cookie,
 * y esa preferencia explícita debe ganar a la implícita del navegador que usa
 * `chrome.i18n` para esta extensión.
 */
export function urlDeBusqueda(termino) {
  const url = new URL(SERVIDOR + "/");
  url.searchParams.set("termino", termino);
  url.searchParams.set("buscar", "1");
  return url.toString();
}

/** Recorta lo seleccionado: los saltos de línea y el espacio sobran. */
export function limpiarTermino(bruto) {
  return (bruto || "").replace(/\s+/g, " ").trim();
}
