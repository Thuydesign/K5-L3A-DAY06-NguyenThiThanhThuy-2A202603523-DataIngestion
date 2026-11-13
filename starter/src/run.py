"""Run the Day 06 ingestion pipeline and retrieval benchmark."""
import json
import logging
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import DEFAULT_MODEL, MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf, load_text_unit, normalize_text
from .models import Chunk, DocumentPage
from .store import QdrantVectorStore

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
logger = logging.getLogger(__name__)
CORE_METADATA_FIELDS = {"document_id", "source", "page"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Required input file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _load_corpus(manifest: dict[str, Any]) -> list[DocumentPage]:
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("manifest.json must contain a non-empty 'documents' list")

    pages: list[DocumentPage] = []
    seen_ids: set[str] = set()
    custom_metadata_fields: set[str] = set()
    for item in documents:
        if not isinstance(item, dict):
            raise ValueError("Every manifest document must be a JSON object")
        document_id = str(item.get("document_id", "")).strip()
        title = str(item.get("title", "")).strip()
        source = str(item.get("source_path_or_url", item.get("source", ""))).strip()
        license_info = str(item.get("license_or_permission", "")).strip()
        accessed_at = str(item.get("accessed_at", "")).strip()
        raw_path = item.get("path")
        if not document_id or document_id in seen_ids:
            raise ValueError(f"Document IDs must be present and unique: {document_id!r}")
        if not title or not source or not license_info or not accessed_at:
            raise ValueError(
                f"Document {document_id!r} needs title, source_path_or_url, "
                "license_or_permission, and accessed_at in the manifest"
            )
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"Document {document_id!r} must have a local PDF or text 'path'")
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"Document {document_id!r} metadata must be an object")
        custom_metadata_fields.update(set(metadata) - CORE_METADATA_FIELDS)

        pdf_path = (DATA_DIR / raw_path).resolve()
        if not pdf_path.is_relative_to(DATA_DIR.resolve()):
            raise ValueError(f"PDF path must stay inside {DATA_DIR}: {raw_path}")
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF for document {document_id!r} not found: {pdf_path}")

        if pdf_path.suffix.lower() == ".pdf":
            document_pages = load_pdf(pdf_path, document_id, source)
        elif pdf_path.suffix.lower() in {".txt", ".md"}:
            document_pages = load_text_unit(pdf_path, document_id, source)
            if len(document_pages[0].text) < 1500:
                raise ValueError(
                    f"Text source {document_id!r} has {len(document_pages[0].text)} "
                    "characters; each independent text source unit must contain "
                    "at least 1,500 normalized characters"
                )
        else:
            raise ValueError(
                f"Document {document_id!r} has unsupported file type: {pdf_path.suffix}"
            )
        include_pages = item.get("include_pages")
        if include_pages is not None:
            if (
                not isinstance(include_pages, list)
                or not include_pages
                or any(not isinstance(page, int) or page <= 0 for page in include_pages)
            ):
                raise ValueError(f"include_pages for {document_id!r} must be positive page numbers")
            requested = set(include_pages)
            available = {page.page for page in document_pages}
            missing = requested - available
            if missing:
                raise ValueError(
                    f"Document {document_id!r} has no physical pages: {sorted(missing)}"
                )
            document_pages = [page for page in document_pages if page.page in requested]

        for page in document_pages:
            page.metadata.update(metadata)
        pages.extend(document_pages)
        seen_ids.add(document_id)

    if not custom_metadata_fields:
        raise ValueError("Manifest documents need at least one source-backed filter metadata field")
    content_pages = [page for page in pages if page.text]
    if len(content_pages) < 30:
        raise ValueError(
            f"Corpus has {len(content_pages)} non-empty included pages; at least 30 are required"
        )
    return content_pages


def _gold_records(question: dict[str, Any]) -> list[dict[str, Any]]:
    alternatives = question.get("gold_evidence")
    if isinstance(alternatives, list) and alternatives:
        if not all(isinstance(item, dict) for item in alternatives):
            raise ValueError(f"Question {question.get('id')} has invalid gold_evidence")
        return alternatives
    return [
        {
            "document_id": question.get("gold_source_id"),
            "page": question.get("gold_page"),
            "evidence_quote": question.get("evidence_quote"),
        }
    ]


