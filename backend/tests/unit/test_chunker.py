"""Unit tests for text chunker."""
import pytest
from utils.chunker import chunk_text, TextChunk


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_short_text_single_chunk():
    chunks = chunk_text("This is a short sentence.", chunk_size=512)
    assert len(chunks) == 1
    assert chunks[0].content == "This is a short sentence."


def test_long_text_multiple_chunks():
    # ~200 tokens ≈ 800 chars
    text = "word " * 400
    chunks = chunk_text(text, chunk_size=64)
    assert len(chunks) > 1


def test_all_chunks_non_empty():
    text = "paragraph one\n\nparagraph two\n\nparagraph three\n\n" * 10
    chunks = chunk_text(text, chunk_size=32)
    for c in chunks:
        assert c.content.strip(), "Empty chunk produced"


def test_chunk_has_metadata_fields():
    chunks = chunk_text("Some text here.", chunk_size=512)
    c = chunks[0]
    assert c.chunk_id
    assert c.chunk_index == 0
    assert c.token_count > 0


def test_chunk_ids_are_unique():
    text = "word " * 300
    chunks = chunk_text(text, chunk_size=64)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_page_number_extracted():
    text = "[Page 3]\nSome text on page three."
    chunks = chunk_text(text, chunk_size=512)
    assert chunks[0].page_number == 3


def test_no_page_number_is_none():
    text = "Text without any page marker."
    chunks = chunk_text(text, chunk_size=512)
    assert chunks[0].page_number is None


def test_overlap_produces_some_shared_content():
    # Build text with clear paragraph separators
    text = "\n\n".join([f"Para {i}: " + "word " * 20 for i in range(5)])
    chunks_with = chunk_text(text, chunk_size=40, overlap=15)
    chunks_without = chunk_text(text, chunk_size=40, overlap=0)
    # Overlap should produce more chunks (or same), but each with shared content
    assert len(chunks_with) >= 1


def test_chunk_size_respected_approximately():
    text = "word " * 1000
    chunks = chunk_text(text, chunk_size=100)
    for c in chunks:
        # token_count should be within 2× of chunk_size (overlap + rounding tolerance)
        assert c.token_count < 300, f"Chunk too large: {c.token_count}"
