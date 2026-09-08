# Registro de decisiones

Log corto de decisiones de diseño no triviales tomadas durante el
desarrollo, con fecha y motivo breve. Formato: `YYYY-MM-DD — [componente] decisión. Motivo.`

2026-07-28 — [paper-search] Un fallo al generar el resumen no descarta los papers ya
obtenidos: se devuelven con `resumen=None` y el motivo en `error_resumen`, y la CLI los
imprime junto al error y sale con código 2. Motivo: el brief pide fallar con un mensaje
claro si falta `ANTHROPIC_API_KEY`, pero tirar los resultados reales de PubMed que ya
teníamos sería peor para el usuario. Sigue sin inventarse nada: o hay resumen real o hay
motivo explícito.

2026-07-28 — [paper-search] `ANTHROPIC_API_KEY` se exige literalmente como variable de
entorno, sin caer en otras fuentes de credenciales del SDK (perfiles OAuth de `ant`).
Motivo: es lo que dice el brief y hace el fallo predecible; si algún día se usan perfiles,
basta con relajar la comprobación en `summarizer._crear_client`.

2026-07-28 — [paper-search] En `esearch` se usa `sort=pub_date` en vez del `sort=pub+date`
que aparece en `docs/api-notes.md`. Motivo: `pub_date` es la grafía documentada por NCBI y
`pub+date` se escaparía como `pub%2Bdate` al construir la query con `requests`. Verificado
contra la API real.

2026-07-28 — [paper-search] El JSON añade `total`, `dias`, `error_resumen` y `aviso` a las
claves `query`/`resumen`/`papers` del brief. Motivo: el modo JSON es el que consumirá el
clasificador de síntomas (fase 2) y necesita saber si hubo resumen y por qué no, sin
parsear texto. Las claves del brief no cambian de forma ni de tipo.

2026-07-28 — [paper-search] La orquestación (`buscar_y_resumir`) vive en `__init__.py` y no
en `cli.py`. Motivo: el brief exige que la CLI sea solo argparse + printing, y esa función
es además la API pública que reutilizará la fase 2.

2026-07-28 — [paper-search] La excepción base `PaperSearchError` se define en `models.py` en
vez de crear un `errors.py`. Motivo: mantener el árbol de ficheros exactamente como lo
describe el brief.

2026-07-28 — [paper-search] Se añade `conftest.py` en la raíz del componente para poner
`src/` en `sys.path` y aislar las variables de entorno en los tests. Motivo: permite
`pytest tests/ -v` sin instalar el paquete ni definir `PYTHONPATH`, y evita que una
`ANTHROPIC_API_KEY`/`NCBI_API_KEY` presente en la máquina cambie el resultado de la suite.

2026-07-28 — [paper-search] El email de contacto para NCBI se lee de `NCBI_EMAIL` con el
del autor como valor por defecto en el código. Motivo: NCBI pide un contacto real y no un
placeholder. Si el repo se hace público conviene mover el valor por defecto a la variable de
entorno.

2026-07-28 — [paper-search] El resumen usa `claude-opus-5` por la vía estable
(`client.messages.create`), sin parámetros de thinking ni `fallbacks` de servidor. Motivo:
mantener la v1 simple; los rechazos del modelo (`stop_reason == "refusal"`) se detectan y se
convierten en error explícito en vez de en un resumen vacío. Si aparecen rechazos en
contenido biomédico legítimo, el siguiente paso son los fallbacks de servidor.

2026-07-28 — [paper-search] Un registro de PubMed sin PMID se descarta al parsear. Motivo:
sin PMID no hay trazabilidad, y la regla del repo es no presentar nada que no se pueda
verificar en la fuente original.

2026-07-30 — [paper-search] La web local usa una plantilla única `templates/index.html` que
sirve el formulario y los resultados, en vez de HTML inline o dos plantillas. Motivo: el
brief deja elegir; con una sola plantilla el POST puede devolver la página con el formulario
ya relleno cuando hay error, sin duplicar el marcado.

2026-07-30 — [paper-search] La búsqueda web es una petición POST síncrona y el estado
"buscando..." se resuelve con tres líneas de JS (aviso visible + botón deshabilitado), sin
endpoint JSON ni polling. Motivo: es lo más simple que cumple el brief, y bloquear el botón
evita lanzar dos búsquedas a PubMed a la vez desde la misma pestaña.

2026-07-30 — [paper-search] `app.py` distingue los errores por código HTTP: 400 para entrada
inválida del formulario y 502 para un `PaperSearchError` de PubMed. Un fallo del resumen no
es error de página: se renderizan las referencias reales con el motivo del fallo destacado,
igual que hace la CLI. Motivo: mantener la misma regla del repo (nunca inventar y nunca
tirar datos reales ya obtenidos) también en la interfaz web.
2026-08-03 — [paper-search] El `.env` se carga en los puntos de entrada (`cli.py` y
`app.py`) llamando a `cargar_env()`, no al importar el paquete. Motivo: importar
`paper_search` como librería (fase 2) no debe tener el efecto colateral de escribir en
`os.environ`, y así los tests siguen aislados del `.env` real de la máquina — ninguno usa la
ruta por defecto. La comprobación de `summarizer._crear_client` no cambia: sigue exigiendo la
variable en el entorno, solo que ahora alguien puede haberla puesto desde el archivo.

2026-08-03 — [paper-search] La carga del `.env` vive en un módulo nuevo `config.py`, que se
sale del árbol de ficheros del brief. Motivo: no encajaba en `models.py` (no es un dato),
`summarizer.py` (el `.env` también trae las variables de NCBI) ni `pubmed_client.py`. El
módulo es pequeño y tiene sus propios tests en `tests/test_config.py`.

2026-08-03 — [paper-search] El entorno del sistema gana sobre el `.env` (`load_dotenv` con
`override=False`). Motivo: es lo que pidió el autor y permite probar otra clave puntualmente
sin editar el archivo. Efecto secundario útil: copiar `.env.example` tal cual, con la clave
vacía, no rompe a quien ya tenía la variable exportada.

2026-08-03 — [paper-search] Si hay un `.env` pero falta `python-dotenv`, se avisa por
`logging.warning` y se sigue con las variables del sistema, en vez de fallar. Motivo: la
regla del repo es no fallar en silencio, pero quedarse sin arrancar por una dependencia de
comodidad sería peor; el aviso deja claro que el archivo no se ha leído.

