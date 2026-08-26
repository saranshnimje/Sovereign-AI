"""
Text extraction service — dispatches by MIME type.
Returns (text, page_count). Adds [Page N] markers for PDFs.
All extraction is synchronous; call from a thread-pool executor if needed.
"""
from __future__ import annotations
import asyncio
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    pass


def _extract_pdf(path: str) -> tuple[str, int]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ExtractionError("PyMuPDF is not installed (pip install PyMuPDF)")

    try:
        doc = fitz.open(path)
        pages: list[str] = []
        for i, page in enumerate(doc, 1):
            page_text = page.get_text("text") or ""
            pages.append(f"[Page {i}]\n{page_text}")
        doc.close()
        return "\n\n".join(pages), len(pages)
    except Exception as exc:
        raise ExtractionError(f"PDF extraction failed: {exc}") from exc


def _extract_docx(path: str) -> tuple[str, int]:
    try:
        from docx import Document  # python-docx
    except ImportError:
        raise ExtractionError("python-docx is not installed")

    try:
        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs)
        return text, 1
    except Exception as exc:
        raise ExtractionError(f"DOCX extraction failed: {exc}") from exc


def _extract_txt(path: str) -> tuple[str, int]:
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = Path(path).read_text(encoding=enc)
            return text, 1
        except (UnicodeDecodeError, LookupError):
            continue
    raise ExtractionError("Could not decode text file with any supported encoding")


def _extract_csv(path: str) -> tuple[str, int]:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        raise ExtractionError("pandas is not installed")

    try:
        df = pd.read_csv(path, dtype=str, na_filter=False)
        # Produce human-readable rows — do NOT execute cell content
        lines = [",".join(df.columns.tolist())]
        for _, row in df.iterrows():
            lines.append(",".join(str(v) for v in row.tolist()))
        return "\n".join(lines), 1
    except Exception as exc:
        raise ExtractionError(f"CSV extraction failed: {exc}") from exc


_EXTRACTORS: dict[str, object] = {
    "application/pdf": _extract_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _extract_docx,
    "text/plain": _extract_txt,
    "text/markdown": _extract_txt,
    "text/csv": _extract_csv,
}


async def extract_text(path: str, mime_type: str) -> tuple[str, int]:
    """
    Async wrapper: runs sync extraction in the default thread-pool.
    Returns (extracted_text, page_count).
    Images (PNG/JPEG/WEBP) return ("", 1) — text comes from OCR.
    """
    if mime_type in ("image/png", "image/jpeg", "image/webp"):
        return "", 1

    fn = _EXTRACTORS.get(mime_type)
    if fn is None:
        raise ExtractionError(f"No extractor for MIME type: {mime_type}")

    loop = asyncio.get_event_loop()
    text, pages = await loop.run_in_executor(None, fn, path)  # type: ignore[arg-type]
    return text, pages
