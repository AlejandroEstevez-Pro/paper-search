# Roadmap

## Fase 1 — paper-search (actual)
Buscador/resumidor de papers de PubMed por gen o síndrome. Ver
`paper-search/docs/brief.md` para la spec completa.

## Fase 2 — symptom-classifier (futuro, no empezado)
Dado un conjunto de síntomas, sugerir síndromes candidatos usando una base
de datos tipo Orphanet. Ideas para cuando llegue el momento (no vinculante,
ajustar según lo aprendido en fase 1):

- Reutilizar el cliente de PubMed de `paper-search` para enriquecer cada
  síndrome candidato con papers recientes relevantes.
- Separar claramente "coincidencia de síntomas" (lógica determinista contra
  la base de datos) de "explicación en lenguaje natural" (lo que sí puede
  usar un LLM) — para que el resultado principal sea trazable y no dependa
  de que el LLM "recuerde bien" los datos.
- Necesitará su propia fuente de datos estructurada (export de Orphanet u
  otra base pública) — investigar formato y licencia de uso antes de empezar.

## Por qué están separados en dos carpetas
Cada componente es útil por sí solo y se puede probar/usar de forma
independiente. Se unen bajo el mismo repo porque comparten dominio (IA +
enfermedades raras) y probablemente código (cliente de PubMed), pero no
comparten runtime ni deployment necesariamente.
