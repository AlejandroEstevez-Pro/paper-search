# paper-search

[English](README.md) · **Español**

Buscador/resumidor de papers de PubMed por gen o síndrome **relacionado con
enfermedades raras**. Genera un resumen en lenguaje llano de los hallazgos
recientes, siempre con trazabilidad a los PMIDs originales.

## Antes de usarlo

> **paper-search no es una herramienta de diagnóstico ni sustituye el criterio
> médico.** Ayuda a encontrar y leer artículos científicos. No puede decir si
> alguien tiene una enfermedad, qué tratamiento seguir ni qué cabe esperar. No
> tomes decisiones de salud basándote en lo que diga; lleva tus preguntas a un
> profesional sanitario.

**Los resúmenes los escribe un modelo de lenguaje.** Se verifican
automáticamente antes de mostrarse, pero la verificación no es infalible: un
resumen puede superar todas las comprobaciones y aun así deformar lo que dice
un artículo.

Esto es lo que cubren de verdad las comprobaciones:

**Garantizado por código (exacto, siempre)**
- Todo PMID citado en el resumen pertenece a un artículo recuperado en esta
  búsqueda: no puede citar un paper inexistente o que no se haya recuperado.
- El resumen cita al menos un PMID.
- No se muestra ningún resumen cuya verificación no haya terminado y lo haya
  aprobado. Si el verificador no está disponible, salen las referencias y no
  el resumen.

**Comprobado por un segundo modelo (suele acertar, pero puede fallar)**
- Toda afirmación clínica lleva su cita.
- El texto no da consejo médico dirigido al lector.
- El término de búsqueda entra en el ámbito de las enfermedades raras. Si esta
  comprobación no puede ejecutarse, la búsqueda sigue igualmente, con un
  aviso.

**Sin comprobar**
- **Que el paper citado respalde de verdad la afirmación.** El verificador ve
  el resumen y la lista de PMIDs válidos, no los abstracts. Un PMID real puede
  acabar pegado a algo que ese paper no dice, y una afirmación correcta puede
  salir exagerada, con una cifra equivocada o sin sus matices.
- **Lo que no esté en el abstract.** El modelo lee solo el título, los
  metadatos y el abstract de cada paper, nunca el texto completo. Métodos,
  limitaciones y resultados que no estén en el abstract no los ve, y un paper
  sin abstract no aporta casi nada.
- **La calidad de la evidencia.** No se evalúa el diseño del estudio, el
  tamaño de la muestra, las retractaciones, los conflictos de interés ni si se
  ha replicado: un caso clínico aislado y un ensayo aleatorizado pesan igual.
- **La exhaustividad.** Por defecto salen hasta 15 papers de los dos últimos
  años, ordenados por relevancia de PubMed. No es una revisión sistemática y
  puede faltar trabajo importante.

Usa cada resumen como guía de qué leer, y abre el paper citado antes de fiarte
de cualquier afirmación.

El alcance está restringido: un clasificador comprueba antes de buscar que el
término es plausible como gen o síndrome de enfermedades raras, y cada resumen
pasa una verificación automática (trazabilidad de PMIDs y ausencia de consejo
médico) antes de mostrarse. Ver "Qué esperar de una búsqueda" más abajo.

Ver `docs/brief.md` para la spec completa de esta primera versión.

## Instalación

Requiere Python 3.10 o superior.

```bash
cd paper-search
pip install -r requirements.txt
```

## Claves de API

| Variable | ¿Obligatoria? | Para qué |
|---|---|---|
| `ANTHROPIC_API_KEY` | Sí, para el resumen | Genera el resumen en lenguaje llano y alimenta los dos guardarraíles (filtro de alcance y verificación del resumen). Sin ella la búsqueda funciona igual y se listan las referencias, pero no hay resumen (la CLI sale con código 2 explicando por qué) y el filtro de alcance deja pasar cualquier término con un aviso. |
| `NCBI_EMAIL` | **Sí** | Tu email de contacto. NCBI, que mantiene PubMed, lo pide a todo programa que use su API para poder avisar a quien lo ejecuta si sus peticiones dan problemas antes de bloquearlas. No hay ninguno por defecto: sin él no se consulta PubMed, y la CLI (código 1) o la web explican qué falta. |
| `NCBI_API_KEY` | No | Sube el límite de PubMed de 3 a 10 peticiones/segundo. Gratis en <https://www.ncbi.nlm.nih.gov/account/>. |

