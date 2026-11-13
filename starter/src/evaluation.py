"""Evaluate source-and-evidence retrieval and aggregate split-specific metrics."""
from typing import Any


def _normalized(value: object) -> str:
    return " ".join(str(value).casefold().split())


def _gold_records(question: dict[str, Any]) -> list[dict[str, Any]]:
    alternatives = question.get("gold_evidence")
    if isinstance(alternatives, list) and alternatives:
        return [item for item in alternatives if isinstance(item, dict)]
    return [
        {
            "document_id": question.get("gold_source_id"),
            "page": question.get("gold_page"),
            "evidence_quote": question.get("evidence_quote", ""),
        }
    ]


def _is_evidence_hit(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    metadata = hit.get("metadata") or {}
    hit_document = hit.get("document_id", metadata.get("document_id"))
    hit_page = hit.get("page", metadata.get("page"))
    hit_text = _normalized(hit.get("text", ""))

    for gold in _gold_records(question):
        gold_document = gold.get("document_id", gold.get("gold_source_id"))
        gold_page = gold.get("page", gold.get("gold_page"))
        quote = _normalized(gold.get("evidence_quote", ""))
        if not gold_document or gold_page is None or not quote:
            continue
        if _normalized(hit_document) != _normalized(gold_document):
            continue
        if str(hit_page) != str(gold_page):
            continue
        if quote in hit_text:
            return True
    return False


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Mark exact evidence-containing source/page matches, retaining all top-k hits."""
    hit_flags = [_is_evidence_hit(question, hit) for hit in hits]
    return {
        "question_id": question["id"],
        "split": question["split"],
        "hit_at_1": bool(hit_flags and hit_flags[0]),
        "evidence_hit_at_3": any(hit_flags[:3]),
        "evidence_hit_by_rank": hit_flags[:3],
        "hits": hits[:3],
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 and Evidence Hit@3 by strategy and split."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trace in traces:
        groups.setdefault((trace["strategy"], trace["split"]), []).append(trace)

    summary: dict[str, Any] = {}
    for (strategy, split), rows in sorted(groups.items()):
        total = len(rows)
        hit1 = sum(bool(row["hit_at_1"]) for row in rows)
        hit3 = sum(bool(row["evidence_hit_at_3"]) for row in rows)
        summary.setdefault(strategy, {})[split] = {
            "questions": total,
            "hit_at_1": {"hits": hit1, "total": total, "rate": hit1 / total},
            "evidence_hit_at_3": {
                "hits": hit3,
                "total": total,
                "rate": hit3 / total,
            },
        }
    return summary
