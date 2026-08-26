"""Unit tests for file upload validator."""
import pytest
from utils.file_validator import validate_upload


# ---- Valid uploads ----

def test_valid_pdf():
    content = b"%PDF-1.4 minimal content here"
    name, mime = validate_upload("report.pdf", content)
    assert mime == "application/pdf"
    assert name.endswith(".pdf")


def test_valid_txt():
    content = b"Hello, this is plain text."
    name, mime = validate_upload("notes.txt", content)
    assert mime == "text/plain"
    assert name.endswith(".txt")


def test_valid_csv():
    content = b"name,age\nAlice,30\nBob,25"
    name, mime = validate_upload("data.csv", content)
    assert mime == "text/csv"


def test_valid_docx():
    # DOCX starts with PK (ZIP magic bytes)
    pk_header = b"PK\x03\x04" + b"\x00" * 30
    name, mime = validate_upload("report.docx", pk_header)
    assert "wordprocessingml" in mime


def test_valid_png():
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    name, mime = validate_upload("image.png", png_header)
    assert mime == "image/png"


def test_valid_jpeg():
    jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 20
    name, mime = validate_upload("photo.jpg", jpeg_header)
    assert mime == "image/jpeg"


# ---- Filename sanitization ----

def test_path_traversal_stripped():
    content = b"%PDF-1.4 test"
    name, _ = validate_upload("../../etc/passwd.pdf", content)
    assert "/" not in name
    assert "\\" not in name
    assert name.endswith(".pdf")


def test_windows_path_traversal():
    content = b"%PDF-1.4 test"
    name, _ = validate_upload("..\\..\\windows\\system32\\evil.pdf", content)
    assert "\\" not in name


def test_special_chars_sanitized():
    content = b"plain text"
    name, _ = validate_upload("my file (1).txt", content)
    assert " " not in name
    assert "(" not in name


def test_empty_filename_gets_default():
    # An empty filename has no extension, so it should be rejected gracefully
    # (validator cannot determine allowed type without an extension)
    content = b"%PDF-1.4 content"
    with pytest.raises(ValueError):
        validate_upload("", content)


# ---- Rejections ----

def test_empty_file_rejected():
    with pytest.raises(ValueError, match="empty"):
        validate_upload("file.txt", b"")


def test_oversized_file_rejected():
    big = b"x" * (51 * 1024 * 1024)
    with pytest.raises(ValueError, match="exceeds"):
        validate_upload("big.txt", big)


def test_disallowed_extension_rejected():
    content = b"MZ\x90\x00"
    with pytest.raises(ValueError):
        validate_upload("malware.exe", content)


def test_extension_mismatch_rejected():
    # PDF magic bytes but .txt extension
    content = b"%PDF-1.4 content here"
    with pytest.raises(ValueError):
        validate_upload("bad.txt", content)