Hay dos formas de ponerlas. La segunda es la cómoda para el día a día,
sobre todo con el modo doble clic, donde no hay terminal donde exportar nada.

**1. Variables de entorno del sistema** (tienen prioridad):

```powershell
# PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

```bash
# bash / zsh
export ANTHROPIC_API_KEY="sk-ant-..."
```

**2. Un archivo `.env`** en la raíz de `paper-search/` (junto a `cli.py`).
Copia la plantilla versionada y rellena la clave y tu email:

```powershell
# PowerShell
Copy-Item .env.example .env
```

```bash
# bash / zsh
cp .env.example .env
```

```ini
# paper-search/.env
ANTHROPIC_API_KEY=sk-ant-...
NCBI_EMAIL=<tu email>
```

Se carga solo al arrancar la CLI o el servidor web, así que basta con guardarlo
una vez. `.env` acepta las tres variables de la tabla de arriba.

Si una variable está definida en el entorno **y** en el `.env`, gana la del
entorno: el `.env` es el valor por defecto, no una imposición. Esto permite
probar otra clave puntualmente sin editar el archivo.

`.env` está en `.gitignore` y nunca debe subirse al repositorio. Lo que sí se
versiona es `.env.example`, siempre con los valores vacíos.

Las claves se leen siempre del entorno del proceso; nunca hay que escribirlas
en el código, y en el modo web nunca llegan al navegador.

## Uso

```bash
python cli.py buscar "SCN1A" --max 15 --dias 365
python cli.py buscar "síndrome de Dravet" --max 10
python cli.py buscar "SCN1A" --formato json > resultados.json
python cli.py buscar "Dravet syndrome" --autor "Scheffer IE"
python cli.py buscar --autor "Scheffer IE"          # solo autor
python cli.py buscar "toxoplasmosis" --patogeno "Toxoplasma gondii"
python cli.py buscar "SCN1A" --orden relevancia
```

| Argumento | Por defecto | Descripción |
|---|---|---|
| `término` (posicional) | — | Gen o síndrome (de enfermedades raras) a buscar. Opcional si se da `--autor` o `--patogeno` |
| `--autor` | — | Filtra por autor (campo `[AU]` de PubMed) |
| `--patogeno` | — | Filtra por patógeno |
| `--max` | 15 | Número máximo de papers a traer |
| `--dias` | 730 | Ventana de "recientes", en días |
| `--orden` | `fecha` | `fecha` (más recientes primero) o `relevancia` |
| `--idioma` | `es` | Idioma del **resumen** (`es` o `en`). La ayuda y los mensajes de la CLI siguen en español |
| `--formato` | `texto` | `texto` (resumen + referencias) o `json` |
| `--forzar` | off | Regenera el resumen ignorando la caché local |

### Favoritos

```bash
python cli.py favoritos listar
python cli.py favoritos marcar 38123456 --nota "Revisar la tabla 2"
python cli.py favoritos nota 38123456 "Nota corregida"
python cli.py favoritos nota 38123456 --borrar
python cli.py favoritos desmarcar 38123456        # pregunta si hay nota
```

Solo se pueden marcar papers que hayan aparecido en alguna búsqueda previa: sus
datos ya están en la base local, así que marcar y listar **no consultan
PubMed**. Un PMID desconocido falla con un mensaje que explica qué hacer, en vez
de crear un favorito sin título que enseñar.

Desmarcar borra también la nota. La CLI pregunta antes si hay una escrita
(`--si` para saltarse la pregunta); sin terminal interactiva responde que no,
para que un `pipe` no borre nada.

Códigos de salida: `0` correcto (incluida una búsqueda legítima sin
resultados), `1` error de uso o de configuración (incluidos un término fuera
del alcance de enfermedades raras y que falte `NCBI_EMAIL`), `2` fallo de una API externa o resumen no generado,
`3` límite diario de uso alcanzado.

### Salida en modo texto

Resumen en lenguaje llano, seguido de las referencias con título, autores,
revista, año, PMID y enlace a PubMed.

## Qué esperar de una búsqueda

**Búsqueda válida** (p. ej. `SCN1A`, `síndrome de Dravet`): resumen en lenguaje
llano, en el idioma elegido, donde cada afirmación termina con su cita `[PMID: ...]`,
seguido de las referencias con enlace a PubMed. El resumen solo se muestra si
ha superado la verificación automática: todos los PMIDs citados pertenecen a
los artículos realmente recuperados y no contiene consejo médico dirigido al
lector.

**Término fuera de alcance** (p. ej. `gripe`, `hipertensión`, un término no
médico): la búsqueda se bloquea **antes** de consultar PubMed, con un mensaje
que explica el motivo y sugiere buscar un gen o un síndrome raro. En la CLI
sale con código `1`; en la web aparece como error destacado. Nunca se disfraza
de "sin resultados".

**Término ambiguo** (p. ej. `epilepsia`, siglas con varios significados): la
búsqueda se ejecuta, pero con un aviso visible pidiendo interpretar los
resultados con cautela.

**Término escrito en español, catalán, euskera o gallego** (p. ej. `síndrome de
Dravet`, `Dravet sindromea`): la búsqueda se ejecuta **tal cual** —no se
traduce nada— con un aviso de que PubMed indexa sobre todo en inglés y de que
reescribir el término en inglés (o buscar por el nombre del gen, que es igual
en todos los idiomas) suele devolver bastantes más resultados. La detección es
local: no gasta llamadas a la API ni necesita la clave. Un nombre de gen
(`SCN1A`) o de síndrome (`Smith-Lemli-Opitz`) nunca dispara el aviso.

**Búsqueda solo por autor** (sin término ni patógeno): se ejecuta, con un aviso
de que no se ha podido comprobar el alcance —no hay ningún término médico que
clasificar— y de que los resultados pueden incluir trabajos del autor ajenos a
las enfermedades raras. El autor **nunca** se le manda al filtro de alcance: un
apellido no es un concepto médico. Este caso no gasta ninguna llamada a Claude.

**Sin resultados**: se dice explícitamente, con sugerencias (ampliar la
ventana de días, buscar por el gen en vez del síndrome).

**Fallos**: nunca en silencio. Si PubMed falla, se muestra el error y no se
inventa nada. Si falla la generación del resumen, se conservan y muestran las
referencias reales con el motivo del fallo. Ningún resumen se muestra sin haber
superado la verificación: un rechazo regenera el resumen con feedback, un fallo
técnico de la propia llamada de verificación cuenta también como intento
fallido, y agotados los 3 intentos el resumen se descarta explicando por qué
(las referencias reales se muestran igualmente).

**Coste**: cada búsqueda con resumen hace normalmente 3 llamadas a la API de
Claude (filtro de alcance + resumen + verificación), y hasta 2 más por cada
regeneración si la verificación rechaza el resumen. Repetir una búsqueda
reciente no cuesta nada: se sirve desde la caché local (ver abajo).

## Ordenar y afinar resultados

**Orden.** Por defecto los resultados salen de más recientes a más antiguos;
`--orden relevancia` (o el selector de la web) los pone en el orden que dio
PubMed. Cambiar de orden es una operación **local**: no vuelve a consultar
PubMed, no gasta llamadas y no cambia qué artículos hay. En empate de fecha
—frecuente, porque muchos artículos solo traen el año— desempata el orden de
relevancia, que es estable y reproducible.

Para que "relevancia" signifique algo, la búsqueda pide a PubMed
`sort=relevance` y guarda la posición devuelta. Eso implica que el conjunto que
se trae son **los N más relevantes** de la ventana temporal, no los N más
recientes; la ventana (`--dias`) se sigue aplicando igual.

**Afinar en pantalla vs. buscar.** Son cosas distintas y la interfaz lo dice:

- Los campos de «Búsqueda avanzada» (autor, patógeno) entran en la consulta que
  se manda a PubMed, así que **pueden traer artículos nuevos**.
- Los campos de «Afinar» de la web solo esconden filas de las que ya están.
  **No consultan PubMed y no pueden traer nada nuevo.** Por eso el contador dice
  siempre "N de M resultados mostrados": filtrar 15 resultados por autor y ver 2
  no significa que ese autor tenga 2 artículos sobre el tema.

## Llevar el resumen a NotebookLM

En la web, bajo cada resumen hay un botón **«Copiar para NotebookLM»**. Copia al
portapapeles una versión en texto plano del resultado:

- el término buscado (y el autor o patógeno, si los hubo),
- el resumen íntegro con sus citas `[PMID: ...]`,
- las referencias con título, revista, PMID y enlace a PubMed,
- el aviso de que esto no es una herramienta de diagnóstico.

Para usarlo: pulsa el botón, abre [NotebookLM](https://notebooklm.google.com/)
(o Gemini Notebook), añade una fuente del tipo **«Texto copiado»** y pega. El
texto lleva el término de búsqueda de encabezado, así que la fuente se explica
sola dentro del cuaderno sin tener que recordar de dónde salió.

No hay integración automática con NotebookLM a propósito: hacerlo requeriría una
librería no oficial y las credenciales de una cuenta de Google real. Copiar y
pegar hace el mismo trabajo sin ese riesgo.

Si el navegador no da acceso al portapapeles (permiso denegado, navegador
antiguo, o servido por `http` fuera de `localhost`), el texto aparece en un
cuadro ya seleccionado para copiarlo con Ctrl+C — nunca falla en silencio.

Desde la CLI el equivalente es `--formato json`, o redirigir la salida de texto
a un archivo:

```bash
python cli.py buscar "SCN1A" > scn1a.txt
```

## Idiomas

La web está en español e inglés. Se cambia con el conmutador de la cabecera
(`?idioma=en`) y la elección se recuerda en una cookie, así que sobrevive a las
búsquedas (que son POST) y a la vista de favoritos (que redirige).

El idioma no es solo de la interfaz: **el resumen se genera en el idioma
elegido**, el verificador lo revisa con las reglas de esa lengua, el aviso de no
diagnóstico sale traducido y el texto exportado para NotebookLM también. La
caché lleva el idioma en su clave, así que un resumen español no se sirve nunca
a quien pidió inglés (ni al revés). En la CLI se elige con `--idioma`.

Los prompts del resumidor y del verificador **no** están en `i18n/`, sino en
[`src/paper_search/prompts.py`](src/paper_search/prompts.py): esa carpeta se
compila al `messages.json` de la extensión de Chrome, y un prompt acabaría
empaquetado ahí. Un prompt no es una cadena de interfaz.

Todos los textos de interfaz viven en **una sola fuente**, `paper-search/i18n/`:

```
i18n/
├── es.json      # idioma de referencia: el único que tiene que estar completo
├── en.json      # traducción
└── meta.json    # descripción y orden de placeholders (no depende del idioma)
```

Los archivos por idioma son `clave: "texto"` plano, con placeholders `$nombre$`:

```json
{
  "form_boton_buscar": "Buscar",
  "fil_contador": "$visibles$ de $total$ resultados mostrados"
}
```

**Para traducir o corregir un texto** basta con editar el JSON del idioma: no
hay que tocar plantillas ni código. Para **añadir un idioma**, se copia
`es.json`, se traduce, y se añade el código a `IDIOMAS` en
`src/paper_search/i18n.py`.

Si una clave falta en un idioma se usa la del idioma de referencia, y si no
está en ninguno se muestra la propia clave (`form_boton_buscar`), que señala
qué falta y dónde. Una traducción a medias degrada el texto; nunca rompe la
página.

Las claves van en `snake_case` con prefijo de área (`form_`, `res_`, `fav_`,
`alc_`…) y sin puntos: es lo único que admite `chrome.i18n`, y así la misma
clave sirve para la web y para la extensión sin transformarla.

### Generar los `_locales/` para la extensión de Chrome

La extensión de Chrome (Fase 5.3) necesita las mismas cadenas en el formato
propio de `chrome.i18n`. Se generan desde la misma fuente, sin mantener un
segundo diccionario:

```bash
python herramientas/generar_locales.py            # a extension/_locales/
python herramientas/generar_locales.py --comprobar   # ¿está al día?
```

Sale `extension/_locales/<idioma>/messages.json`, que es donde Chrome exige
encontrarlos: dentro del paquete de la extensión. Ver `extension/README.md`.

Después de editar `i18n/*.json`, hay que regenerar: un test
(`test_los_locales_del_repo_estan_al_dia`) falla si se olvida.

**Qué NO está traducido todavía**: la CLI (sus textos de `argparse` son otra
superficie y no sirven a la extensión) y los mensajes técnicos de fallo de la
API de Anthropic y de PubMed, que siguen en español. La web —interfaz, errores
de formulario, avisos de alcance e idioma y errores de favoritos— sí lo está.

## Instalar como aplicación (PWA)

La web se puede instalar como aplicación: se abre en su propia ventana, sin
barra de direcciones ni pestañas, y con su icono en la barra de tareas. En
Chrome o Edge, con paper-search en marcha, aparece el icono de instalar en la
barra de direcciones.

El icono es una lupa de trazo grueso en oro con una cruz médica maciza dentro
de la lente, sobre near-black. Usa los tokens del sistema de diseño
(`--color-text`, `--color-accent`, `--color-bg`), así que no desentona con el
resto de la interfaz.

La fuente es `static/iconos/paper-search-icon.svg`; los PNG que pide el
manifest se derivan de él:

```bash
python herramientas/generar_iconos.py
python herramientas/generar_iconos.py --comprobar   # ¿están al día?
```

Hay además una variante `-transparent.svg` para fondos claros. Si se retoca el
icono, se retoca el SVG y se regenera: un test falla si los PNG se quedan
atrás.

### Qué funciona sin conexión y qué no

paper-search corre en tu propio ordenador (`127.0.0.1`), así que «sin conexión»
son dos cosas distintas y conviene no confundirlas:

**Sin internet, con paper-search en marcha** — que es el caso normal, quedarse
sin wifi:

| | |
|---|---|
| Ver la interfaz | ✅ funciona |
| Ver tus favoritos y sus notas | ✅ funciona |
| Escribir, editar y borrar notas | ✅ funciona |
| Marcar y desmarcar favoritos | ✅ funciona |
| Buscar en PubMed | ❌ necesita internet |
| Generar resúmenes | ❌ necesita internet |

Los favoritos funcionan enteros porque la base de datos es local. Solo fallan
PubMed y la API de Claude, que son servicios externos. La app te lo dice con un
aviso y **no te deja lanzar una búsqueda que no puede funcionar**, en vez de
dejarte esperando.

**Con paper-search apagado** (no arrancaste `run.bat`, o lo cerraste):

| | |
|---|---|
| Abrir la app y ver la interfaz | ✅ desde la copia guardada |
| Ver los favoritos que visitaste antes | ⚠️ copia guardada, **solo lectura** |
| Cualquier cosa que escriba | ❌ deshabilitado |
| Buscar | ❌ |

Cuando lo que ves es una copia guardada, sale un aviso arriba diciendo de qué
momento es y que no se puede editar, y los formularios quedan deshabilitados.
Es a propósito: una nota que borraste hace un rato seguiría apareciendo, y
guardar cambios fallaría en silencio.

**Lo que no hace, a propósito:**

- No guarda resultados de búsqueda para enseñarlos sin conexión. Un resumen
  viejo presentado como nuevo es justo lo que esta herramienta evita.
- No encola cambios «para cuando vuelva la conexión». Si algo no se puede
  guardar, se dice en el momento.

## Usarlo desde el móvil (misma wifi)

Por defecto el servidor solo escucha en `127.0.0.1`, que alcanza únicamente
este ordenador. Para entrar desde el móvil hay que abrirlo a la red **a
propósito**:

```bash
python app.py --red
```

o doble clic en **`run-red.bat`**, que pregunta antes de continuar. También
vale `PAPER_SEARCH_RED=1`, pensado para quien arranca con `flask run`.

Al arrancar así, la consola imprime la dirección exacta que hay que escribir en
el móvil —detecta la IP de este equipo, no hay que buscarla— junto con la
advertencia de lo que se está abriendo.

> ### Lo que estás aceptando
>
> **No hay contraseña de ningún tipo.** Cualquiera conectado a esa wifi que
> sepa la dirección puede:
>
> - leer tus favoritos y tus notas personales,
> - ver todo lo que has buscado,
> - lanzar búsquedas que gastan tu clave de la API y tu cuota diaria — es
>   decir, tu dinero.
>
> Úsalo en tu red de casa, no en una wifi pública ni compartida, y apágalo
> cuando termines: sin `--red` vuelve a escuchar solo en este equipo.

### Qué NO funciona desde el móvil

Sobre la red local la dirección es `http://192.168.x.x:5000`, y el navegador
**no** considera eso un «contexto seguro» (solo lo son `https` y `localhost`).
Conviene saberlo antes de probarlo:

| | Desde el móvil por wifi |
|---|---|
| Buscar, resúmenes, referencias | ✅ |
| Favoritos y notas | ✅ |
| Orden, filtros, idiomas | ✅ |
| Instalar como app (PWA) | ❌ el navegador no lo ofrece |
| Funcionamiento sin conexión | ❌ no se registra el service worker |
| Botón «Copiar para NotebookLM» | ⚠️ cae a seleccionar y copiar a mano |

**En el móvil es una web normal, no una PWA.** No es un fallo: los service
workers exigen HTTPS o localhost, y una IP de red local no cumple ninguna de
las dos. En el ordenador, donde se abre por `127.0.0.1`, la PWA sigue
instalándose y funcionando sin conexión como siempre.

Montar HTTPS lo arreglaría, pero no basta con un certificado autofirmado —el
navegador bloquea los service workers en un origen con error de certificado—:
haría falta una CA propia instalada también en el móvil. Es bastante montaje
para lo que se gana, así que de momento se queda así. Un túnel público está
descartado por otro motivo: haría pasar búsquedas médicas por un tercero.

La extensión de Chrome no necesita ningún cambio: se usa desde el ordenador, y
ahí `127.0.0.1` sigue funcionando aunque el servidor escuche también en la red.

## Caché, límites y registro locales

Todo vive en un único archivo SQLite, por defecto
`paper-search/datos/paper-search.db` (configurable con `PAPER_SEARCH_DB` en el
`.env`). No hay servidor aparte y el archivo no se sube al repo. Si no se
puede abrir, la búsqueda funciona igualmente — se avisa y se sigue sin caché
ni registro.

**Caché de resúmenes.** Antes de generar un resumen se comprueba si ya existe
uno vigente para ese término *y ese mismo conjunto de papers*: si PubMed
devuelve algún paper nuevo, la caché se ignora sola y el resumen se regenera.
Un resumen servido desde caché lo indica claramente (CLI y web) junto con la
fecha en que se generó. Caducidad: 30 días (`PAPER_SEARCH_CACHE_DIAS`). Para
regenerar a mano: `--forzar` en la CLI o la casilla «Regenerar el resumen» en
la web (ignoran también el veredicto de alcance cacheado). Los veredictos del
filtro de alcance se cachean igualmente, así que repetir una búsqueda cacheada
consume 0 llamadas a Claude.

**Límites diarios de uso.** Dos límites independientes con reseteo a
medianoche (hora local): búsquedas al día (50 por defecto,
`PAPER_SEARCH_MAX_BUSQUEDAS_DIA`) y llamadas a la API de Claude al día (200
por defecto, `PAPER_SEARCH_MAX_LLAMADAS_DIA`). Se cuenta cada llamada real —
una búsqueda con reintentos de verificación puede consumir 5-7 — y al alcanzar
un límite el mensaje dice cuál fue y cuándo se resetea (CLI: código de salida
3; web: HTTP 429). Es independiente del rate limiting hacia PubMed, que sigue
en `pubmed_client.py`.

**Registro de acciones.** Cada búsqueda queda anotada: término, parámetros,
resultado (éxito, sin resultados, bloqueo por alcance o por límite, error de
PubMed o de resumen), si vino de caché, cuántas llamadas a Claude consumió y
qué PMIDs devolvió. Sirve para auditoría y depuración, y de ahí salen los datos
de los papers que se pueden marcar como favoritos. El registro en sí todavía no
se muestra en la interfaz.

## Modo doble clic (interfaz web local)

Para uso diario sin terminal: doble clic en `run.bat`. Instala las dependencias
la primera vez, arranca el servidor local y abre el navegador solo en
<http://127.0.0.1:5000>. Cerrar la ventana de consola (o Ctrl+C) detiene el
servidor.

También se puede arrancar a mano:

```bash
python app.py
```

El formulario tiene las mismas opciones que la CLI (término, máx. papers,
ventana en días, orden, «Regenerar el resumen» y, en «Búsqueda avanzada», autor
y patógeno; el idioma se elige en la cabecera) y devuelve exactamente el mismo
resultado: por debajo llama a la misma función `buscar_y_resumir` del paquete.

Por defecto el servidor escucha solo en `127.0.0.1`: es una herramienta local
para una persona, no un servicio de red. Solo se abre a la red local si se pide
a propósito con `--red` (ver «Usarlo desde el móvil»). La clave de API vive únicamente
en el proceso Python y nunca llega al navegador — por eso hay un backend y no
un HTML suelto.

Dentro del resumen, cada cita `[PMID: ...]` es un enlace al artículo en PubMed
(solo si ese PMID está entre los recuperados), y debajo está la lista de
referencias: se ve de un vistazo qué afirmación se apoya en qué paper.

### Estilos

`static/classical.css` es el sistema de diseño (tokens de color, tipografía,
espaciado y clases `.btn` / `.input` / `.card`), copiado tal cual del proyecto
de Claude Design `b184134d-3e1e-4c07-b8fc-a88271b2fc6d`. **No se edita a mano**:
si cambia el diseño se vuelve a copiar desde allí. Lo específico de esta página
—rejilla, aviso, resaltado de PMIDs, spinner— vive en `static/paper-search.css`.

Las fuentes (Cormorant Garamond y Lora) se cargan de Google Fonts; sin conexión
la página cae a la tipografía del sistema y todo lo demás funciona igual.

### Salida en modo JSON

Pensado para que lo consuman otras herramientas del repo (ver
`../docs/roadmap.md`). Estructura estable:

```json
{
  "query": "SCN1A",
  "resumen": "texto del resumen, o null si no se pudo generar",
  "papers": [
    {
      "pmid": "42495533",
      "titulo": "...",
      "autores": ["Lascorz R", "Roth FC"],
      "revista": "iScience",
      "fecha": "2026-08-21",
      "abstract": "...",
      "url": "https://pubmed.ncbi.nlm.nih.gov/42495533/",
      "orden_relevancia": 1
    }
  ],
  "total": 1,
  "dias": 365,
  "error_resumen": null,
  "aviso_alcance": null,
  "aviso_idioma": null,
  "orden": "fecha",
  "criterios": {"termino": "SCN1A", "autor": null, "patogeno": null},
  "desde_cache": false,
  "cache_creado_en": null,
  "aviso": "Esta herramienta es una ayuda de búsqueda..."
}
```

`resumen` es `null` **siempre** que no haya un resumen real y verificado:
nunca se rellena con texto aproximado ni se entrega sin verificar. Cuando es
`null` por un fallo o un rechazo de la verificación, `error_resumen` explica el
motivo. `aviso_alcance` se rellena si el término era ambiguo o el filtro de
alcance no se pudo ejecutar; `aviso_idioma`, si el término parecía escrito en
español, catalán, euskera o gallego. `desde_cache` y `cache_creado_en` indican
si el resumen se sirvió desde la caché local y cuándo se generó originalmente.
`orden` es el criterio con el que viene ordenado `papers` (cada paper lleva en
`orden_relevancia` la posición que le dio PubMed), y `criterios` lo que se
escribió campo a campo (`query` es la consulta ya montada que se mandó a PubMed).

## Tests

```bash
python -m pytest tests/ -v
```

Las respuestas de la API están mockeadas/grabadas, así que la suite es rápida y
no depende de que PubMed o Anthropic estén disponibles (la persistencia se
prueba contra una BD en memoria). Cubre, entre otros casos: que la API no
devuelva resultados, que la API falle, el filtro de alcance (término válido,
fuera de alcance, ambiguo, fallo de la verificación), la verificación del
resumen (limpio, sin cita, con consejo médico, PMID inventado, reintentos
agotados), la caché (hit, miss, caducada, `--forzar`), los límites diarios
(por debajo, alcanzados, reseteo al cambiar de día) y el registro de acciones.

## Arquitectura

```
paper-search/
├── cli.py                        # solo argparse + printing, sin lógica
├── app.py                        # servidor Flask local (modo doble clic)
├── run.bat                       # doble clic: instala, arranca y abre el navegador
├── run-red.bat                   # igual, pero abierto a la wifi (pregunta antes)
├── templates/                    # búsqueda, favoritos, página sin conexión, service worker
├── static/classical.css          # sistema de diseño, copiado de Claude Design
├── static/paper-search.css       # estilos propios de la página
├── static/conexion.js            # registro del service worker y avisos de conexión
├── static/iconos/                # icono SVG fuente y PNG derivados
├── i18n/                         # textos de interfaz en es/en (fuente única)
├── herramientas/                 # generadores de _locales/ e iconos
├── .env.example                  # plantilla de claves (el .env real no se sube)
├── conftest.py                   # hace importable src/ en los tests
├── datos/                        # BD SQLite local (no se versiona)
├── src/paper_search/
│   ├── __init__.py               # API pública: buscar_y_resumir(...)
│   ├── config.py                 # carga del .env, sin pisar el entorno
│   ├── pubmed_client.py          # esearch/efetch, rate limiting, parseo XML
│   ├── alcance.py                # filtro de alcance (solo enfermedades raras)
│   ├── idioma.py                 # aviso si el término no está en inglés
│   ├── busqueda.py               # criterios (autor, patógeno) y filtros locales
│   ├── orden.py                  # ordenación por fecha o relevancia
│   ├── favoritos.py              # papers marcados y sus notas
│   ├── exportar.py               # texto plano para pegar en NotebookLM
│   ├── i18n.py                   # traducción: cargador, traducir(), fallback
│   ├── locales.py                # generador del formato chrome.i18n
│   ├── pwa.py                    # política de caché de la PWA
│   ├── red.py                    # modo red local (--red), apagado por defecto
│   ├── prompts.py                # prompts del resumidor y del verificador, por idioma
│   ├── summarizer.py             # resumen en lenguaje llano
│   ├── verificacion.py           # verificación del resumen + reintentos
│   ├── db.py                     # SQLite local: conexión, esquema, migraciones
│   ├── cache.py                  # caché de resúmenes y veredictos de alcance
│   ├── limites.py                # límites diarios de uso propios
│   ├── registro.py               # registro de acciones (auditoría)
│   └── models.py                 # Paper, ResultadoBusqueda
└── tests/
```

**Rate limiting.** El cliente espacia sus propias peticiones (3/s sin API key,
10/s con ella) y reintenta los errores transitorios de NCBI con backoff
exponencial, respetando la cabecera `Retry-After`. Quien llama no tiene que
preocuparse de no pasarse dentro de un bucle.

**Nunca se inventan resultados.** Si PubMed falla se lanza un error; si no hay
artículos se dice explícitamente. Un registro sin PMID se descarta porque no
sería verificable. Además, la verificación automática descarta cualquier
resumen que cite un PMID ajeno a los artículos recuperados.

## Limitaciones actuales

- **Alcance restringido a enfermedades raras.** Un término médico ajeno a ellas
  (enfermedades comunes) o no médico se bloquea antes de buscar. Términos
  médicos ambiguos pasan con aviso. El filtro lo hace un modelo, así que puede
  equivocarse en casos límite: si bloquea un término que crees legítimo, prueba
  con el nombre del gen o el nombre oficial del síndrome.
- **La fuente está en inglés.** PubMed indexa casi todo en inglés y los
  abstracts que alimentan el resumen están en inglés; el resumen se escribe en
  el idioma elegido. Buscar en español funciona a veces para nombres de
  síndrome muy establecidos ("síndrome de Dravet"), pero es menos fiable que
  buscar por el gen (`SCN1A`) o por el nombre en inglés. Si el término parece
  escrito en español, catalán, euskera o gallego, la herramienta **avisa** (ver
  «Qué esperar de una búsqueda»), pero no lo traduce: se busca tal cual.
- **La verificación no es infalible.** La capa determinista garantiza que
  ningún PMID citado sea inventado, pero juzgar si una afirmación necesita cita
  o constituye consejo médico lo hace un modelo. Por eso el aviso permanente:
  verifica cada afirmación en el paper original.
- **Fuera de esta versión:** traducir los abstracts, enseñar en la interfaz
  un historial de búsquedas (se anotan en el registro local, pero no se
  muestran) y cachear los resultados de PubMed. Solo se cachean los resúmenes y
  los veredictos de alcance, así que cada búsqueda vuelve a consultar PubMed.

## Licencia

[MIT](../LICENSE) © 2026 Alejandro Estevez Ruiz. Cubre todo el repositorio
`rare-disease-tools`, incluida la extensión de Chrome.
