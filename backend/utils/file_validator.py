"""
Secure file validator.
Validates MIME type (via magic bytes), extension, size, and sanitizes filename.
Never trusts the client-supplied Content-Type header.
"""
import re
import os
from pathlib import Path


# Approved (MIME type → allowed extensions)
ALLOWED_TYPES: dict[str, list[str]] = {
    "application/pdf":  [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "text/plain":       [".txt", ".md"],
    "text/markdown":    [".txt", ".md"],
    "text/csv":         [".csv"],
    "image/png":        [".png"],
    "image/jpeg":       [".jpg", ".jpeg"],
    "image/webp":       [".webp"],
}

# Magic bytes → MIME type (for offline detection without libmagic)
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF",             "application/pdf"),
    (b"PK\x03\x04",      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    (b"\xff\xd8\xff",     "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n","image/png"),
    (b"RIFF",             "image/webp"),  # WebP starts with RIFF
]


def _detect_mime(header: bytes) -> str | None:
    """Detect MIME type from first 16 bytes without requiring libmagic."""
    for sig, mime in _SIGNATURES:
        if header.startswith(sig):
            return mime
    # Try text heuristic
    try:
        header.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return None


def validate_upload(
    filename: str,
    content: bytes,
    max_size_mb: int = 50,
) -> tuple[str, str]:
    """
    Validate an uploaded file.

    Returns:
        (safe_filename, detected_mime_type)

    Raises:
        ValueError with a human-readable message on any violation.
    """
    # --- Size check first (cheap) ---
    max_bytes = max_size_mb * 1024 * 1024
    if len(content) == 0:
        raise ValueError("File is empty")
    if len(content) > max_bytes:
        raise ValueError(
            f"File size ({len(content) // (1024*1024)} MB) exceeds the "
            f"{max_size_mb} MB limit"
        )

    # --- Sanitize filename (prevent path traversal) ---
    safe = Path(filename).name                 # strip any directory parts
    safe = re.sub(r"[^\w.\-]", "_", safe)      # allow only safe chars
    safe = re.sub(r"\.{2,}", ".", safe)        # collapse consecutive dots
    safe = safe.strip("._")                    # strip leading/trailing dots
    if not safe:
        safe = "upload.bin"                    # fallback for empty/stripped names

    # --- Extension check ---
    ext = Path(safe).suffix.lower()
    all_allowed_exts = {e for exts in ALLOWED_TYPES.values() for e in exts}
    if ext not in all_allowed_exts:
        raise ValueError(
            f"File extension '{ext}' is not allowed. "
            f"Allowed: {sorted(all_allowed_exts)}"
        )

    # --- MIME detection from magic bytes ---
    detected = _detect_mime(content[:16])
    if detected is None:
        raise ValueError("Could not determine file type from content")

    # --- CSV / plain-text disambiguation ---
    if detected == "text/plain" and ext == ".csv":
        detected = "text/csv"

    # --- MIME not in allowlist ---
    if detected not in ALLOWED_TYPES:
        raise ValueError(f"File type '{detected}' is not allowed")

    # --- Extension must match detected MIME ---
    if ext not in ALLOWED_TYPES[detected]:
        # Allow .md for text/plain
        if not (detected == "text/plain" and ext == ".md"):
            raise ValueError(
                f"File extension '{ext}' does not match detected type '{detected}'"
            )

    return safe, detected
