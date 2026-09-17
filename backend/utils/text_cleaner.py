"""
Deterministic text normalizer.
No LLM calls — pure string processing.
"""
import re
import unicodedata


def clean_text(text: str) -> str:
    """
    Normalize extracted document text.

    - Normalize Unicode (NFC)
    - Replace Windows line endings
    - Collapse runs of >2 blank lines to a single blank line
    - Remove null bytes and other control characters (except newlines/tabs)
    - Collapse horizontal whitespace within lines
    - Strip leading/trailing whitespace
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    return text.strip()


def is_mostly_empty(text: str, min_chars: int = 1) -> bool:
    """
    Return True only when extraction produced no usable non-whitespace text.

    Short documents are valid knowledge-base documents too (for example,
    "test1", a title, a short policy note, or a one-line instruction), so a
    fixed 20-character minimum incorrectly rejects legitimate uploads.
    """
    return len(text.strip()) < min_chars
