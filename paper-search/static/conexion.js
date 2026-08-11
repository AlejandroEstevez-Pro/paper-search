/* Registro del service worker y avisos de conexión.
 *
 * Distingue DOS situaciones que se confunden con facilidad, porque
 * paper-search se sirve desde 127.0.0.1:
 *
 *   1. No hay internet, pero el servidor local está encendido. La página carga
 *      entera y los favoritos funcionan completos —el SQLite es local—; solo
 *      fallan PubMed y el resumidor. Se avisa, pero no se bloquea nada salvo
 *      la búsqueda.
 *   2. El servidor local está apagado. Aquí no funciona nada: lo que se ve es
 *      una copia guardada por el service worker, de solo lectura.
 *
 * `navigator.onLine` solo responde a la primera pregunta, así que por sí solo
 * se equivocaría en los dos sentidos. La segunda se responde preguntándole al
 * propio servidor (/api/estado).
 *
 * Los textos salen todos de PS_TEXTOS, que viene de la fuente de traducción.
 * Aquí no hay ni un literal de cara al usuario.
 */
(function () {
  'use strict';

  function texto(clave, valores) {
    var plantilla = (window.PS_TEXTOS || {})[clave] || clave;
    if (!valores) return plantilla;
    return plantilla.replace(/\$([a-z][a-z0-9_]*)\$/g, function (todo, nombre) {
      return Object.prototype.hasOwnProperty.call(valores, nombre)
        ? valores[nombre] : todo;
    });
  }

  // ---------------------------------------------------------- service worker

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .catch(function () {
          // Que no se registre no rompe nada: la app funciona igual con el
          // servidor encendido, que es el caso normal. Se calla.
        });
    });
  }

  // ------------------------------------------------------- estado del servidor

  function servidorVivo() {
    var ruta = window.PS_RUTA_ESTADO || '/api/estado';
    // Timeout corto: si el servidor no está, el navegador tardaría en rendirse
    // y el aviso llegaría cuando ya no sirve de nada.
    var aborto = new AbortController();
    var reloj = setTimeout(function () { aborto.abort(); }, 2000);
    return fetch(ruta, { cache: 'no-store', signal: aborto.signal })
      .then(function (r) { clearTimeout(reloj); return r.ok; })
      .catch(function () { clearTimeout(reloj); return false; });
  }

  function fechaDeGeneracion() {
    var meta = document.querySelector('meta[name="ps-generado"]');
    if (!meta || !meta.content) return '';
    // Solo la parte legible: "2026-08-11T14:32:05+00:00" -> "2026-08-11 14:32"
    return meta.content.slice(0, 10) + ' ' + meta.content.slice(11, 16);
  }

  function marcarCopiaGuardada() {
    var aviso = document.getElementById('ps-aviso-copia');
    if (!aviso) return;
    document.getElementById('ps-texto-copia').textContent =
      texto('off_copia_aviso', { fecha: fechaDeGeneracion() });
    aviso.hidden = false;

    // Con el servidor apagado, cualquier formulario que escriba fallaría en
    // silencio: se deshabilitan y se dice por qué en el propio botón.
    var formularios = document.querySelectorAll('form[method="post"], .ps-form');
    Array.prototype.forEach.call(formularios, function (formulario) {
      Array.prototype.forEach.call(
        formulario.querySelectorAll('button, input, textarea, select'),
        function (campo) {
          campo.disabled = true;
          if (campo.tagName === 'BUTTON') campo.title = texto('off_solo_lectura');
        }
      );
    });
    Array.prototype.forEach.call(document.querySelectorAll('.ps-fav'), function (b) {
      b.disabled = true;
      b.title = texto('off_solo_lectura');
    });
  }

  function marcarSinInternet(sinInternet) {
    var aviso = document.getElementById('ps-aviso-internet');
    if (!aviso) return;
    document.getElementById('ps-texto-internet').textContent = texto('off_sin_internet');
    aviso.hidden = !sinInternet;
  }

  function revisarConexion() {
    marcarSinInternet(navigator.onLine === false);
    servidorVivo().then(function (vivo) {
      if (!vivo) marcarCopiaGuardada();
    });
  }

  window.addEventListener('online', function () { marcarSinInternet(false); });
  window.addEventListener('offline', function () { marcarSinInternet(true); });

  // -------------------------------------------- la búsqueda necesita internet

  var formulario = document.getElementById('formulario');
  if (formulario) {
    // Se comprueba en el `submit` y ANTES de que el navegador navegue: sin
    // esto, sin red el usuario se quedaría mirando el spinner hasta que el
    // navegador se rindiera y enseñara su propia página de error.
    formulario.addEventListener('submit', function (evento) {
      if (navigator.onLine === false) {
        evento.preventDefault();
        evento.stopImmediatePropagation();
        var aviso = document.getElementById('ps-aviso-internet');
        if (aviso) {
          document.getElementById('ps-texto-internet').textContent =
            texto('off_buscar_sin_conexion');
          aviso.hidden = false;
          aviso.scrollIntoView({ block: 'nearest' });
        }
      }
    }, true);  // en captura: corre antes que el que enciende el spinner
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', revisarConexion);
  } else {
    revisarConexion();
  }
})();