2026-08-03 — [paper-search] La interfaz web adopta el diseño `paper-search.dc.html` del
proyecto de Claude Design `b184134d-3e1e-4c07-b8fc-a88271b2fc6d`. Del `.dc.html` se porta la
estructura, los estados y los estilos; NO se porta nada de `support.js`, `x-dc`, `sc-if`,
`sc-for` ni `DCLogic`. Motivo: ese es el arnés de previsualización (React) del canvas de
diseño, y en la app real ese papel ya lo hacen Jinja y el backend Flask.

2026-08-03 — [paper-search] Los datos de ejemplo del diseño (la constante `REFERENCES` y
`buildSummary()`, con seis papers y PMIDs inventados) se descartan por completo. Motivo:
regla del repo — nunca se muestra nada que no venga de PubMed. El estado "vacío" de la
maqueta se rellena con datos reales o no se rellena.

2026-08-03 — [paper-search] `segmentar_resumen` (trocear el resumen en párrafos y marcar las
citas `[PMID: ...]`) vive en `models.py` y no en la plantilla ni en `app.py`. Motivo: es
lógica de texto reutilizable y testeable, y renderizar segmentos en vez de HTML marcado
evita tener que usar `|safe` sobre texto que viene de un modelo. El texto no se altera: solo
se marca dónde está cada cita, así que un resumen sin citas se muestra igual de entero.

2026-08-03 — [paper-search] La card de "resumen no disponible" del diseño lleva además el
motivo real (`error_resumen`), que la maqueta no contemplaba. Motivo: la regla del repo pide
decir explícitamente por qué no hay resumen (p. ej. falta `ANTHROPIC_API_KEY`); el texto
genérico del diseño solo dice que no se pudo.

2026-08-03 — [paper-search] Se descarta el botón "Simular resumen no disponible" del diseño y
el estado de carga se enciende desde el `submit` en vez de con un `setTimeout`. Motivo: eran
andamiaje de la maqueta para poder enseñar los estados sin backend.

2026-08-03 — [paper-search] Los tests de la web (`tests/test_app.py`) sustituyen
`buscar_y_resumir` en el módulo `app` por un doble, y `conftest.py` añade la raíz del
componente a `sys.path` para poder importar `app.py`. Motivo: se quiere probar el
renderizado de los estados y los códigos HTTP sin tocar PubMed ni Anthropic.

2026-07-30 — [paper-search] Pendiente: detectar cuando el término de búsqueda está en español y avisar/traducir automáticamente, porque PubMed indexa mayoritariamente en inglés y el mapeo de términos en español no es fiable para nombres de síndromes.

2026-08-09 — [paper-search] Guardarraíl de alcance (`alcance.py`): si la llamada de
verificación a la API de Claude falla (timeout, API caída, clave ausente, respuesta
irreconocible), la búsqueda se deja pasar con un aviso visible en vez de bloquearse
("fail-open"), confirmado por el autor. Motivo: el guardarraíl delimita el alcance del
producto, no protege contra resultados inventados — los papers vienen de PubMed reales y el
resumidor tiene sus propias reglas. Bloquear toda búsqueda con la API de Anthropic caída
dejaría inservible incluso la parte que hoy funciona sin `ANTHROPIC_API_KEY`.

2026-08-09 — [paper-search] El clasificador de alcance distingue tres veredictos
(`dentro_de_alcance` / `ambiguo` / `fuera_de_alcance`) en vez de un booleano, con respuesta
estructurada (`output_config.format` con JSON Schema, parseo con `json.loads` sin
heurísticas). "Ambiguo" deja pasar con aviso; el prompt pide preferir ambiguo ante la duda.
Motivo: un booleano obligaría a elegir entre bloquear términos médicos legítimos (p. ej.
"epilepsia", siglas) o dejar pasar todo, y el coste de un falso bloqueo es mayor que el de
una búsqueda de más.

2026-08-09 — [paper-search] Un término fuera de alcance lanza `TerminoFueraDeAlcanceError`
antes de tocar PubMed; la CLI sale con código 1 (uso) y no 2 (fallo de API), y la web lo
trata como los errores de formulario (400) y no como fallo de PubMed (502). Motivo: es un
problema de la entrada del usuario, no de las APIs externas.

2026-08-09 — [paper-search] La llamada de verificación usa el mismo modelo que el resumen
(`claude-opus-5`, constante compartida) con `effort: "low"`, `max_tokens` 2000 y timeout de
15 s. Motivo: una clasificación no necesita razonamiento profundo y no debe colgar la
búsqueda; si aun así se agota el timeout, cae en el fail-open con aviso. No se baja a un
modelo menor sin decisión explícita del autor.

2026-08-09 — [paper-search] La verificación del resumen (`verificacion.py`) tiene dos capas:
una determinista en código (todo PMID citado debe estar en la lista real de artículos y el
resumen debe citar al menos una vez, con el `PATRON_CITA` que ya existía) y la llamada a la
API de Claude (afirmaciones sin cita + consejo médico, respuesta estructurada). Motivo: un
PMID inventado se detecta gratis y de forma exacta en local, y la llamada se reserva para lo
que el código no puede juzgar. Un resumen rechazado se regenera pasando los problemas
concretos al prompt; `MAX_INTENTOS = 3` (1 generación + 2 regeneraciones), y al agotarse se
descarta el resumen con `ResumenError` visible (los papers reales se conservan, mismo camino
que el resto de fallos de resumen).

2026-08-09 — [paper-search] Si la llamada de verificación del resumen falla (timeout, API,
clave), el fallo cuenta como INTENTO FALLIDO con su propio tipo de problema
(`no_verificado`, detalle "no se pudo verificar: [motivo]") y el resumen NO se entrega
("fail-closed", decidido por el autor, que revierte el fail-open-con-aviso implementado
inicialmente y elimina el campo `aviso_resumen`). Agotados los `MAX_INTENTOS`, se descarta
el resumen con `ResumenError` visible. Motivo: la regla del repo es que la precisión importa
más que la completitud — un resumen sin verificar no cumple la garantía que promete la fase
1, mientras que las referencias de PubMed (que sí se conservan y muestran) cubren la
necesidad informativa. Contraste deliberado con el guardarraíl de alcance (Tarea 1), que es
fail-open: allí un fallo de verificación solo afecta al *alcance del producto* y bloquear
dejaría inservible la búsqueda de PubMed, que no depende de Claude; aquí afecta a la
*fiabilidad del contenido médico mostrado*, y lo que está en juego si se deja pasar es
precisamente lo que la verificación existe para garantizar.