def _validate_questions(
    questions: object, pages: list[DocumentPage]
) -> list[dict[str, Any]]:
    if not isinstance(questions, list) or len(questions) < 20:
        raise ValueError("questions.json must contain at least 20 questions")
    by_page = {(page.document_id, page.page): page for page in pages}
    seen_ids: set[str] = set()
    split_counts = {"dev": 0, "test": 0}
    filtered_count = 0
    filtered_test_count = 0
    custom_metadata_fields = {
        key
        for page in pages
        for key in page.metadata
        if key not in CORE_METADATA_FIELDS
    }

    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Every benchmark question must be a JSON object")
        question_id = str(question.get("id", "")).strip()
        split = question.get("split")
        if not question_id or question_id in seen_ids:
            raise ValueError(f"Question IDs must be present and unique: {question_id!r}")
        if not isinstance(split, str) or split not in split_counts:
            raise ValueError(f"Question {question_id!r} split must be 'dev' or 'test'")
        if not str(question.get("question", "")).strip():
            raise ValueError(f"Question {question_id!r} has no question text")
        if not str(question.get("expected_answer", "")).strip():
            raise ValueError(f"Question {question_id!r} has no expected_answer")
        seen_ids.add(question_id)
        split_counts[split] += 1

        filters = question.get("filter")
        if filters is not None:
            if not isinstance(filters, dict) or not filters:
                raise ValueError(f"Question {question_id!r} filter must be a non-empty object")
            if not any(key in custom_metadata_fields for key in filters):
                raise ValueError(
                    f"Question {question_id!r} filter must use a source-backed metadata field"
                )
            filtered_count += 1
            if split == "test":
                filtered_test_count += 1
            matching_pages = [
                page
                for page in pages
                if all(
                    {**page.metadata, "document_id": page.document_id,
                     "source": page.source, "page": page.page}.get(key) == value
                    for key, value in filters.items()
                )
            ]
            if not matching_pages:
                raise ValueError(
                    f"Question {question_id!r} filter matches no source page: {filters}"
                )

        records = _gold_records(question)
        if not records:
            raise ValueError(f"Question {question_id!r} has no gold evidence")
        for record in records:
            document_id = record.get("document_id", record.get("gold_source_id"))
            page_number = record.get("page", record.get("gold_page"))
            quote = str(record.get("evidence_quote", "")).strip()
            page = by_page.get((document_id, page_number))
            if page is None or not quote:
                raise ValueError(f"Question {question_id!r} has incomplete or unknown gold evidence")
            normalized_quote = " ".join(normalize_text(quote).casefold().split())
            normalized_text = " ".join(normalize_text(page.text).casefold().split())
            if normalized_quote not in normalized_text:
                raise ValueError(
                    f"Question {question_id!r} evidence quote is not present on "
                    f"{document_id} page {page_number}"
                )

    if split_counts["dev"] < 15 or split_counts["test"] < 5:
        raise ValueError(
            f"Need at least 15 dev and 5 test questions; found {split_counts}"
        )
    if filtered_count < 3 or filtered_test_count < 1:
        raise ValueError("Need at least 3 metadata-filter questions, including 1 test question")
    return questions


def _corpus_manifest(
    manifest: dict[str, Any], pages: list[DocumentPage]
) -> dict[str, Any]:
    page_groups: dict[str, list[DocumentPage]] = {}
    for page in pages:
        page_groups.setdefault(page.document_id, []).append(page)
    entries = []
    for document in manifest["documents"]:
        document_id = document["document_id"]
        document_pages = sorted(page_groups.get(document_id, []), key=lambda page: page.page)
        entries.append(
            {
                "document_id": document_id,
                "title": document["title"],
                "source_path_or_url": document.get(
                    "source_path_or_url", document.get("source")
                ),
                "license_or_permission": document["license_or_permission"],
                "accessed_at": document["accessed_at"],
                "page_count_with_text": len(document_pages),
                "pages": [
                    {"page": page.page, "character_count": len(page.text)}
                    for page in document_pages
                ],
                "total_characters": sum(len(page.text) for page in document_pages),
            }
        )
    return {"documents": entries}


