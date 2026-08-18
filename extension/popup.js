/* Popup de la extensión: lanzador, no visor de resultados.
 *
 * Sirve para dos cosas: buscar un término escrito a mano (cuando no hay nada
 * seleccionado en la página) y ver si paper-search está en marcha antes de
 * intentarlo.
 *
 * Lo que NO hace es pintar resultados. Un popup de MV3 se cierra en cuanto
 * pierde el foco, y una búsqueda con resumen tarda entre 10 y 30 segundos
 * (alcance + resumen + verificación): moriría a media búsqueda de forma
 * rutinaria. Además, renderizar aquí el resumen obligaría a repetir en un
 * segundo sitio el aviso de no diagnóstico y la trazabilidad a PMID, que son
 * las reglas duras del proyecto. Se abre una pestaña con la web de siempre.
 *
 * Ni un texto de este archivo está escrito a mano: todos salen de `_locales/`.
 */

import { limpiarTermino, servidorVivo, texto, urlDeBusqueda } from "./comun.js";

const $ = (id) => document.getElementById(id);

function pintarTextosFijos() {
  $("titulo").textContent = texto("ext_nombre");
  $("intro").textContent = texto("ext_popup_intro");
  $("etiqueta-termino").textContent = texto("form_etiqueta_termino");
  $("termino").placeholder = texto("form_placeholder_termino");
  $("boton").textContent = texto("form_boton_buscar");
  $("estado-texto").textContent = texto("ext_estado_comprobando");
  document.title = texto("ext_nombre");
  document.documentElement.lang = chrome.i18n.getMessage("@@ui_locale") || "es";
}

function mostrarError(clave) {
  const error = $("error");
  if (!clave) {
    error.hidden = true;
    return;
  }
  error.textContent = texto(clave);
  error.hidden = false;
}

async function pintarEstado() {
  const vivo = await servidorVivo();
  $("punto").classList.toggle("vivo", vivo);
  $("punto").classList.toggle("caido", !vivo);
  // El caso «caído» reutiliza el mensaje de la PWA, que ya dice lo útil
  // —arráncalo con run.bat— en vez de un «sin conexión» genérico.
  $("estado-texto").textContent = texto(vivo ? "ext_estado_vivo" : "off_servidor_caido");
  return vivo;
}

$("formulario").addEventListener("submit", async (evento) => {
  evento.preventDefault();

  const termino = limpiarTermino($("termino").value);
  if (!termino) {
    mostrarError("ext_sin_termino");
    $("termino").focus();
    return;
  }
  mostrarError(null);

  // Se abre la pestaña aunque el servidor esté caído: la página «sin conexión»
  // de la PWA explica el problema mejor de lo que cabe en este popup.
  await chrome.tabs.create({ url: urlDeBusqueda(termino) });
  window.close();
});

pintarTextosFijos();
pintarEstado();
