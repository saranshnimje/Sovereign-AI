"""Unit tests for text extraction — uses real small files created in-memory."""
import io
import os
import tempfile
import pytest


# ---- TXT ----

@pytest.mark.asyncio
async def test_extract_txt():
    from services.text_extractor import extract_text
    content = "Hello world!\nThis is a test document."
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
        f.write(content)
        path = f.name
    try:
        text, pages = await extract_text(path, "text/plain")
        assert "Hello world" in text
        assert pages == 1
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_extract_csv():
    from services.text_extractor import extract_text
    content = "name,value\nfoo,1\nbar,2\n"
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, encoding="utf-8") as f:
        f.write(content)
        path = f.name
    try:
        text, pages = await extract_text(path, "text/csv")
        assert "name" in text
        assert "foo" in text
        assert pages == 1
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_extract_pdf():
    """Create a minimal PDF with PyMuPDF and test extraction."""
    pytest.importorskip("fitz")
    import fitz
    from services.text_extractor import extract_text

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Test PDF content for extraction.", fontsize=12)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    doc.save(path)
    doc.close()

    try:
        text, pages = await extract_text(path, "application/pdf")
        assert "Test PDF" in text or len(text) > 0  # some text extracted
        assert pages >= 1
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_extract_docx():
    pytest.importorskip("docx")
    from docx import Document
    from services.text_extractor import extract_text
    import tempfile

    doc = Document()
    doc.add_paragraph("DOCX test paragraph one.")
    doc.add_paragraph("Second paragraph here.")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        path = f.name
    doc.save(path)

    try:
        text, pages = await extract_text(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert "DOCX test" in text
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_image_returns_empty_text():
    from services.text_extractor import extract_text
    # Images return empty text (OCR handles them separately)
    text, pages = await extract_text("/nonexistent/image.png", "image/png")
    assert text == ""
    assert pages == 1


@pytest.mark.asyncio
async def test_extraction_failure_raises():
    from services.text_extractor import extract_text, ExtractionError
    with pytest.raises(ExtractionError):
        await extract_text("/nonexistent/file.pdf", "application/pdf")
