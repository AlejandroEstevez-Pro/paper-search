# Notas de la API — NCBI E-utilities (PubMed)

Base: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
No hace falta API key para empezar, pero se recomienda tenerla (sube el
límite de 3 a 10 peticiones/segundo). Se consigue gratis en
https://www.ncbi.nlm.nih.gov/account/ y se pasa como `api_key=<clave>`.

## Flujo típico (2 pasos)

1. **`esearch.fcgi`** — busca por texto, devuelve una lista de PMIDs (IDs de
   artículo).
   ```
   GET esearch.fcgi?db=pubmed&term=<consulta>&retmax=20&retmode=json
       &sort=pub+date&tool=<nombre_app>&email=<tu_email>
   ```
2. **`efetch.fcgi`** — dado un lote de PMIDs, devuelve los registros completos
   (título, autores, revista, fecha, abstract).
   ```
   GET efetch.fcgi?db=pubmed&id=<pmid1,pmid2,...>&rettype=abstract
       &retmode=xml&tool=<nombre_app>&email=<tu_email>
   ```
   `retmode=xml` es más fiable para sacar el abstract completo que `text`.

## Parámetros que siempre hay que mandar

- `tool` — nombre identificativo de tu aplicación (cualquier string corto)
- `email` — un email de contacto real (NCBI lo pide para poder avisar si algo
  abusa de la API sin querer)
- `api_key` — opcional pero recomendado, ver arriba

## Límites y buenas prácticas

- Sin API key: **3 peticiones/segundo**. Con API key: **10/segundo**.
- Si se van a pedir muchos PMIDs, mejor un solo `efetch` con todos los IDs
  separados por coma que una petición por artículo.
- Añadir manejo de errores/reintentos con backoff — la API puede devolver
  errores transitorios bajo carga.
- Filtrar por fecha reciente cuando el objetivo es "hallazgos recientes":
  parámetro `datetype=pdat` + `reldate=<días>` en `esearch`, o
  `mindate`/`maxdate` con `datetype=pdat`.

## Referencia completa
https://www.ncbi.nlm.nih.gov/books/NBK25501/ (guía oficial de E-utilities)
