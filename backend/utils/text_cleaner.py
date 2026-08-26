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

    # Unicode normalization
    text = unicodedata.normalize("NFC", text)

    # Windows line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove null bytes and other control characters (keep \n \t)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Collapse 3+ consecutive blank lines → single blank line
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Collapse multiple spaces/tabs within a line to single space
    text = re.sub(r"[ \t]+", " ", text)

    # Strip trailing spaces from each line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


def is_mostly_empty(text: str, min_chars: int = 20) -> bool:
    """Return True if the text is too short to be meaningful."""
    return len(text.strip()) < min_chars