2026-08-09 — [paper-search] El feedback de regeneración viaja como parámetro `correcciones`
de `Summarizer.resumir`/`construir_prompt` (un bloque de texto al final del prompt), no como
turno adicional de conversación. Motivo: mantiene el resumidor sin estado y el prompt en un
solo mensaje de usuario, igual que hasta ahora.

2026-08-09 — [paper-search] La documentación de uso de la fase 1 (guardarraíles, qué esperar
de una búsqueda, limitaciones) se integra en el `README.md` del componente en vez de crear un
`USO.md` aparte. Motivo: el README ya era el documento de instalación y uso (claves, `.env`,
CLI, `run.bat`); un segundo archivo duplicaría esas secciones y acabarían divergiendo.

2026-08-10 — [paper-search] Fase 2: SQLite local (`db.py`) con esquema v1 aprobado por el
autor: `esquema_version`, `resumenes_cache`, `veredictos_alcance`, `uso_diario`, `papers`,
`acciones`. Migraciones como lista ordenada de scripts SQL re-ejecutables (`IF NOT EXISTS`);
añadir una migración = añadir un script al final, nunca editar los anteriores. Ruta por
defecto `paper-search/datos/paper-search.db` (en `.gitignore`), configurable con
`PAPER_SEARCH_DB`.

2026-08-10 — [paper-search] Del "índice sobre termino/pmid en acciones" pedido por el autor
se implementa `idx_acciones_termino`; para `pmids` no se crea índice porque la columna es un
array JSON y un índice B-tree normal solo serviría para igualdad exacta del array completo.
Si la Fase 3 necesita buscar acciones por PMID individual, la solución es una tabla puente
`accion_pmids` en la migración v2, no un índice sobre el JSON.

2026-08-10 — [paper-search] La clave de la caché de resúmenes es (término normalizado +
hash SHA-256 del conjunto ordenado de PMIDs), no el término solo. Motivo: la búsqueda a
PubMed se hace siempre (barata, sin coste Claude) y la caché ahorra lo caro; si aparece un
paper nuevo, el conjunto de PMIDs cambia y la caché falla sola — nunca se sirve un resumen
que ignore papers nuevos. La caducidad (30 días, `PAPER_SEARCH_CACHE_DIAS`) se calcula al
leer, no se guarda: cambiar la config afecta también a lo ya cacheado. Solo se cachean
resúmenes que superaron la verificación (`verificar_resumen=False` no escribe en caché), y
los veredictos de alcance `no_concluyente` no se cachean (se reintentan). `--forzar` (CLI) /
la casilla "Regenerar" (web) ignoran ambas cachés.

2026-08-10 — [paper-search] `buscar_y_resumir(db=None)` significa "librería pura": sin
caché, sin límites y sin registro. La persistencia se activa pasando la conexión, y son la
CLI y `app.py` quienes abren la BD; si no se puede abrir, avisan y siguen sin persistencia
(la búsqueda no debe depender de un archivo local corrupto). Motivo: los tests y el uso como
librería (Fase 3) no deben escribir en la BD real por importar el paquete.

2026-08-10 — [paper-search] Límites diarios: se comprueban ambos al INICIO de la búsqueda y
cada llamada real a Claude incrementa el contador vía un callback `contador` inyectado en
`VerificadorAlcance.verificar`, `Summarizer.resumir` y `VerificadorResumen.verificar` — una
búsqueda con reintentos puede sumar 5-7 llamadas, y un cache-hit suma 0. Una búsqueda en
marcha se termina aunque cruce el límite a mitad (abortar tiraría trabajo ya pagado); la
siguiente ya no arranca. El día es fecha LOCAL (el usuario piensa en "hoy") y el reseteo es
implícito: fila nueva por día, las viejas quedan como histórico. CLI sale con código 3 y la
web responde 429. Defaults: 50 búsquedas/día y 200 llamadas/día
(`PAPER_SEARCH_MAX_BUSQUEDAS_DIA`, `PAPER_SEARCH_MAX_LLAMADAS_DIA`).

2026-08-10 — [paper-search] El registro de acciones anota también los intentos bloqueados
(`bloqueada_alcance`, `bloqueada_limite`) y los fallos (`error_pubmed`, `error_resumen`),
no solo los éxitos, con `detalle` del motivo. Cada acción guarda los PMIDs devueltos (JSON
en orden) y `cache_id`, y los metadatos de cada paper se upsertan en `papers` — es la base
sobre la que Fase 3 construirá historial y favoritos sin volver a llamar a PubMed.

2026-08-10 — [paper-search] El aviso de `ANTHROPIC_API_KEY` ausente se emite UNA sola vez, al
principio de `cli.py`, y de esa comprobación salen `resumir=False` y `verificar_alcance=False`.
Motivo: antes cada componente que necesitaba la clave (filtro de alcance, resumidor,
verificador del resumen) fallaba por su cuenta y repetía el aviso, y el mensaje es largo —
salía tres veces en la misma ejecución. Los componentes siguen fallando solos si se usan como
librería; lo que se centraliza es el aviso al usuario, no la comprobación. Se mantiene el
código de salida 2 (sin resumen) y el cuerpo remite al aviso del inicio en vez de repetirlo.
La web no necesita el equivalente: allí el motivo sale una vez, en `error_resumen`.

2026-08-10 — [paper-search] Aviso de término escrito en español, catalán, euskera o gallego
(`idioma.py`): detección LOCAL por léxico + morfología, sin librería de detección de idioma y
sin llamada a Claude. Decidido midiendo, no a ojo: `langdetect` no tiene siquiera perfil de
euskera ni de gallego (55 idiomas, faltan `eu` y `gl`), y `py3langid` —que sí los tiene— falla
el 31% de los términos cortos de este dominio: clasifica «distròfia muscular» como occitano,
«epilèpsia mioclònica» como criollo haitiano, «enfermidades raras» como portugués y, lo peor,
«Smith-Lemli-Opitz» como euskera con 0.70 de confianza. Con uno o dos términos de búsqueda no
hay suficiente señal para un modelo estadístico. La heurística mide 0 falsos positivos y 1
falso negativo sobre 102 casos (incluidos 51 negativos: inglés médico, genes y apellidos).

