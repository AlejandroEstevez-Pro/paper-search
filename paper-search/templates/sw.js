/* Service worker de paper-search.
 *
 * Aquí solo hay MECÁNICA. La decisión de qué estrategia le toca a cada
 * petición vive en `src/paper_search/pwa.py` y llega abajo como JSON, porque
 * sin navegador ni Node la suite de tests no puede ejecutar este archivo: así
 * lo que decide se prueba de verdad en Python y aquí queda lo mínimo.
 *
 * Contexto que explica las decisiones: paper-search se sirve desde 127.0.0.1.
 * "Sin conexión" son dos cosas distintas —sin internet con el servidor vivo, o
 * el servidor apagado— y solo la segunda necesita este archivo. Ver pwa.py.
 */

const POLITICA = {{ politica | tojson }};

const CACHE_ESTATICOS = `paper-search-${POLITICA.version}-estaticos`;
const CACHE_PAGINAS = `paper-search-${POLITICA.version}-paginas`;
const NUESTRAS_CACHES = [CACHE_ESTATICOS, CACHE_PAGINAS];

self.addEventListener('install', (evento) => {
  evento.waitUntil(
    caches.open(CACHE_ESTATICOS)
      .then((cache) => cache.addAll(POLITICA.precache))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (evento) => {
  // Al subir la versión se tiran las cachés viejas: es lo que evita quedarse
  // con un CSS o un icono de una versión anterior.
  evento.waitUntil(
    caches.keys()
      .then((nombres) => Promise.all(
        nombres
          .filter((n) => n.startsWith('paper-search-') && !NUESTRAS_CACHES.includes(n))
          .map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

function estrategiaPara(peticion) {
  if (peticion.method !== 'GET') return 'sin_cache';

  const url = new URL(peticion.url);
  if (url.origin !== self.location.origin) return 'sin_cache';

  const ruta = url.pathname;
  if (ruta === POLITICA.ruta_estado) return 'sin_cache';
  if (ruta.startsWith('/static/') || ruta === '/manifest.json') return 'estatico';
  if (ruta === POLITICA.ruta_offline) return 'red_primero';
  if (POLITICA.navegaciones_cacheables.includes(ruta)) return 'red_primero';
  return 'sin_cache';
}

// Cache-first con refresco por detrás: lo que no cambia dentro de una versión.
async function servirEstatico(peticion) {
  const cache = await caches.open(CACHE_ESTATICOS);
  const guardado = await cache.match(peticion);
  const desdeRed = fetch(peticion)
    .then((respuesta) => {
      if (respuesta && respuesta.ok) cache.put(peticion, respuesta.clone());
      return respuesta;
    })
    .catch(() => guardado);
  return guardado || desdeRed;
}

// Network-first: manda el servidor, y si no responde se enseña la última copia.
async function servirNavegacion(peticion) {
  const cache = await caches.open(CACHE_PAGINAS);
  try {
    const respuesta = await fetch(peticion);
    if (respuesta && respuesta.ok) cache.put(peticion, respuesta.clone());
    return respuesta;
  } catch (error) {
    const guardado = await cache.match(peticion, { ignoreSearch: true });
    if (guardado) return guardado;
    const offline = await caches.match(POLITICA.ruta_offline);
    if (offline) return offline;
    throw error;
  }
}

self.addEventListener('fetch', (evento) => {
  const estrategia = estrategiaPara(evento.request);

  // `sin_cache` no intercepta NADA: la petición sale como si este archivo no
  // existiera. Es lo que impide servir de caché un POST —una búsqueda que no
  // se hizo, una nota que no se guardó— aunque falle la red.
  if (estrategia === 'sin_cache') return;

  if (estrategia === 'estatico') {
    evento.respondWith(servirEstatico(evento.request));
  } else {
    evento.respondWith(servirNavegacion(evento.request));
  }
});
