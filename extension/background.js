/* Service worker de la extensión: el menú contextual.
 *
 * Flujo: seleccionas un gen o un síndrome en cualquier página, botón derecho,
 * y se abre paper-search con el término ya puesto.
 *
 * La extensión NO lee ninguna página. `contexts: ["selection"]` hace que Chrome
 * entregue el texto seleccionado en `info.selectionText`, así que no hacen
 * falta ni content scripts, ni `activeTab`, ni `scripting`. En una herramienta
 * médica eso importa: la extensión no puede ver lo que estás leyendo.
 */

import { limpiarTermino, servidorVivo, texto, urlDeBusqueda } from "./comun.js";

const ID_MENU = "buscar-en-paper-search";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: ID_MENU,
      // El «%s» del texto lo sustituye Chrome por lo seleccionado. Es sintaxis
      // de contextMenus, no un placeholder de i18n.
      title: texto("ext_menu_buscar"),
      contexts: ["selection"],
    });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, pestana) => {
  if (info.menuItemId !== ID_MENU) return;

  const termino = limpiarTermino(info.selectionText);
  if (!termino) return;

  const vivo = await servidorVivo();
  await avisarSiCaido(vivo);

  // Se abre la pestaña esté el servidor vivo o no. Si está caído, la propia
  // PWA sirve su página de «sin conexión», que ya explica qué pasa y cómo
  // arrancarlo, en el idioma correcto. Duplicar aquí ese mensaje sería
  // mantener dos textos para lo mismo.
  await chrome.tabs.create({
    url: urlDeBusqueda(termino),
    index: pestana ? pestana.index + 1 : undefined,
  });
});

/**
 * La insignia del icono es la única superficie propia que tiene la extensión
 * cuando actúa desde el menú contextual: no hay popup abierto donde escribir.
 * Se usa para señalar, no para explicar; lo que explica es la página que se
 * abre a continuación.
 */
async function avisarSiCaido(vivo) {
  if (vivo) {
    await chrome.action.setBadgeText({ text: "" });
    await chrome.action.setTitle({ title: texto("ext_nombre") });
    return;
  }
  await chrome.action.setBadgeText({ text: "!" });
  await chrome.action.setBadgeBackgroundColor({ color: "#b68235" });
  await chrome.action.setTitle({ title: texto("off_servidor_caido") });
}