2026-08-10 — [paper-search] Contra lo que se esperaba, el euskera es la lengua MÁS fiable de
las cuatro con este método (12/12), no la más difícil: al no ser romance, sus sufijos
aglutinantes (`-ak`, `-aren`, `-tasuna`, `-tzen`) no colisionan con el inglés ni con el latín
médico. Las difíciles son el catalán y el gallego, ahogados en cognados con el castellano, el
portugués y el propio inglés médico. Lo que hunde al euskera es la escasez de datos de
entrenamiento de los detectores estadísticos, no su tipología.

2026-08-10 — [paper-search] Tres guardas anti-falso-positivo en `idioma.py`, cada una puesta
tras ver el fallo que corrige: (1) los tokens en mayúsculas o con dígitos se apartan antes de
analizar (`SCN1A`, `22q11`); (2) una palabra que también es inglesa nunca cuenta como
evidencia (`muscular dystrophy` disparaba por «muscular»; `rare disease treatment`, por el
sufijo «-ment», que por eso tampoco está en la lista catalana); (3) las preposiciones romances
(`de`, `del`, `la`, `el`) refuerzan pero NUNCA disparan solas, porque el inglés médico está
lleno de locuciones que las llevan — `de novo mutations`, `del 22q11 syndrome`, `La Crosse
encephalitis`, `El Escorial criteria`, `torsades de pointes`. Esta tercera guarda, por sí
sola, quitó 6 de los 6 falsos positivos que quedaban. Las grafías `tz`/`tx` solo se miran en
tokens en minúscula: en apellidos (Opitz, Peutz, Creutzfeldt) no significan nada.

2026-08-10 — [paper-search] El aviso de idioma NO nombra la lengua concreta, aunque
`ResultadoIdioma.lenguas` la traiga para tests y depuración. Motivo: buena parte del
vocabulario médico se escribe igual en las tres lenguas romances («síndrome de Dravet»,
«distrofia muscular»), así que nombrar una sería acertar por azar, y decirle «parece estar en
español» a quien escribió en euskera es un error que se ve. El consejo —reescribir en inglés—
es idéntico en los cuatro casos. El sesgo general es hacia el falso negativo: solo se avisa
con evidencia positiva, porque un aviso falso sobre `SCN1A` o sobre `de novo mutations`
enseñaría a ignorar todos los avisos de la herramienta, incluido el de alcance.

2026-08-10 — [paper-search] `alcance.py` y `verificacion.py` atribuían a la clave ausente
cualquier `PaperSearchError` al crear el cliente perezoso: con la clave puesta pero sin el
paquete `anthropic` instalado, el aviso decía «falta la clave de la API» y mandaba a revisar
algo que estaba bien. Ahora solo `FaltaAPIKeyError` da ese motivo y el resto reporta el suyo.

2026-08-10 — [paper-search] Fase 3, favoritos: migración v2 con `favoritos(pmid PK → papers,
nota, creado_en, actualizado_en)`. El PMID es la clave primaria, sin id sustituto: un paper
está marcado o no lo está, así que la unicidad es natural y `marcar` sale idempotente. El
favorito huérfano lo impide la clave ajena (`PRAGMA foreign_keys = ON` ya estaba activo), no
un SELECT previo: comprobarlo antes sería una condición de carrera y dejaría la regla en dos
sitios. `nota` es NULL cuando no hay nota, nunca '', para que "sin nota" tenga una sola
representación. `actualizado_en` entra en la v2 y no en una v3 posterior porque la nota es
editable en cualquier momento y `creado_en` solo dice cuándo se marcó. Listar es un JOIN con
`papers`, que la Fase 2 ya rellena en cada búsqueda: marcar un favorito nunca consulta PubMed.

2026-08-10 — [paper-search] Desmarcar un favorito borra la fila entera, nota incluida, con
confirmación previa en CLI (`--si` para saltarla) y en web (la primera llamada a
`/favoritos/alternar` responde `requiere_confirmacion` con el texto de la nota, para poder
avisar de lo que se pierde antes de insistir). Alternativa descartada: conservar notas de
papers no favoritos, que crea notas fantasma reapareciendo al re-marcar. Sin terminal
interactiva, la confirmación de la CLI responde NO: no se pierde una nota por un pipe.

2026-08-10 — [paper-search] Fase 3, orden: `esearch` pasa de `sort=pub_date` a
`sort=relevance` y la posición devuelta se guarda en `Paper.orden_relevancia`. Motivo: PubMed
no da puntuación de relevancia, solo el orden, así que el orden por fecha SÍ se puede
recalcular en local sobre lo ya traído y el de relevancia NO. Pidiendo relevancia se tienen
los dos criterios sin llamadas extra y sin cambiar nunca el conjunto de PMIDs. **Cambio de
semántica asumido**: el conjunto pasa a ser "los N más relevantes de la ventana" en vez de
"los N más recientes"; la ventana `reldate` se sigue aplicando igual. Las alternativas eran
una segunda `esearch` al cambiar de orden (traería otro conjunto → fallo de caché → resumen
regenerado → coste Claude) o no ofrecer relevancia.

2026-08-10 — [paper-search] El orden es SOLO presentación. `buscar_y_resumir` mantiene
`papers` en el orden canónico de PubMed para los PMIDs, la caché, el registro y el prompt del
resumen, y devuelve una vista ordenada aparte. Así dos búsquedas iguales con distinta
ordenación producen el mismo resumen y el mismo acierto de caché. Que la caché no se invalide
no depende de esto solamente: `cache.hash_pmids` ya hasheaba `sorted(pmids)` desde la Fase 2,
así que es imposible por construcción. Desempate del orden por fecha: rango de relevancia —
estable, reproducible y no arbitrario, que importa porque muchos artículos solo traen el año.
En la web el reordenado lo hace el navegador sobre las filas ya pintadas (`data-fecha`,
`data-relevancia`), sin volver al servidor: la búsqueda llegó por POST y recargar la perdería.

