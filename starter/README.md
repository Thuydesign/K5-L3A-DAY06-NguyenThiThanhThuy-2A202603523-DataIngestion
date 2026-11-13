# Starter · NASA Space Science + local retrieval

The pipeline uses NASA Science pages, a local FastEmbed model, and an embedded
persistent Qdrant database. It makes **no embedding API calls** and does not
require Docker or a database server. You must still review the source rights,
gold evidence, and human-audit templates before submitting the lab.

## 1. Install and download the corpus

Use Python 3.10 or newer. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts\fetch_nasa_corpus.py
```

The downloader saves NASA Science page text as separate, attributed source units
under `data/nasa_space_science/` and writes `data/manifest.json`. Every unit must
contain at least 1,500 normalized characters; the runner checks this and requires
at least 30 units. The manifest records the original NASA URL, access date,
topic metadata, unit size, and a snapshot SHA-256. The downloader only follows
redirects within `science.nasa.gov`.

NASA's media guidance explains that some third-party material has separate
rights. The pages are gathered for this noncommercial educational lab and credit
NASA; the source pages do not provide a separate license for every text passage.
Check the attribution and rights notes before publishing or redistributing the
corpus.

## 2. Local model and vector store

The default model is
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions,
Apache-2.0), run by FastEmbed using ONNX Runtime on CPU. The model weights are
downloaded once and cached under `%USERPROFILE%\.cache\fastembed` (override with
`FASTEMBED_CACHE_PATH`). Afterward, embedding and retrieval run locally without
an API key, account, or embedding service. To prohibit even model-cache network
access on later runs, set `FASTEMBED_LOCAL_FILES_ONLY=true` in `.env`. Do not
configure API keys for this lab.

Qdrant runs embedded in the Python process and persists under
`results/qdrant_local/`. The store uses cosine similarity and exact local search
(HNSW disabled). Each rerun replaces each strategy's collection, preventing stale or duplicate
chunks from remaining.

## 3. Benchmark inputs

Create `data/questions.json` as `{"questions": [...]}`. Each question needs
`id`, `split` (`dev` or `test`), `question`, `expected_answer`, and either
`gold_source_id`, `gold_page`, `evidence_quote`, or a `gold_evidence` list of
`document_id`/`page`/`evidence_quote` objects. `filter` is an optional metadata
object; use it only when the question supplies that scope before retrieval.

The runner validates at least 20 questions, 15 dev / 5 test, three metadata
filter questions (including one test), every filter value against corpus
metadata, and every quote against its cited NASA source unit. It checks format
and exact evidence presence, but you must independently confirm each answer,
source and quote before using the benchmark.

## 4. Run and audit

```powershell
python -m unittest discover -s tests -v
python -m src.run
```

The run creates:

- `results/corpus_manifest.json`: downloaded source units and character counts.
- `results/traces.jsonl`: top-3 hits, scores, metadata, gold and split for A/B/C.
- `results/summary.json`: Hit@1 and Evidence Hit@3 counts/rates by split.
- `results/run_metadata.json`: model, store, chunk statistics and timings.
- `results/manual_audit_template.jsonl`: blank human labels for coherence,
  metadata accuracy, and grounding. Fill these from the trace; the blank
  template is not evidence that an audit has been performed.

Strategies A and B compare fixed-size with paragraph-aware chunking. C uses the
same paragraph chunks/vectors as B and applies the question's metadata filter.
The benchmark runs all three strategies over the same dev/test questions; choose
any preferred strategy from dev before interpreting test results. Report all
test comparisons as the lab's small illustrative holdout, not as general proof.
No measured result, personal information, or human label is pre-filled.

## 5. Optional PDF inputs

The ingestion module also supports PDF pages. To use the PostgreSQL starter
instead, the original Compose files remain available, but this lab's default
runner uses local Qdrant and needs no PostgreSQL service.
