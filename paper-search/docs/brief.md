# Brief — paper-search

Spec completa de la primera versión. El objetivo es que se pueda construir
de principio a fin en una sola sesión larga sin necesidad de preguntar nada
que ya esté decidido aquí. Si algo no está cubierto y es una decisión de
diseño real, tomar la opción más simple y anotarla en `docs/decisions.md`
del repo raíz.

## Qué hace la herramienta

Dado un término de búsqueda (gen, síndrome, o término libre), la herramienta:
1. Busca en PubMed artículos relevantes, priorizando los más recientes.
2. Descarga título, autores, revista, fecha y abstract de cada resultado.
3. Genera un resumen en lenguaje llano (no jerga médica innecesaria) de los
   hallazgos, agrupando por tema si hay varios artículos sobre líneas
   distintas.
4. Presenta el resultado con trazabilidad: cada afirmación del resumen debe
   poder rastrearse a un PMID concreto.

## Entrada / Salida

**CLI** (como interfaz principal de esta primera versión):
```bash
python cli.py buscar "SCN1A" --max 15 --dias 365
python cli.py buscar "síndrome de Dravet" --max 10
```

- `término` (posicional, obligatorio) — gen o síndrome a buscar
- `--max` (opcional, por defecto 15) — número máximo de papers a traer
- `--dias` (opcional, por defecto 730) — ventana de "recientes", en días
- `--formato` (opcional: `texto` | `json`, por defecto `texto`) — cómo se
  imprime el resultado

**Salida en modo texto**: resumen en lenguaje llano seguido de una lista de
referencias (título, autores, revista, año, PMID + enlace a PubMed).

**Salida en modo json**: estructura con `query`, `resumen`, y `papers` (lista
de objetos con `pmid`, `titulo`, `autores`, `revista`, `fecha`, `abstract`,
`url`). Este modo es el que usará más adelante el clasificador de síntomas
u otras herramientas, así que debe ser estable y bien tipado.

## Arquitectura (mismo patrón que otros proyectos del autor)

```
paper-search/
├── README.md
├── requirements.txt
├── cli.py                        # solo argparse + printing, sin lógica
├── src/paper_search/
│   ├── __init__.py               # expone la API pública del paquete
│   ├── pubmed_client.py          # esearch/efetch, rate limiting, parseo XML
│   ├── summarizer.py             # genera el resumen en lenguaje llano
│   └── models.py                 # dataclasses: Paper, ResultadoBusqueda
└── tests/
    ├── test_pubmed_client.py     # con mocks — nunca golpear la API real en tests
    └── test_summarizer.py
```

- `pubmed_client.py` implementa el rate limiting descrito en
  `docs/api-notes.md` (raíz del repo) desde el principio.
- El resumen (`summarizer.py`) puede usar la API de Anthropic (paquete
  `anthropic`) para generar el texto en lenguaje llano a partir de los
  abstracts — si se hace así, la clave se lee de la variable de entorno
  `ANTHROPIC_API_KEY`, nunca hardcodeada, y el código debe fallar con un
  mensaje claro si la variable no está puesta.
- Los tests de `pubmed_client.py` usan respuestas de la API **mockeadas/
  grabadas**, no llamadas reales — para que la suite sea rápida y no
  dependa de que PubMed esté disponible.

## Fuera de alcance para esta versión (no implementar)

- Interfaz web o gráfica — solo CLI.
- Caché persistente de búsquedas anteriores.
- Traducción automática de abstracts (asumir que están en inglés, y el
  resumen en español está bien aunque el abstract esté en inglés).
- Cualquier intento de dar una opinión médica o recomendación de
  tratamiento — el resumen se limita a describir qué dicen los papers.

## Definición de "terminado" para esta v1

- [ ] `pip install -r requirements.txt` + `python cli.py buscar "..."` funciona
      de principio a fin con una búsqueda real.
- [ ] Tests pasan (`pytest tests/ -v`), incluyendo al menos un caso de "la
      API no devuelve resultados" y uno de "la API falla".
- [ ] README explica instalación, uso, y deja claro que no es una
      herramienta de diagnóstico.
- [ ] Ningún resumen se presenta sin sus PMIDs de respaldo.
## Añadido — modo de lanzamiento con doble clic (interfaz web local)

Además de la CLI, la herramienta necesita un modo de arranque con doble
clic para uso diario sin terminal. Esto se construye AL FINAL, después de
que la CLI funcione y tenga tests en verde — no antes.

### Por qué web local y no HTML puro
La herramienta llama a APIs externas (PubMed, y la API de Claude si se usa
para el resumen). Un HTML autocontenido sin backend expondría cualquier
clave de API directamente en el navegador — inaceptable. La solución es un
servidor local: la clave de API vive solo en el proceso Python del
servidor, nunca llega al navegador.

### Qué construir

1. **`app.py`** en la raíz de `paper-search/` — servidor Flask mínimo:
   - `pip install flask` (añadir a `requirements.txt`)
   - Ruta `GET /` → sirve un formulario HTML simple (campo de término,
     max resultados, días) — puede ser una plantilla en `templates/index.html`
     o HTML inline, lo que sea más simple.
   - Ruta `POST /buscar` → llama a la MISMA función pública que ya usa
     `cli.py` para hacer la búsqueda (reutilizar el código existente de
     `src/paper_search/`, no duplicar lógica) y devuelve el resultado
     renderizado en la página (resumen + lista de referencias con enlace
     a PubMed).
   - Puerto fijo `5000`, host `127.0.0.1` (nunca `0.0.0.0` — esto es solo
     para uso local de una persona, no un servidor expuesto a la red).
   - Mostrar un estado de "buscando..." mientras tarda, y errores de la
     API de forma clara si algo falla (nunca fallar en silencio).

2. **`run.bat`** en la raíz — ya está escrito, no hay que tocarlo salvo
   que cambien nombres de archivo. Actualiza/instala dependencias solo, y
   abre el navegador en `http://127.0.0.1:5000` automáticamente.

3. Añadir `flask` a `requirements.txt`.

### Definición de "hecho" para este añadido
- [ ] Doble clic en `run.bat` abre el navegador solo, sin pasos manuales.
- [ ] Buscar un término desde el formulario web da el mismo resultado que
      `python cli.py buscar "<término>"` desde terminal.
- [ ] Cerrar la ventana de consola que abre `run.bat` detiene el servidor
      limpiamente (comportamiento por defecto de Flask con Ctrl+C / cierre
      de ventana es suficiente, no hace falta nada especial).