2026-08-10 — [paper-search] Fase 3, buscador avanzado: el guardarraíl de alcance clasifica el
SUJETO MÉDICO (término + patógeno) y **nunca al autor**. Un apellido no es un concepto médico
y preguntarle a un clasificador si «Sánchez J» cae dentro de las enfermedades raras es una
pregunta sin respuesta que solo puede producir bloqueos falsos. Caso límite (solo autor): el
sujeto queda vacío, se resuelve en local con `veredicto_sin_sujeto()` → `NO_CONCLUYENTE`, sin
gastar llamada, y la búsqueda pasa con un aviso que dice que los resultados pueden incluir
trabajos ajenos al ámbito. Bloquear habría sido el primer bloqueo duro no basado en un
veredicto del modelo, contradiciendo el fail-open ya documentado, y habría impedido el flujo
legítimo de "ver la obra de este investigador".

2026-08-10 — [paper-search] Filtrar ≠ buscar, y la interfaz debe dejarlo claro. Los filtros de
pantalla (`filtrar_papers`, y su equivalente en JS en la web) solo esconden filas de las que
ya están: no consultan PubMed y no pueden traer nada nuevo. Los criterios de búsqueda
(`construir_consulta`) sí entran en la consulta. Por eso el contador de la web dice siempre
"N de M resultados mostrados" y nunca un número a secas: filtrar 15 resultados por autor y ver
2 NO significa que ese autor tenga 2 artículos sobre el tema. En una herramienta bibliográfica
médica esa confusión es grave.

2026-08-10 — [paper-search] En `construir_consulta`, el término va TAL CUAL a PubMed (quien
sabe escribir `SCN1A OR SCN2A` o `"Dravet syndrome"[MeSH]` puede seguir haciéndolo, como en
las Fases 1 y 2) y solo los criterios nuevos se envuelven: el autor con `[AU]`, el patógeno
como frase entre comillas, ambos tras quitarles `"[]()`. Sin autor ni patógeno la consulta es
exactamente el término, así que una búsqueda normal produce la consulta de siempre. La caché
de resúmenes y el registro de acciones usan la consulta completa, no el término suelto: dos
búsquedas del mismo término con distinto autor son búsquedas distintas.

2026-08-10 — [paper-search] `sqlite3.connect` lanza `sqlite3.OperationalError`, que NO es
`OSError`: `abrir_db` solo capturaba OSError, así que una ruta que sqlite no puede abrir salía
como traceback en vez de como `BaseDatosError`. Afectaba también a `buscar`, que debía
continuar sin caché y en cambio se caía. Ahora se capturan ambas.

2026-08-10 — [paper-search] Fase 4 simplificada: la exportación a NotebookLM se resuelve
copiando y pegando, no integrando una librería no oficial. Motivo: la integración exigiría
credenciales de una cuenta de Google real y depender de una API no soportada que puede
romperse o costar la cuenta; NotebookLM acepta texto pegado como fuente, así que el resultado
para el usuario es el mismo sin ese riesgo.

2026-08-10 — [paper-search] El texto de exportación lo arma el SERVIDOR (`exportar.py`) y
viaja ya hecho a la página dentro de un `<textarea>` oculto; el JavaScript solo lo copia. La
alternativa —reconstruirlo en el navegador leyendo el DOM— habría arrastrado el marcado de la
página, que es justo lo que no debe acabar pegado en NotebookLM, y además no sería testable
con pytest. Ese mismo `<textarea>` hace de alternativa visible cuando la Clipboard API no está
disponible (permiso denegado, navegador antiguo, `http` fuera de localhost): se enseña con el
texto ya seleccionado en vez de fallar en silencio.

2026-08-10 — [paper-search] El texto exportado incluye el término de búsqueda, los PMIDs con
enlace y el aviso de no diagnóstico, y esas tres cosas no son decoración: una fuente pegada en
NotebookLM pierde todo el contexto de dónde salió, la trazabilidad es la regla dura del
proyecto, y separado de esta interfaz nada recordaría que no es asesoramiento médico. En
cambio NO incluye metadatos de caché: dos exportaciones del mismo resumen deben coincidir
byte a byte venga de donde venga, y hay un test que lo fija.

2026-08-11 — [paper-search] Fase 5.1, i18n: fuente única en `paper-search/i18n/<idioma>.json`
(clave → texto plano) más `i18n/meta.json` con lo que no depende del idioma (descripción y
orden de placeholders). De ahí salen la web y los `_locales/<idioma>/messages.json` de
chrome.i18n: un solo diccionario, dos formatos. Se descarta Babel/Flask-Babel porque añadiría
una dependencia y un flujo `.po/.mo`, y convertir gettext a `messages.json` es más trabajo que
JSON a JSON; el módulo propio son ~60 líneas sin dependencias.

2026-08-11 — [paper-search] Las claves van en `snake_case` con prefijo de área
(`form_boton_buscar`) y NO con puntos (`form.boton_buscar`). Motivo medido, no estético:
chrome.i18n solo admite letras, números y `_` en los nombres de mensaje. Con puntos, el
generador tendría que transformar las claves y `a.b_c` y `a_b.c` colisionarían en `a_b_c` sin
avisar. Con snake_case la clave viaja idéntica a los dos formatos, con cero transformación. Un
test valida el patrón y la ausencia del prefijo reservado `@@`.

2026-08-11 — [paper-search] Los placeholders se escriben `$nombre$` y no `{nombre}`: es la
sintaxis nativa de chrome.i18n, así que el generador copia el `message` LITERAL de la fuente.
Con `{}` habría que convertir, y una llave literal dentro de un texto se corrompería en
silencio. El orden posicional ($1, $2…) sale de `meta.json`, declarado, no del orden de
aparición en el texto: así una traducción que reordene los placeholders no desplaza el mapeo.
Tests en ambos sentidos comprueban que lo declarado y lo usado coinciden, y que las dos
lenguas usan los mismos placeholders por clave.

