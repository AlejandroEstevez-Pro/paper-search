# rare-disease-tools

Repo paraguas para herramientas de IA aplicadas a enfermedades raras. Empieza
con `paper-search` (buscador/resumidor de papers de PubMed). Más adelante se
añadirá un clasificador de síntomas → síndromes candidatos que reutilizará
piezas de aquí (ver `docs/roadmap.md`).

## Componentes

| Nombre | Qué hace | Estado |
|---|---|---|
| `paper-search/` | Dado un gen/síndrome, busca en PubMed y resume hallazgos recientes en lenguaje llano | Fases 1-3 completadas (CLI + web local + favoritos, orden y buscador avanzado) |
| `extension/` | Extensión de Chrome: busca el texto seleccionado en tu paper-search local | Fase 5.3 completada |
| `symptom-classifier/` | Dado un conjunto de síntomas, sugiere síndromes candidatos (tipo Orphanet) | No empezado — fase 2 |

## Cómo trabajar en este repo

- Cada componente vive en su propia carpeta con su propio `README.md` y tests.
- La spec detallada de la tarea actual está en `paper-search/docs/brief.md` —
  **léela entera antes de escribir código**, tiene el contrato de entrada/salida,
  la API a usar, y los límites de la primera versión.
- Sigue el mismo patrón que otros proyectos del autor: lógica separada de la
  CLI (`core.py` / `cli.py`), tests con pytest desde el primer commit, sin
  dependencias sin justificar en `requirements.txt`.
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
  un bucle. Detalles completos en `docs/api-notes.md`.

## Estado del proyecto

Ver `docs/decisions.md` para el registro de decisiones tomadas sesión a sesión.
