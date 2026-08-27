# OCR Service Availability

## Status

**Implemented but unavailable** — OCR is fully wired into the document ingestion pipeline but PaddleOCR is not currently installed.

## Implementation

- **Service**: `backend/services/ocr_service.py`
- **Backend**: PaddleOCR (CPU mode)
- **Wiring**: `backend/services/document_service.py` calls `needs_ocr()` and `run_ocr()` during document ingestion
- **Graceful degradation**: When PaddleOCR is absent, scanned documents produce empty OCR text with INFO-level logging

## How It Works

1. On document upload, `needs_ocr()` checks if OCR is needed:
   - Images (PNG/JPEG/WEBP) always need OCR
   - PDFs need OCR only if extracted text is < 50 characters (likely scanned)
2. If OCR is needed and PaddleOCR is available, text is extracted via `run_ocr()`
3. If PaddleOCR is not installed, OCR is skipped and the document proceeds with whatever text was already extracted

## Enabling OCR

1. Uncomment these lines in `requirements.txt`:
   ```
   paddleocr>=2.7.0
   paddlepaddle>=2.5.0
   ```
2. Reinstall dependencies: `pip install -r requirements.txt`
3. Restart the backend — INFO log will confirm: `OCR service available (PaddleOCR initialized in CPU mode)`

## Size Impact

PaddleOCR + PaddlePaddle add approximately **2 GB** to the installation. This is why they remain optional.

## Impact on Normal Documents

None. Text-based PDFs and documents are never sent through OCR. The `needs_ocr()` function ensures only genuinely scanned/image documents trigger the OCR path.