2026-08-11 — [paper-search] Los avisos de alcance e idioma, que se construyen dentro del
paquete y no en las plantillas, TAMBIÉN pasan por i18n: `aviso(termino, idioma="es")`,
`mensaje_bloqueo(...)`, `Favoritos(conn, idioma=...)` y `buscar_y_resumir(..., idioma=...)`.
Con el idioma por defecto en el de referencia, la salida de la CLI no cambia ni un byte
(verificado por los 145 tests de alcance e idioma, que no se tocaron) y no hay diccionario
duplicado. La alternativa —dejar esos textos fijos en español— habría dado una web en inglés
con los avisos en español y los habría dejado fuera de la extensión de Chrome.

2026-08-11 — [paper-search] Selección de idioma en la web: `?idioma=xx` conmuta y una cookie
lo recuerda (precedencia parámetro > cookie > `es`). Se descarta la sesión de Flask porque
exigiría un SECRET_KEY —un secreto más que configurar y guardar en una herramienta cuyo
objetivo es funcionar en local sin configuración— y se descarta el parámetro solo porque
`/buscar` es POST y `/favoritos/*` redirige: habría que arrastrar el idioma en un campo oculto
de cada formulario y en cada enlace, y basta olvidar uno para volver al español. La cookie no
firma nada y no hace falta: el valor se normaliza al leerlo y solo puede acabar siendo uno de
los idiomas conocidos.

2026-08-11 — [paper-search] Fallback de traducción: idioma pedido → idioma de referencia (`es`)
→ la propia clave. Nunca lanza. Devolver la clave (`form_boton_buscar` en pantalla) es
deliberado: señala exactamente qué falta y dónde, mientras que un texto vacío pasaría
desapercibido. Lo mismo con un placeholder sin valor: se deja visible (`$termino$`) en vez de
sustituirlo por vacío. Hay tests que piden la página real con una fuente incompleta y con la
fuente entera vacía, y comprueban que en ambos casos se sirve un 200.

2026-08-11 — [paper-search] El JavaScript de la web no lleva ni un literal de texto: recibe
las cadenas que necesita en un `PS_TEXTOS` serializado por el servidor, y las sustituye con la
misma mecánica `$nombre$` que el servidor y que chrome.i18n. Así la fuente sigue siendo una
sola incluso para los textos que solo existen en cliente (botón «¡Copiado!», contador de
filtros, confirmación al borrar una nota).

2026-08-11 — [paper-search] La CLI queda FUERA de la fase de i18n. Sus textos de `argparse`
son otra superficie, no sirven a la extensión de Chrome, y con `idioma="es"` por defecto su
salida es idéntica a la de antes. Fuera de alcance también, y anotado como deuda: los mensajes
técnicos de fallo de `summarizer.py`, `verificacion.py` y `pubmed_client.py`, que siguen en
español fijo. Se cubrió lo que ve el usuario en la web (interfaz, errores de formulario,
avisos y errores de favoritos).

2026-08-11 — [paper-search] `herramientas/generar_locales.py` genera los `_locales/`, y tiene
un modo `--comprobar` que no escribe y sale con código 1 si lo generado no coincide con la
fuente. Hay además un test (`test_los_locales_del_repo_estan_al_dia`) que falla si alguien
edita `i18n/*.json` y no regenera: sin él, la extensión de la Fase 5.3 se llevaría textos
viejos sin que nadie se enterara.

2026-08-11 — [paper-search] Fase 5.2, PWA. El hallazgo que condiciona todo lo demás:
paper-search se sirve desde 127.0.0.1, así que "sin conexión" son DOS situaciones distintas y
solo una necesita service worker. (a) Sin internet con el servidor encendido: la página carga
entera y los favoritos funcionan completos —el SQLite es local—; solo fallan PubMed y Claude.
Esto ya funcionaba antes de la PWA. (b) Servidor local apagado: no responde nada, y ahí el
service worker solo puede ofrecer HTML guardado de solo lectura. Lo que la PWA aporta de
verdad es la instalabilidad (ventana propia, icono, sin cromo del navegador) y una degradación
honesta en el caso (b), no "búsquedas offline", que no pueden existir.

2026-08-11 — [paper-search] `navigator.onLine` NO se usa como única señal: responde a si hay
internet, no a si Flask está vivo, y se equivocaría en los dos sentidos (sin wifi pero con el
servidor encendido diría "sin conexión" cuando los favoritos funcionan; con wifi y el servidor
apagado diría "conectado" cuando no funciona nada). Se usan dos señales independientes:
`navigator.onLine` para saber si hay internet y un ping a `/api/estado` con timeout de 2 s
para saber si el servidor local responde. Son dos problemas distintos y llevan dos mensajes
distintos.

2026-08-11 — [paper-search] Estrategias de caché: estáticos (CSS, JS, iconos, manifest) a
cache-first con refresco por detrás; navegaciones (`/`, `/favoritos`, `/offline`) a
network-first con la última copia como reserva; y TODO lo que no sea GET se deja pasar sin
tocar. Esa última regla es la importante: un POST servido desde caché sería inventar un
resultado —una búsqueda que no se hizo, una nota que no se guardó— y el service worker no
intercepta esas peticiones en absoluto. Descartado también Background Sync para las notas:
encolar "guardar" para reintentarlo luego y que el usuario cierre la ventana creyendo que se
guardó es peor que fallar claro.

2026-08-11 — [paper-search] Nunca se sirve un resultado de búsqueda desde la caché del service
worker. Un resumen viejo presentado como nuevo es exactamente lo que el proyecto lleva cuatro
fases evitando, y el hecho de que el fallo sea de red no lo hace más aceptable.

2026-08-11 — [paper-search] Con el servidor apagado, `/favoritos` sí sirve la última copia
guardada, pero marcada: un banner dice de qué momento es y que puede estar desactualizada, y
se deshabilitan todos los campos y botones que escriben. Sin eso, una nota borrada hace un
rato parecería vigente y editable, y cualquier intento de guardar fallaría en silencio. La
marca de tiempo viaja en un `<meta name="ps-generado">` de cada página, que es la única pista
de antigüedad que queda cuando la sirve el service worker.

2026-08-11 — [paper-search] La política de caché vive en `src/paper_search/pwa.py`, en Python,
y viaja al `sw.js` serializada como JSON. Motivo: la suite no tiene navegador ni Node, así que
el JavaScript del service worker no se puede ejecutar en los tests; sacando la parte que
DECIDE a Python se prueba de verdad, y en el `sw.js` queda solo la mecánica de `caches.match`
/ `fetch`. Queda sin cubrir por la suite —y dicho en el propio archivo de tests— que el
navegador registre el worker y que `caches` se comporte como se espera: eso hay que mirarlo a
mano en las herramientas de desarrollo.

