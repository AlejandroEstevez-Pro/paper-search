# rare-disease-tools

AI tools to help people find their way through the research literature on rare
diseases.

> **Not a diagnostic tool and no substitute for medical judgement.** These tools
> help you search the literature. They tell you nothing about any particular
> patient. The summaries are written by a language model and checked
> automatically, but the checks are not infallible. Read
> [what they cover and what they don't](paper-search/README.md#before-you-use-it)
> before relying on anything they say.

| Component | What it does | Status |
|---|---|---|
| [`paper-search/`](paper-search/README.md) | Given a gene or syndrome, searches PubMed and writes a plain-language summary of recent findings, with every statement cited to its PMID and checked before it is shown | Usable |
| [`extension/`](extension/README.md) | Chrome extension: right-click any selected text to search it in your local paper-search | Usable |
| `symptom-classifier/` | Given a set of symptoms, suggest candidate syndromes | Planned, not started |

Start with the [paper-search README](paper-search/README.md). It explains what
the tool does, how it guards against fabricated or untraceable content, and how
to install it. Design decisions and their reasons are logged in
[`docs/decisions.md`](docs/decisions.md) (in Spanish).

## License

[MIT](LICENSE) © 2026 Alejandro Estevez Ruiz
