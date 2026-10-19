# paper-search

**English** · [Español](README.es.md)

Search PubMed for a rare-disease gene or syndrome and get a plain-language
summary of the recent literature, where every statement is cited to the
PubMed article (PMID) it comes from.

## Before you use it

> **paper-search is not a diagnostic tool and does not replace medical
> judgement.** It helps you find and read research papers. It cannot tell you
> whether someone has a condition, which treatment to follow or what to
> expect. Do not make health decisions based on what it says; take your
> questions to a qualified clinician.

**The summaries are written by a language model.** They are checked
automatically before they are shown, but the checks are not infallible. A
summary can pass every check and still misstate what a paper says.

This is what the checks actually cover:

**Guaranteed by code (exact, every time)**
- Every PMID cited in the summary belongs to an article retrieved in this
  search. The summary cannot cite a paper that does not exist or was not
  retrieved.
- The summary cites at least one PMID.
- No summary is shown unless its verification completed and approved it. If
  the verifier is unavailable, you get the references and no summary.

**Checked by a second model (usually right, but can miss things)**
- Every clinical statement carries a citation.
- The text gives no medical advice addressed to the reader.
- The search term is within the scope of rare diseases. If this check cannot
  run, the search goes ahead anyway, with a warning.

**Not checked at all**
- **Whether the cited paper really supports the statement.** The verifier
  sees the summary and the list of valid PMIDs, not the abstracts. A real PMID
  can be attached to a claim that paper does not make. A correct claim can be
  overstated, get a number wrong or lose its caveats.
- **Anything outside the abstract.** The model reads only each paper's title,
  metadata and abstract, never the full text. Methods, limitations and results
  that are not in the abstract are invisible to it, and a paper with no
  abstract contributes almost nothing.
- **Quality of the evidence.** Study design, sample size, retractions,
  conflicts of interest and replication are not assessed. A single case report
  and a randomised trial carry the same weight.
- **Completeness.** By default you get up to 15 papers from the last two
  years, ranked by PubMed relevance. This is not a systematic review, and
  important work may be missing.

Treat each summary as a guide to what to read, and open the cited paper before
relying on any statement.

## What problem it solves, and for whom

When someone in a family is diagnosed with a rare disease, the people around
them (parents, patients, carers, researchers from other fields) soon want to
know what is actually being published about it. The answer is on PubMed, but
it comes as dozens of technical abstracts in English, and few people have the
time or the background to read fifteen of them.

paper-search takes a gene (`SCN1A`) or a syndrome (`Dravet syndrome`), fetches
the most relevant recent articles from PubMed, and writes a plain-language
summary grouped by topic: genetics, treatment, animal models, natural history.
Every sentence ends with the PMID of the paper behind it, so you can go
straight from a statement to its source.

It runs on your own computer, with your own Anthropic API key. You can use it
through a local web interface (English or Spanish), a command-line tool, or a
Chrome extension that searches whatever text you select.

## How reliability is handled

The tool writes about medical topics for people who often cannot judge the
source material themselves, so a fluent but wrong summary is the main risk. The
design follows from one rule in the project: **precision matters more than
completeness**. It is better to show no summary than an unverified one.

### Guardrails are enforced in code, not only requested in the prompt

The summariser's prompt tells the model to use only the given abstracts, to
cite a PMID after every claim and to give no medical advice. A prompt is a
request, though, and the model can ignore it. The model will usually comply,
but here an unnoticed slip ends up in front of someone making sense of a
diagnosis. Anything that can be checked mechanically is therefore checked by
the code after the model answers, instead of being trusted.

### Every claim must be backed by a real PMID

No summary reaches the screen until it passes a two-layer check:

1. **A deterministic check, in code.** Every PMID cited in the summary must
   belong to the articles actually retrieved from PubMed in this search, and
   the summary must cite at least once. An invented PMID, or one the model
   remembers from elsewhere, is caught here exactly, at no cost and without an
   API call.