2026-08-11 — [paper-search] El service worker se sirve en `/sw.js` y no como archivo estático:
un service worker solo controla su carpeta hacia abajo, así que desde `/static/sw.js` su
alcance sería `/static/` y no vería ni la portada ni los favoritos. Se acompaña de la cabecera
`Service-Worker-Allowed: /` y de `Cache-Control: no-cache`, sin la cual el navegador podría
quedarse hasta 24 h con un worker viejo.

2026-08-11 — [paper-search] `conexion.js` está en la lista de precache, y hay un test que
comprueba que TODO estático referenciado por las páginas lo está. No es cosmética: ese archivo
es el que enciende el aviso de «copia guardada» y deshabilita los formularios, así que sin
precachearlo la página servida desde caché se vería normal y editable — justo lo contrario de
lo que se pretende.

2026-08-11 — [paper-search] El manifest se sirve desde una ruta de Flask y no como archivo
estático, para que el nombre y la descripción que se ven al instalar pasen por el sistema de
traducción del punto 5.1. La página `/offline` es la excepción a ese sistema: como es la única
que tiene que funcionar con el servidor apagado, lleva dentro los textos de TODOS los idiomas
y elige por la cookie. Siguen saliendo de `i18n/<idioma>.json`; lo que cambia es que se
serializan todos en vez de resolverse en el servidor.

2026-08-11 — [paper-search] Los iconos de `static/iconos/` son PLACEHOLDER: una lupa generada
con Pillow sobre los colores del CSS. Pillow se usó una sola vez para generarlos y los PNG
están commiteados, así que NO entra en requirements.txt. Hay que sustituirlos por un icono de
verdad antes de que esto se enseñe a nadie.
  → RESUELTO el 2026-08-17: sustituidos por el icono real (ver más abajo).

