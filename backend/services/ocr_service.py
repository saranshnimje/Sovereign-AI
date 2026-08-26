"""
OCR service — wraps PaddleOCR for CPU-only document/image processing.

Key design decisions:
- Singleton PaddleOCR instance (expensive to initialize).
- Per-document unique temp directories (no shared /tmp/ocr_page_1.png).
- OCR runs in a thread-pool executor to avoid blocking the event loop.
- Graceful degradation: if PaddleOCR is not installed, returns empty string
  and logs a warning instead of crashing.
"""
from __future__ import annotations
import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Module-level singleton — initialized lazily on first use
_ocr_instance = None
_ocr_available: bool | None = None  # None = not yet checked


def _get_ocr():
    """Return singleton PaddleOCR instance (CPU mode). Returns None if unavailable."""
    global _ocr_instance, _ocr_available
    if _ocr_available is False:
        return None
    if _ocr_instance is not None:
        return _ocr_instance

    try:
        from paddleocr import PaddleOCR  # type: ignore
        _ocr_instance = PaddleOCR(
            use_gpu=False,
            use_angle_cls=True,
            lang="en",
            show_log=False,
        )
        _ocr_available = True
        logger.info("PaddleOCR initialized in CPU mode")
    except ImportError:
        logger.warning(
            "PaddleOCR is not installed. OCR will be skipped. "
            "Install with: pip install paddleocr paddlepaddle"
        )
        _ocr_available = False
    except Exception as exc:
        logger.warning("PaddleOCR initialization failed: %s", exc)
        _ocr_available = False

    return _ocr_instance


def _ocr_image_sync(image_path: str, confidence_threshold: float = 0.7) -> str:
    """Run OCR on a single image file. Blocking — call from executor."""
    ocr = _get_ocr()
    if ocr is None:
        return "[OCR_UNAVAILABLE]"

    try:
        result = ocr.ocr(image_path, cls=True)
        lines: list[str] = []
        if result and result[0]:
            for item in result[0]:
                if item and len(item) >= 2:
                    text = item[1][0] if item[1] else ""
                    conf = item[1][1] if item[1] and len(item[1]) > 1 else 0.0
                    if conf >= confidence_threshold:
                        lines.append(text)
                    elif text:
                        lines.append(f"[LOW_CONF:{conf:.2f}] {text}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("OCR failed on %s: %s", image_path, exc)
        return f"[OCR_ERROR: {exc}]"


def _ocr_pdf_sync(pdf_path: str, tmp_dir: str, confidence_threshold: float = 0.7) -> str:
    """Render PDF pages to images and OCR each. Blocking — call from executor."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "[PyMuPDF not available for PDF OCR]"

    doc = fitz.open(pdf_path)
    page_texts: list[str] = []
    for i, page in enumerate(doc, 1):
        # Unique filename per page in the unique temp dir
        img_path = os.path.join(tmp_dir, f"page_{i}_{uuid.uuid4().hex[:8]}.png")
        mat = fitz.Matrix(2, 2)  # 2× zoom for better OCR accuracy
        pix = page.get_pixmap(matrix=mat)
        pix.save(img_path)
        page_text = _ocr_image_sync(img_path, confidence_threshold)
        page_texts.append(f"[OCR:page_{i}]\n{page_text}")
    doc.close()
    return "\n\n".join(page_texts)


def is_ocr_available() -> bool:
    """Return True if PaddleOCR can be used."""
    return _get_ocr() is not None


async def run_ocr(
    path: str,
    mime_type: str,
    confidence_threshold: float = 0.7,
) -> str:
    """
    Async OCR entry point.
    Creates a unique temp directory, runs OCR in executor, cleans up.
    Returns extracted text (may be empty or contain error markers).
    """
    tmp_dir = os.path.join(tempfile.gettempdir(), f"sovereign_ocr_{uuid.uuid4().hex}")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        loop = asyncio.get_event_loop()

        if mime_type in ("image/png", "image/jpeg", "image/webp"):
            text = await loop.run_in_executor(
                None, _ocr_image_sync, path, confidence_threshold
            )
        elif mime_type == "application/pdf":
            text = await loop.run_in_executor(
                None, _ocr_pdf_sync, path, tmp_dir, confidence_threshold
            )
        else:
            text = ""

        return text
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def needs_ocr(text: str, mime_type: str, min_text_chars: int = 50) -> bool:
    """
    Decide whether OCR is needed:
    - Images always need OCR.
    - PDFs need OCR only if the extracted text is too short (likely scanned).
    """
    if mime_type in ("image/png", "image/jpeg", "image/webp"):
        return True
    if mime_type == "application/pdf" and len(text.strip()) < min_text_chars:
        return True
    return False
