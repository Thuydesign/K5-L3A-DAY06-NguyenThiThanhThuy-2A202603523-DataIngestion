"""Deterministic chunking strategies that preserve document and page metadata."""
import hashlib

from .models import Chunk, DocumentPage


def _chunk(page: DocumentPage, text: str, ordinal: int, strategy: str) -> Chunk:
    digest = hashlib.sha256(
        f"{page.document_id}\0{page.page}\0{strategy}\0{ordinal}\0{text}".encode("utf-8")
    ).hexdigest()[:24]
    return Chunk(
        chunk_id=digest,
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata={**page.metadata},
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Split a page into deterministic character windows with a fixed overlap."""
    if size <= 0:
        raise ValueError("size must be a positive integer")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be non-negative and smaller than size")
    if not page.text:
        return []

    step = size - overlap
    chunks = []
    for ordinal, start in enumerate(range(0, len(page.text), step)):
        text = page.text[start : start + size].strip()
        if text:
            chunks.append(_chunk(page, text, ordinal, "fixed"))
    return chunks


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group whole paragraphs up to max_size and split oversized paragraphs."""
    if max_size <= 0:
        raise ValueError("max_size must be a positive integer")
    if not page.text:
        return []

    paragraphs = [part.strip() for part in page.text.split("\n") if part.strip()]
    chunks: list[Chunk] = []
    current: list[str] = []
    current_length = 0

    def flush() -> None:
        nonlocal current, current_length
        if current:
            chunks.append(_chunk(page, "\n".join(current), len(chunks), "paragraph"))
            current = []
            current_length = 0

    for paragraph in paragraphs:
        if len(paragraph) > max_size:
            flush()
            remaining = paragraph
            while len(remaining) > max_size:
                boundary = remaining.rfind(" ", 0, max_size + 1)
                if boundary <= 0:
                    boundary = max_size
                piece = remaining[:boundary].strip()
                if piece:
                    chunks.append(_chunk(page, piece, len(chunks), "paragraph"))
                remaining = remaining[boundary:].strip()
            if remaining:
                chunks.append(_chunk(page, remaining, len(chunks), "paragraph"))
            continue

        added_length = len(paragraph) + (1 if current else 0)
        if current and current_length + added_length > max_size:
            flush()
            added_length = len(paragraph)
        current.append(paragraph)
        current_length += added_length

    flush()
    return chunks