2026-08-17 — [paper-search] Icono definitivo, importado del proyecto de Claude Design
`Icon.dc.html`: una lupa de trazo grueso en oro con una cruz médica maciza dentro de la lente,
sobre near-black. Sustituye al placeholder de la Fase 5.2. Usa los tokens de marca del sistema
(`--color-text #201f1d`, `--color-accent #b68235`, `--color-bg #f3f2f2`) y no tonos sueltos de
la rampa como hacía el placeholder (#2d2b2b, #facb8d), así que ahora el icono y la interfaz
son el mismo sistema. Del diseño original: la cruz se eligió sobre la vara de Asclepio porque
sus curvas no sobreviven a 16 px.

2026-08-17 — [paper-search] El SVG es la fuente del icono y los PNG son derivados:
`herramientas/generar_iconos.py` **parsea** el SVG y lo rasteriza, en vez de reimplementar la
geometría a mano, para que no puedan quedar desalineados por una copia que se olvidó de
actualizar. El renderizador solo entiende los primitivos que usa este icono (rect con esquinas
opcionales, círculo con trazo, línea con trazo y cabeza redonda) y **falla ante cualquier
otro** en vez de dibujar de menos en silencio — un icono al que le falte un trazo llegaría
hasta la barra de tareas sin que nadie lo notase. Hay un `--comprobar` y un test que fallan si
alguien retoca el SVG y no regenera. Pillow sigue usándose solo para generar, no en tiempo de
ejecución, así que no entra en requirements.txt.

2026-08-17 — [paper-search] La variante `maskable` se genera a sangre (sin las esquinas
redondeadas del SVG) porque el sistema operativo le aplica su propia máscara: dejar las
esquinas redondas haría que se recortara dos veces y quedara mordida. Que el dibujo quepa
dentro de la máscara circular no se da por supuesto: un test rasteriza el icono y mide el
punto dibujado más lejano del centro (184 de un radio seguro de 205, ~10 % de holgura), que
confirma empíricamente lo que declaraba el diseño.

2026-08-17 — [paper-search] `theme_color` y `background_color` del manifest pasan de #2d2b2b a
#201f1d, el mismo near-black del fondo del icono. La pantalla de arranque de la app instalada
pinta `background_color` detrás del icono: si no coinciden, al abrir se ve un escalón de
color. Hay un test que lee el fill del rectángulo de fondo del SVG y lo compara con el
manifest, para que no vuelvan a separarse.

2026-08-17 — [paper-search] El favicon pasa a ser el SVG (`rel="icon" type="image/svg+xml"`)
con el PNG de 192 como reserva, en vez de servir un PNG de 192 px para un hueco de 16. El SVG
entra en el precache del service worker porque ahora lo referencian todas las páginas.

2026-08-18 — [paper-search] `GET /` acepta ahora `?termino=` para llegar con el formulario
relleno, y `?buscar=1` para que la página lo envíe sola. Lo va a usar la extensión de Chrome.
La búsqueda de verdad sigue siendo el POST a `/buscar`, y eso es deliberado: un GET que
buscara gastaría cuota diaria y llamadas a Claude reales, y quedaría al alcance de una
precarga del navegador, de un marcador sincronizado o de una revisita del historial. La URL
que sí se abre solo pinta un formulario: es inofensiva por muchas veces que se cargue.

2026-08-18 — [repo] Los `_locales/` pasan a generarse en `extension/_locales/`, que es donde
Chrome exige encontrarlos —dentro del paquete de la extensión—, y se borra la copia de
`paper-search/_locales/`, que no consumía nadie. Una sola copia a propósito: dos habrían
divergido, que es justo lo que el generador existe para evitar. La fuente no se mueve; lo que
cambia es el destino por defecto, y `--salida` sigue permitiendo escribir en otro sitio.

2026-08-18 — [repo] `generar_iconos.py` emite también los tamaños 16/48/128 que pide una
extensión de Chrome, desde el mismo SVG que la web. Las salidas pasan a darse relativas a la
raíz del repo y no a `paper-search/`, porque el icono es un activo de MARCA compartido por los
dos componentes y la extensión necesita sus PNG dentro de su propia carpeta. El `--comprobar`
cubre ahora los seis.

2026-08-18 — [extension] Permisos mínimos: `contextMenus` y `host_permissions` acotado a
`http://127.0.0.1:5000/*`. NO se piden content scripts, `activeTab`, `scripting`, `tabs` ni
`<all_urls>`. La clave está en `contexts: ["selection"]`, que hace que Chrome entregue el texto
seleccionado en `info.selectionText` sin que la extensión toque la página: **no puede leer lo
que el usuario está leyendo**, y en una herramienta médica eso no es un detalle.
`chrome.tabs.create` no requiere el permiso `tabs` (ese solo abre el acceso a `url`/`title` de
pestañas ajenas). El `host_permissions` existe solo para preguntar por el estado del servidor.
Hay tests que fallan si alguien añade un permiso o un content script.

2026-08-18 — [extension] El nombre y la descripción del manifest van como `__MSG_ext_nombre__`
y `__MSG_ext_descripcion__`, resueltos por `chrome.i18n` contra los `_locales` generados: si
fueran literales, quedarían fijos en un idioma en la propia ficha de la extensión. Las claves
nuevas llevan prefijo `ext_` y se añaden a la fuente única, nunca al `messages.json` generado.

2026-08-18 — [extension] Los tests de la extensión comprueban su CONTRATO ESTÁTICO, no su
ejecución: sin navegador no se puede cargar el service worker ni abrir el popup. Se cubre lo
que de verdad rompe al instalar —manifest que Chrome rechaza, icono declarado que no existe o
que no mide lo que dice, permiso de más, `default_locale` sin su carpeta— y queda dicho en el
propio archivo de tests que el resto hay que probarlo a mano en `chrome://extensions`.

2026-08-18 — [extension] La extensión ABRE UNA PESTAÑA con el término puesto, en vez de llamar
a una API y pintar los resultados en el popup. Motivo decisivo y práctico: un popup de MV3 se
cierra en cuanto pierde el foco, y una búsqueda con resumen tarda 10-30 s (alcance + resumen +
verificación), así que moriría a media búsqueda de forma rutinaria. Motivo de fondo:
renderizar resultados allí obligaría a repetir el aviso de no diagnóstico y la trazabilidad a
PMID en un segundo sitio, y tener dos implementaciones de esas reglas es donde se pudren. El
popup existe, pero como lanzador y línea de estado, nunca como visor de resultados.

2026-08-18 — [extension] La URL que abre es `/?termino=X&buscar=1`, no `GET /buscar?termino=X`:
la página se rellena y envía sola, así que la búsqueda sigue siendo el POST del servidor (ver
la entrada del lado de paper-search). El guardarraíl de alcance y el aviso de idioma los sigue
aplicando el servidor; la extensión no los reimplementa ni los esquiva, y hay un test que lo
comprueba buscando esas señales en su código.

2026-08-18 — [extension] Servidor caído: se detecta preguntando a `/api/estado` con timeout de
1,5 s, la misma señal que usa la PWA y por el mismo motivo — `navigator.onLine` responde a si
hay internet, no a si Flask vive, y se equivoca en los dos sentidos. El mensaje reutiliza
`off_servidor_caido`, que ya existía y ya dice lo útil (arráncalo con run.bat) en vez de un
«sin conexión» genérico. Desde el menú contextual, además de la insignia `!`, la pestaña se
abre igualmente: la página `/offline` de la PWA explica el problema mejor de lo que cabe en
una insignia, y duplicar ese texto sería mantener dos.

2026-08-18 — [extension] La extensión elige idioma por el del navegador (`chrome.i18n`) y la
web por su cookie, así que pueden discrepar. No se manda `?idioma=` desde la extensión a
propósito: una preferencia explícita —la que el usuario eligió en la web— debe ganar a una
implícita —la del navegador—. Queda documentado en el README de la extensión. El `%s` de
`ext_menu_buscar` es sintaxis de `chrome.contextMenus`, que lo sustituye por lo seleccionado,
y por eso no va como `$x$` de i18n.

2026-08-18 — [extension] Los tests que inspeccionan el JavaScript le quitan antes los
comentarios, con un lector que respeta las cadenas. Hace falta porque varios comentarios
explican precisamente lo que NO se hace —«navigator.onLine no vale aquí», «no se apunta a
/buscar»— y confundirlos con el código daba falsos positivos. Partir por `//` a lo bruto
tampoco vale: `http://127.0.0.1` lo contiene.

2026-08-18 — [paper-search] Fase 5.4, acceso desde el móvil: el servidor puede escuchar en
0.0.0.0, pero **nunca por defecto**. Se activa con `--red` (o `PAPER_SEARCH_RED=1`), y se
prefiere el flag a una variable en el `.env` justamente porque una variable en un archivo se
queda puesta y se olvida: el flag vale para un arranque concreto. `run-red.bat` existe para
quien no usa terminal, y pregunta antes de continuar — doble clic no debe bastar para abrir
el servidor a toda la wifi.

2026-08-18 — [paper-search] La advertencia en consola enumera QUÉ queda expuesto y no un «ten
cuidado» genérico, que nadie lee: sin contraseña, cualquiera en esa wifi puede leer los
favoritos y sus notas personales, ver todo el historial de búsquedas, y lanzar búsquedas que
gastan la clave de la API y la cuota diaria — o sea, dinero. Hay tests que fallan si esas
cuatro cosas dejan de mencionarse.

2026-08-18 — [paper-search] La IP local se detecta abriendo un socket UDP «hacia» 192.0.2.1
(red de documentación, RFC 5737) y leyendo la dirección de origen que asigna el sistema: eso
da la interfaz de la ruta por defecto, que es la que ve el móvil. Con UDP, `connect` no envía
ningún paquete. Se descarta `gethostbyname(gethostname())` porque devuelve 127.0.0.1 en muchas
configuraciones de Linux y la interfaz equivocada en portátiles con VPN o adaptadores
virtuales — y una IP equivocada en pantalla es peor que ninguna, porque manda a probar una
dirección que no puede funcionar. Si solo hay loopback o falla el socket, se lanza `RedError`
con instrucciones (`ipconfig` / `ip addr`) y el aviso de seguridad sale igual: el servidor ya
está escuchando en la red, así que no saber la IP no puede hacer que desaparezca la
advertencia.
