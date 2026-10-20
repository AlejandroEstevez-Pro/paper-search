# rare-disease-tools

Repo paraguas para herramientas de IA aplicadas a enfermedades raras. Empieza
con `paper-search` (buscador/resumidor de papers de PubMed). Más adelante se
añadirá un clasificador de síntomas → síndromes candidatos que reutilizará
piezas de aquí (ver `docs/roadmap.md`).

## Componentes

| Nombre | Qué hace | Estado |
|---|---|---|
| `paper-search/` | Dado un gen/síndrome, busca en PubMed y resume hallazgos recientes en lenguaje llano | Completo: sus cinco fases, más el icono, los PMID enlazables y el resumen por idioma (ver «Estado del proyecto») |
| `extension/` | Extensión de Chrome: busca el texto seleccionado en tu paper-search local | Completa (fase 5.3 de paper-search). Se carga en modo desarrollador; no está en la Chrome Web Store |
| `symptom-classifier/` | Dado un conjunto de síntomas, sugiere síndromes candidatos (tipo Orphanet) | No empezado. Es la fase 2 del roadmap del REPO (`docs/roadmap.md`), que no es la fase 2 de paper-search |

## Cómo trabajar en este repo

- Cada componente vive en su propia carpeta con su propio `README.md`. Los
  tests de paper-search están en `paper-search/tests/`. La extensión no tiene
  suite propia: su contrato estático (manifest, permisos, iconos, `_locales/`
  al día) se comprueba en `paper-search/tests/test_extension.py`.
- La spec de la primera versión de paper-search está en
  `paper-search/docs/brief.md`: **léela entera antes de tocar el núcleo**.
  Tiene el contrato de entrada/salida, la API a usar y los límites de esa
  versión. Lo construido después se especificó sesión a sesión y está razonado
  en `docs/decisions.md`, que también recoge dónde se apartó la implementación
  del brief.
- Sigue el mismo patrón que otros proyectos del autor: la lógica vive en el
  paquete `paper-search/src/paper_search/`, y `cli.py` y `app.py` solo hacen
  de interfaz. Tests con pytest desde el primer commit, sin dependencias sin
  justificar en `requirements.txt`.
- No hace falta pedir confirmación para decisiones ya cerradas en el brief —
  actúa con autonomía dentro de lo que ahí se especifica. Si algo no está
  cubierto por el brief y es una decisión de diseño real (no un detalle de
  implementación), anótalo en `docs/decisions.md` con tu elección y el motivo,
  en vez de parar a preguntar.

## Reglas importantes

- **Nunca inventes resultados de PubMed.** Si la API falla o no hay resultados,
  decirlo explícitamente — nunca rellenar con papers inventados o
  aproximados de memoria. Esto es contenido médico, la precisión importa más
  que la completitud.
- **Todo resumen debe indicar la fuente** (PMID + enlace) para que se pueda
  verificar. Nunca resumir sin trazabilidad al paper original.
- **No es una herramienta diagnóstica.** Cualquier texto de cara al usuario
  debe dejar claro que esto es una ayuda de búsqueda bibliográfica, no
  asesoramiento médico.
- **API de PubMed (NCBI E-utilities)**: 3 peticiones/segundo sin API key,
  10/segundo con ella. Implementa rate limiting desde el principio, no como
  añadido posterior — con 3 req/s de límite es fácil pasarse sin quererlo en
  un bucle. Detalles completos en `docs/api-notes.md`. NCBI pide además un
  email de contacto real: `NCBI_EMAIL` es obligatorio, y en el código no se
  pone nunca uno por defecto (hay un test que lo impide).

## Estado del proyecto

paper-search tiene completas sus cinco fases:

1. CLI y web local, con los dos guardarraíles (filtro de alcance y
   verificación del resumen).
2. Base de datos SQLite local: caché de resúmenes, límites diarios y registro
   de acciones.
3. Favoritos con notas, orden y búsqueda avanzada (autor, patógeno).
4. Exportación del resultado para NotebookLM.
5. Interfaz en español e inglés (5.1), PWA instalable (5.2), extensión de
   Chrome (5.3) y modo red local para usarlo desde el móvil (5.4).

Después llegaron el icono definitivo, las citas `[PMID: ...]` enlazables y el
resumen generado en el idioma elegido. El repo tiene licencia MIT y está
preparado para publicarse, con el README de paper-search en inglés y el manual
completo en `paper-search/README.es.md`.

Ver `docs/decisions.md` para el registro de decisiones tomadas sesión a sesión.
