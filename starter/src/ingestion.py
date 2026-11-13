"""Read and normalize source data while retaining physical page numbers."""
import logging
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

logger = logging.getLogger(__name__)


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract every physical PDF page; warn when a page has no extractable text."""
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError(f"Encrypted PDF cannot be read without a password: {path}")

    pages: list[DocumentPage] = []
    for page_number, pdf_page in enumerate(reader.pages, start=1):
        text = normalize_text(pdf_page.extract_text() or "")
        if not text:
            logger.warning("No extractable text: document=%s page=%d", document_id, page_number)
        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_number,
                text=text,
            )
        )
    return pages


def load_text_unit(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Load one independently sourced text unit and retain its source URL."""
    try:
        text = normalize_text(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as error:
        raise ValueError(f"Text source must be UTF-8 encoded: {path}") from error
    if not text:
        logger.warning("No extractable text: document=%s", document_id)
    return [DocumentPage(document_id=document_id, source=source, page=1, text=text)]


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace while preserving paragraph boundaries."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines = [" ".join(line.split()) for line in text.split("\n")]

    normalized_lines: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        normalized_lines.append(line)
        previous_blank = is_blank
    return "\n".join(normalized_lines).strip()
