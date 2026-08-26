"""
Recursive character-based text chunker.
Splits by semantic boundaries: paragraphs → sentences → words → characters.
Each chunk retains source metadata for RAG citation.
"""
from __future__ import annotations
import re
import uuid
from dataclasses import dataclass, field


@dataclass
class TextChunk:
    chunk_id: str
    content: str
    chunk_index: int
    token_count: int
    page_number: int | None = None
    char_start: int = 0
    char_end: int = 0


_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _estimate_tokens(text: str) -> int:
    """Approximate token count: ~4 chars per token for English."""
    return max(1, len(text) // 4)


def _split_text(text: str, separators: list[str], chunk_size: int) -> list[str]:
    """Recursively split text respecting semantic boundaries."""
    if not text.strip():
        return []

    # Try each separator in order
    for sep in separators:
        if sep and sep in text:
            parts = text.split(sep)
            chunks: list[str] = []
            current = ""
            for part in parts:
                candidate = (current + sep + part).lstrip(sep) if current else part
                if _estimate_tokens(candidate) <= chunk_size:
                    current = candidate
                else:
                    if current.strip():
                        chunks.append(current.strip())
                    # part itself may be too large → recurse with next separator
                    if _estimate_tokens(part) > chunk_size:
                        remaining_seps = separators[separators.index(sep) + 1:]
                        chunks.extend(_split_text(part, remaining_seps, chunk_size))
                        current = ""
                    else:
                        current = part
            if current.strip():
                chunks.append(current.strip())
            if chunks:
                return chunks

    # No separator worked — hard-split by characters
    words = text.split()
    chunks = []
    current = ""
    for word in words:
        candidate = current + " " + word if current else word
        if _estimate_tokens(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks if chunks else [text[:chunk_size * 4]]


def _extract_page_number(text: str) -> int | None:
    """Extract [Page N] marker inserted by the text extractor."""
    m = re.search(r"\[Page (\d+)\]", text)
    return int(m.group(1)) if m else None


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 50,
    doc_id: str = "",
    kb_id: str = "",
    filename: str = "",
) -> list[TextChunk]:
    """
    Split text into overlapping chunks.

    Args:
        text:       Full document text (may contain [Page N] markers).
        chunk_size: Target chunk size in tokens.
        overlap:    Overlap between adjacent chunks in tokens.
        doc_id:     Parent document UUID.
        kb_id:      Parent knowledge-base UUID.
        filename:   Original file name (for citation).

    Returns:
        List of TextChunk objects with metadata.
    """
    if not text or not text.strip():
        return []

    raw_chunks = _split_text(text, _SEPARATORS, chunk_size)
    if not raw_chunks:
        return []

    # Apply overlap: prepend tail of previous chunk
    overlapped: list[str] = []
    for i, chunk in enumerate(raw_chunks):
        if i == 0 or overlap == 0:
            overlapped.append(chunk)
        else:
            prev = overlapped[-1]
            # Take last `overlap` tokens worth of chars from previous chunk
            tail = prev[-(overlap * 4):]
            overlapped.append((tail + " " + chunk).strip())

    result: list[TextChunk] = []
    pos = 0
    for i, content in enumerate(overlapped):
        if not content.strip():
            continue
        # Find approximate char_start in original text
        char_start = text.find(content[:40].strip(), pos)
        if char_start == -1:
            char_start = pos
        char_end = char_start + len(content)
        pos = max(pos, char_start + len(content) // 2)

        result.append(
            TextChunk(
                chunk_id=str(uuid.uuid4()),
                content=content,
                chunk_index=i,
                token_count=_estimate_tokens(content),
                page_number=_extract_page_number(content),
                char_start=char_start,
                char_end=char_end,
            )
        )

    return result
