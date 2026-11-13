import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.chunking import by_paragraph, fixed_size
from src.evaluation import evaluate_query, summarize
from src.ingestion import normalize_text
from src.models import DocumentPage
from src.run import DATA_DIR, _load_corpus, _read_json, _validate_questions
from src.store import QdrantVectorStore


class NormalizeTextTests(unittest.TestCase):
    def test_normalizes_unicode_and_whitespace_but_keeps_paragraphs(self) -> None:
        self.assertEqual(
            normalize_text("Cafe\u0301\t  policy\r\n\r\n\r\n next\u00a0line "),
            "Café policy\n\nnext line",
        )


class ChunkingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = DocumentPage(
            document_id="doc-1",
            source="public.pdf",
            page=2,
            text="one two\n\nthree four five",
            metadata={"section": "intro"},
        )

    def test_fixed_size_retains_metadata_and_overlaps(self) -> None:
        page = DocumentPage("doc", "source", 1, "abcdefgh")
        chunks = fixed_size(page, size=4, overlap=1)

        self.assertEqual([chunk.text for chunk in chunks], ["abcd", "defg", "gh"])
        self.assertTrue(all(chunk.page == 1 for chunk in chunks))

    def test_paragraph_chunking_respects_limit_and_preserves_metadata(self) -> None:
        chunks = by_paragraph(self.page, max_size=10)

        self.assertEqual([chunk.text for chunk in chunks], ["one two", "three four", "five"])
        self.assertTrue(all(chunk.metadata == {"section": "intro"} for chunk in chunks))
        self.assertTrue(all(len(chunk.text) <= 10 for chunk in chunks))

    def test_invalid_chunk_parameters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            fixed_size(self.page, size=4, overlap=4)
        with self.assertRaises(ValueError):
            by_paragraph(self.page, max_size=0)


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.question = {
            "id": "q1",
            "split": "test",
            "gold_source_id": "doc-1",
            "gold_page": 2,
            "evidence_quote": "deadline is June 30",
        }

    def test_requires_matching_document_page_and_evidence(self) -> None:
        hits = [
            {"document_id": "doc-1", "page": 2, "text": "The deadline is June 30."},
            {"document_id": "doc-1", "page": 3, "text": "The deadline is June 30."},
            {"document_id": "doc-2", "page": 2, "text": "The deadline is June 30."},
        ]
        result = evaluate_query(self.question, hits)

        self.assertTrue(result["hit_at_1"])
        self.assertTrue(result["evidence_hit_at_3"])
        self.assertEqual(result["evidence_hit_by_rank"], [True, False, False])

    def test_accepts_documented_alternative_gold_evidence(self) -> None:
        question = {
            **self.question,
            "gold_evidence": [
                {
                    "document_id": "doc-alt",
                    "page": 7,
                    "evidence_quote": "Requests close on Friday",
                }
            ],
        }
        result = evaluate_query(
            question,
            [{"document_id": "doc-alt", "page": 7, "text": "Requests close on Friday."}],
        )

        self.assertTrue(result["hit_at_1"])

    def test_summarize_reports_hit_counts_and_rates_per_split(self) -> None:
        traces = [
            {
                "strategy": "A",
                "split": "dev",
                "hit_at_1": True,
                "evidence_hit_at_3": True,
            },
            {
                "strategy": "A",
                "split": "dev",
                "hit_at_1": False,
                "evidence_hit_at_3": True,
            },
        ]

        result = summarize(traces)

        self.assertEqual(result["A"]["dev"]["hit_at_1"], {"hits": 1, "total": 2, "rate": 0.5})
        self.assertEqual(
            result["A"]["dev"]["evidence_hit_at_3"],
            {"hits": 2, "total": 2, "rate": 1.0},
        )


class BenchmarkValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = DocumentPage(
            document_id="doc-1",
            source="public.pdf",
            page=1,
            text=" ".join(f"Evidence quote {index}" for index in range(20)),
            metadata={"section": "general"},
        )
        self.questions = [
            {
                "id": f"q{index}",
                "split": "dev" if index < 15 else "test",
                "question": f"Question {index}?",
                "expected_answer": f"Answer {index}",
                "gold_source_id": "doc-1",
                "gold_page": 1,
                "evidence_quote": f"Evidence quote {index}",
                **(
                    {"filter": {"section": "general"}}
                    if index in (0, 1, 15)
                    else {}
                ),
            }
            for index in range(20)
        ]

    def test_accepts_minimum_valid_question_set(self) -> None:
        self.assertEqual(_validate_questions(self.questions, [self.page]), self.questions)

    def test_rejects_missing_metadata_filter_coverage(self) -> None:
        questions = [dict(question) for question in self.questions]
        questions[15].pop("filter")

        with self.assertRaisesRegex(ValueError, "metadata-filter"):
            _validate_questions(questions, [self.page])

    def test_downloaded_nasa_corpus_and_gold_evidence_are_valid(self) -> None:
        manifest = _read_json(DATA_DIR / "manifest.json")
        benchmark = _read_json(DATA_DIR / "questions.json")
        pages = _load_corpus(manifest)

        self.assertEqual(len(pages), 36)
        self.assertEqual(
            _validate_questions(benchmark.get("questions"), pages),
            benchmark["questions"],
        )


class QdrantStoreTests(unittest.TestCase):
    def test_persistent_store_filters_metadata_and_replaces_old_points(self) -> None:
        with TemporaryDirectory() as directory:
            store = QdrantVectorStore(Path(directory) / "qdrant", dimensions=2)
            try:
                store.create_schema()
                chunks = [
                    DocumentPage("doc-a", "nasa-a", 1, "alpha", {"category": "moon"}),
                    DocumentPage("doc-b", "nasa-b", 1, "beta", {"category": "planet"}),
                ]
                from src.models import Chunk

                qdrant_chunks = [
                    Chunk(
                        chunk_id=page.document_id,
                        document_id=page.document_id,
                        source=page.source,
                        page=page.page,
                        text=page.text,
                        metadata=page.metadata,
                    )
                    for page in chunks
                ]
                store.upsert("B", qdrant_chunks, [[1.0, 0.0], [0.0, 1.0]])
                filtered = store.search(
                    "B", [1.0, 0.0], top_k=3, filters={"category": "moon"}
                )
                self.assertEqual([hit["document_id"] for hit in filtered], ["doc-a"])

                store.upsert("B", qdrant_chunks[:1], [[1.0, 0.0]])
                self.assertEqual(
                    store.client.count("day6_b", exact=True).count,
                    1,
                )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