def _make_strategies(pages: list[DocumentPage]) -> dict[str, list[Chunk]]:
    strategies: dict[str, list[Chunk]] = {"A": [], "B": [], "C": []}
    for page in pages:
        strategies["A"].extend(fixed_size(page, size=500, overlap=50))
        paragraph_chunks = by_paragraph(page, max_size=1000)
        strategies["B"].extend(paragraph_chunks)
        strategies["C"].extend(paragraph_chunks)
    if any(not chunks for chunks in strategies.values()):
        raise ValueError("Every strategy must produce at least one chunk")
    return strategies


def _embed_chunks(embedder: MyEmbedder, chunks: list[Chunk]) -> list[list[float]]:
    vectors: list[list[float]] = []
    batch_size = 64
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors.extend(embedder.embed_documents([chunk.text for chunk in batch]))
    if len(vectors) != len(chunks):
        raise ValueError("Embedding provider returned an incomplete chunk batch")
    return vectors


def _manual_audit_rows(
    traces: list[dict[str, Any]],
    pages: list[DocumentPage],
    strategies: dict[str, list[Chunk]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    test_questions = [
        trace
        for trace in traces
        if trace["split"] == "test" and trace["strategy"] == "A"
    ][:5]
    for strategy in ("A", "B", "C"):
        for trace in test_questions:
            matching_trace = next(
                item
                for item in traces
                if item["strategy"] == strategy
                and item["question_id"] == trace["question_id"]
            )
            rows.append(
                {
                    "kind": "grounding",
                    "strategy": strategy,
                    "question_id": trace["question_id"],
                    "candidate_hits": matching_trace["hits"],
                    "score_0_to_2": None,
                    "reason": "",
                }
            )
            for rank, hit in enumerate(matching_trace["hits"], start=1):
                rows.append(
                    {
                        "kind": "metadata",
                        "strategy": strategy,
                        "question_id": trace["question_id"],
                        "rank": rank,
                        "chunk_id": hit["chunk_id"],
                        "metadata": hit["metadata"],
                        "expected_gold": (
                            matching_trace["question"].get("gold_evidence")
                            or [
                                {
                                    "document_id": matching_trace["question"].get(
                                        "gold_source_id"
                                    ),
                                    "page": matching_trace["question"].get("gold_page"),
                                }
                            ]
                        ),
                        "applied_filter": matching_trace["applied_filter"],
                        "correct_and_complete": None,
                        "error": "",
                    }
                )

    sample_pages = sorted(pages, key=lambda page: (page.document_id, page.page))[:10]
    for strategy in ("A", "B", "C"):
        chunks_by_page: dict[tuple[str, int], list[Chunk]] = {}
        for chunk in strategies[strategy]:
            chunks_by_page.setdefault((chunk.document_id, chunk.page), []).append(chunk)
        for page in sample_pages:
            page_chunks = chunks_by_page.get((page.document_id, page.page), [])
            if not page_chunks:
                continue
            rows.append(
                {
                    "kind": "coherence",
                    "strategy": strategy,
                    "sample_position": {
                        "document_id": page.document_id,
                        "page": page.page,
                        "character_offset": 0,
                    },
                    "chunk_id": page_chunks[0].chunk_id,
                    "chunk_text": page_chunks[0].text,
                    "score_0_to_2": None,
                    "reason": "",
                }
            )
    return rows


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Ingest a corpus, build A/B/C indexes, and save reproducible retrieval traces."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv(ROOT / ".env")

    manifest = _read_json(DATA_DIR / "manifest.json")
    benchmark = _read_json(DATA_DIR / "questions.json")
    pages = _load_corpus(manifest)
    questions = _validate_questions(benchmark.get("questions"), pages)

    model_name = os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL).strip()
    if not model_name:
        model_name = DEFAULT_MODEL
    embedder = MyEmbedder(model_name)
    store_path = Path(os.getenv("QDRANT_PATH", str(RESULTS_DIR / "qdrant_local")))
    if not store_path.is_absolute():
        store_path = ROOT / store_path
    store = QdrantVectorStore(store_path, embedder.dimensions)
    store.create_schema()

    strategies = _make_strategies(pages)
    strategy_stats: dict[str, Any] = {}
    strategy_vectors: dict[str, list[list[float]]] = {}
    for strategy, chunks in strategies.items():
        embedding_seconds = 0.0
        vectors = (
            strategy_vectors["B"]
            if strategy == "C"
            else None
        )
        if vectors is None:
            embedding_started = time.perf_counter()
            vectors = _embed_chunks(embedder, chunks)
            embedding_seconds = time.perf_counter() - embedding_started
        store_started = time.perf_counter()
        store.upsert(strategy, chunks, vectors)
        store_write_seconds = time.perf_counter() - store_started
        strategy_vectors[strategy] = vectors
        chunk_lengths = [len(chunk.text) for chunk in chunks]
        strategy_stats[strategy] = {
            "chunk_count": len(chunks),
            "total_chunk_characters": sum(chunk_lengths),
            "chunk_length_characters": {
                "min": min(chunk_lengths),
                "median": statistics.median(chunk_lengths),
                "max": max(chunk_lengths),
            },
            "embedding_seconds": round(embedding_seconds, 3),
            "store_write_seconds": round(store_write_seconds, 3),
            "total_build_seconds": round(embedding_seconds + store_write_seconds, 3),
            "time_note": (
                "Embedding is reused from B; this is incremental index-write time."
                if strategy == "C"
                else "Includes local document embedding and index write."
            ),
        }

    traces: list[dict[str, Any]] = []
    for question in questions:
        query_vector = embedder.embed_query(question["question"])
        for strategy in ("A", "B", "C"):
            applied_filter = question.get("filter") if strategy == "C" else None
            hits = store.search(strategy, query_vector, top_k=3, filters=applied_filter)
            evaluated = evaluate_query(question, hits)
            traces.append(
                {
                    "strategy": strategy,
                    **evaluated,
                    "question": question,
                    "applied_filter": applied_filter,
                }
            )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with (RESULTS_DIR / "traces.jsonl").open("w", encoding="utf-8") as output:
        for trace in traces:
            output.write(json.dumps(trace, ensure_ascii=False) + "\n")
    with (RESULTS_DIR / "manual_audit_template.jsonl").open(
        "w", encoding="utf-8"
    ) as output:
        for row in _manual_audit_rows(traces, pages, strategies):
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    _write_json(RESULTS_DIR / "corpus_manifest.json", _corpus_manifest(manifest, pages))
    _write_json(RESULTS_DIR / "summary.json", summarize(traces))
    _write_json(
        RESULTS_DIR / "run_metadata.json",
        {
            "python_version": platform.python_version(),
            "embedding_model": embedder.model_name,
            "embedding_dimensions": embedder.dimensions,
            "embedding_library": "FastEmbed (ONNX Runtime, CPU)",
            "embedding_model_license": embedder.license,
            "vector_store": "Qdrant embedded local",
            "vector_store_path": str(store_path),
            "similarity": "cosine",
            "search_mode": "exact (embedded local mode, HNSW disabled)",
            "non_empty_content_pages": len(pages),
            "question_count": len(questions),
            "strategy_stats": strategy_stats,
            "embedding_api_requests": 0,
            "embedding_tokens": None,
            "embedding_token_usage_complete": False,
            "embedding_cost_usd": 0,
            "cost_note": "Embeddings run locally; no embedding API was called.",
        },
    )
    logger.info("Saved top-3 traces and summaries under %s", RESULTS_DIR)
    store.close()


if __name__ == "__main__":
    main()