2. **A second model call** for what code cannot judge: whether every clinical
   statement carries a citation, and whether the text slips into medical
   advice addressed to the reader ("you should…", "consult your doctor
   about…"). The verifier answers in a fixed JSON schema, so its verdict is
   parsed, not guessed from free text.

If either layer rejects the summary, it is regenerated with the specific
problems fed back to the model. After three failed attempts it is discarded and
the reason is shown. The list of references is still shown, because those
references are real and can be checked by their PMID.

What this establishes is that every citation is **real and traceable**. It does
not establish that the cited paper says what the summary claims; see
[Before you use it](#before-you-use-it).

The same thinking applies elsewhere: inside the summary, a citation is only
turned into a link if its PMID is in the retrieved set, and the summary cache is
keyed by both language and the exact set of papers, so an old or wrong-language
summary is never served as if it were fresh.

### Different failure policies, depending on what is at stake

The two model-based guardrails fail in opposite directions, on purpose:

- **Scope filter: fail-open.** Before searching, a short model call checks that
  the term is plausibly a rare-disease gene or syndrome, and blocks out-of-scope
  terms such as "flu" or "hypertension". If that call fails (timeout, API
  outage, missing key), the search **goes ahead with a visible warning**. This
  filter defines the product's scope; it does not protect content. The papers
  still come from PubMed, and blocking every search whenever the Anthropic API
  is down would make the PubMed search unusable too, even though it does not
  depend on Claude.
- **Summary verification: fail-closed.** If the verifier cannot run, that counts
  as a failed attempt, and **no unverified summary is shown**. Here the failure
  affects the medical content put in front of the reader, which is exactly what
  the verification exists to guarantee. The real references already cover the
  reader's need for information.

The rule behind both: be lenient where an error only costs convenience, and
strict where it affects what the reader takes as fact.

### Failures are never silent

If PubMed fails, you see the error and nothing is filled in. A search with no
results is reported as no results, never padded. An out-of-scope term is shown
as blocked, never disguised as "no results". Records without a PMID are dropped,
because they could not be traced.

## Design decisions

[`docs/decisions.md`](../docs/decisions.md) is a dated log of more than a
hundred design decisions, each with the reasoning behind it. It records the
alternatives that were rejected and the decisions that were later reversed, for
example the summary verifier, which was first fail-open and was switched to
fail-closed. It also records where the implementation had to deviate from the
agreed plan, and why. If you are assessing the project technically, this log is
the most useful thing to read: most of the code is easier to follow once you
know which trade-off it implements.

The log is written in Spanish, the working language of the project.

## Installation

Requires Python 3.10 or later.

```bash
git clone <this repository>
cd rare-disease-tools/paper-search
pip install -r requirements.txt
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
```

Then fill in `.env`:

| Variable | Required? | What for |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes, for summaries | Writes the summary and powers both guardrails. Without it, PubMed search still works and references are listed, but there is no summary, and the scope filter lets every term through with a warning. |
| `NCBI_EMAIL` | Recommended | NCBI asks every client to identify itself with a contact address, so that it can contact you about accidental overuse. Use your own address. |
| `NCBI_API_KEY` | No | Raises the PubMed rate limit from 3 to 10 requests per second. Free at <https://www.ncbi.nlm.nih.gov/account/>. |

Variables already set in the environment take precedence over `.env`. `.env` is
git-ignored; never commit it.

## Usage

### Web interface

```bash
python app.py
```

Then open <http://127.0.0.1:5000>. On Windows you can double-click `run.bat`
instead: it installs the dependencies on first run, starts the server and opens
the browser. Switch to English with the selector in the header. The summary is
then written, verified and exported in English as well.

The server listens only on `127.0.0.1`, and the API key never leaves the Python
process. The web interface also has favourites with personal notes, local
sorting and filtering, a "Copy for NotebookLM" export, and can be installed as
a PWA.

### Command line

The CLI's commands and messages are in Spanish (`buscar` = search). Use
`--idioma en` to get the summary in English:

```bash
python cli.py buscar "SCN1A" --idioma en
python cli.py buscar "Dravet syndrome" --max 10 --dias 365 --idioma en
python cli.py buscar "Dravet syndrome" --autor "Scheffer IE" --idioma en
python cli.py buscar "SCN1A" --formato json > results.json
```

| Option | Default | Meaning |
|---|---|---|
| `--max` | 15 | Maximum number of papers |
| `--dias` | 730 | How recent, in days |
| `--orden` | `fecha` | `fecha` (newest first) or `relevancia` (PubMed relevance) |
| `--idioma` | `es` | Summary language: `es` or `en` |
| `--formato` | `texto` | `texto` (summary + references) or `json` |
| `--autor`, `--patogeno` | — | Filter by author or by pathogen |
| `--forzar` | off | Regenerate the summary, ignoring the local cache |

Exit codes: `0` success (including a legitimate empty result), `1` usage error
or out-of-scope term, `2` external API failure or summary not produced, `3`
daily usage limit reached.

### Chrome extension

[`extension/`](../extension/) adds a right-click "search in paper-search"
action and a popup. It talks only to your local server. See its
[README](../extension/README.md) (in Spanish) for installation and the
permissions it asks for.

### Further details

The [Spanish README](README.es.md) is the full user manual: favourites, offline
behaviour of the PWA, access from a phone on the same Wi-Fi, the local cache,
daily usage limits, the JSON output format and the architecture.

## Cost and limits

A search with a summary normally makes three Claude API calls (scope filter,
summary, verification), plus up to two more for each regeneration. Repeating a
recent search costs nothing, because it is served from a local SQLite cache
(30 days, invalidated as soon as PubMed returns a different set of papers).
Two daily caps, 50 searches and 200 API calls by default, protect you from
running up your bill by accident.

## Tests

```bash
python -m pytest tests/
```

All external APIs are mocked, so the suite runs offline in a few seconds. It
covers the guardrails, retries and fail-open/fail-closed paths, cache,
limits, database migrations and both languages.

## License

[MIT](../LICENSE) © 2026 Alejandro Estevez Ruiz. It covers the whole
`rare-disease-tools` repository, including the Chrome extension.
