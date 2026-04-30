# lambdas/indexer/extractor.py
#
# Responsibility: download a PDF from S3 and extract text page by page.
# Uses PyMuPDF (fitz) as the extraction engine.
#
# Returns a structured result containing:
#   - extracted pages with text and rich metadata
#   - skipped pages (image-only or scanned) with reason
#   - document-level summary metadata
#
# SQS context: this file is called by handler.py which is triggered
# by SQS. The s3_bucket and s3_key passed into these functions come
# directly from the SQS message body, which was populated by the
# S3 PUT event notification.

import boto3
import fitz        # PyMuPDF — pip install pymupdf
import os
from datetime   import datetime, timezone

# ── S3 client (module-level singleton) ───────────────────────────────
# CONCEPT: Initialised once at module load time, reused across
# warm Lambda invocations. Avoids the ~50ms connection overhead
# on every request. boto3 clients are thread-safe.
s3_client = boto3.client(
    "s3",
    region_name=os.getenv("AWS_REGION", "ap-south-1")
)

# ── Constants ─────────────────────────────────────────────────────────
# CONCEPT: Pages with fewer than this many characters after extraction
# are almost certainly image-only or scanned pages. A real text page
# will always have more than 50 meaningful characters.
MIN_CHARS_FOR_TEXT_PAGE = 50


# ─────────────────────────────────────────────────────────────────────
# PUBLIC FUNCTIONS — called by handler.py
# ─────────────────────────────────────────────────────────────────────

def download_pdf_from_s3(bucket: str, key: str) -> bytes:
    """
    Downloads a PDF from S3 and returns its raw bytes.

    Called by handler.py with the bucket and key extracted from
    the SQS message. The SQS message looks like this:
    {
        "Records": [{
            "s3": {
                "bucket": {"name": "rag-mvp-pdfs"},
                "object": {"key": "uploads/user-uuid/doc-uuid/file.pdf"}
            }
        }]
    }

    CONCEPT: We read the entire PDF into memory (BytesIO pattern).
    For typical research PDFs and lecture notes (1–20MB) this is
    perfectly fine. Lambda has 512MB–10GB memory depending on config.
    We set the indexer Lambda to 512MB which comfortably handles
    PDFs up to ~100MB.
    """

    print(f"[S3] Downloading s3://{bucket}/{key}")

    response  = s3_client.get_object(Bucket=bucket, Key=key)
    pdf_bytes = response["Body"].read()
    file_size_kb = len(pdf_bytes) / 1024

    print(f"[S3] Downloaded {file_size_kb:.1f} KB")
    return pdf_bytes


def extract_text_from_pdf(
    pdf_bytes:  bytes,
    s3_key:     str,
    filename:   str,
) -> dict:
    """
    Extracts text from all pages of a PDF using PyMuPDF.

    Parameters:
        pdf_bytes  — raw PDF bytes from download_pdf_from_s3()
        s3_key     — the full S3 key e.g. uploads/user-id/doc-id/file.pdf
                     stored in metadata so chunks can reference their source
        filename   — original filename e.g. "lecture_notes.pdf"
                     shown to the user in the frontend

    Returns a dict with this shape:
    {
        "document_metadata": {
            "filename":          "lecture_notes.pdf",
            "s3_key":            "uploads/.../lecture_notes.pdf",
            "total_pages":       52,
            "extracted_pages":   48,
            "skipped_pages":     [12, 23, 31, 45],
            "skipped_count":     4,
            "extraction_method": "pymupdf",
            "extracted_at":      "2026-04-27T10:30:00Z",
            "file_size_bytes":   1048576,
        },
        "pages": [
            {
                "page_number":  1,
                "text":         "Introduction to Machine Learning...",
                "char_count":   1842,
                "metadata": {
                    "filename":    "lecture_notes.pdf",
                    "s3_key":      "uploads/.../lecture_notes.pdf",
                    "page_number": 1,
                    "total_pages": 52,
                    "has_images":  False,
                    "has_tables":  True,
                }
            },
            ...
        ],
        "skipped_pages": [
            {
                "page_number": 12,
                "reason":      "image_only",
                "char_count":  0,
            },
            ...
        ]
    }

    CONCEPT: We return a rich structured dict rather than a simple
    list of strings. This gives handler.py everything it needs:
    - pages → passed to chunker.py
    - document_metadata → stored in rag.documents
    - skipped_pages → stored in rag.documents, shown in frontend
    """

    print(f"[Extractor] Opening PDF: {filename}")

    # CONCEPT: fitz.open() with stream= reads from bytes in memory.
    # filetype="pdf" tells PyMuPDF the format explicitly —
    # without it PyMuPDF sniffs the format from the bytes which
    # adds a tiny overhead and can occasionally misidentify files.
    pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages  = len(pdf_document)

    print(f"[Extractor] PDF has {total_pages} pages")

    extracted_pages = []
    skipped_pages   = []

    for page_index in range(total_pages):
        page        = pdf_document[page_index]
        page_number = page_index + 1   # human-readable (1-based)

        # ── Extract text ──────────────────────────────────────────
        # CONCEPT: get_text("text") extracts the text layer in
        # reading order. PyMuPDF determines reading order by sorting
        # text blocks using their (x, y) coordinates on the page —
        # top to bottom, left to right. This correctly handles:
        #   - Multi-column academic papers
        #   - Sidebars and callout boxes
        #   - Mixed text and image pages (text extracted, images skipped)
        #   - Headers and footers (included — chunker handles them)
        text = page.get_text("text").strip()

        # ── Detect page characteristics ───────────────────────────
        # CONCEPT: get_images() returns a list of image objects
        # embedded in this page. We use this purely as metadata —
        # to tell the user "this page contains images" in the frontend.
        # We do NOT extract or process the images themselves.
        page_images = page.get_images(full=False)
        has_images  = len(page_images) > 0

        # CONCEPT: Simple table detection — if the page text contains
        # multiple tab characters or consecutive spaces in patterns
        # typical of table rows, flag it. This is a heuristic,
        # not a guarantee. Stored as metadata for debugging.
        has_tables = "\t" in text or "    " in text

        # ── Classify page ─────────────────────────────────────────
        if len(text) >= MIN_CHARS_FOR_TEXT_PAGE:

            # Good text page — include it
            extracted_pages.append({
                "page_number": page_number,
                "text":        text,
                "char_count":  len(text),

                # CONCEPT: Per-page metadata gets attached to every
                # chunk that comes from this page (done in chunker.py).
                # This is what lets the frontend show:
                # "Answer sourced from page 4 of lecture_notes.pdf"
                # storing s3_key lets you regenerate a presigned URL
                # to the original PDF if you ever want to show context.
                "metadata": {
                    "filename":    filename,
                    "s3_key":      s3_key,
                    "page_number": page_number,
                    "total_pages": total_pages,
                    "has_images":  has_images,
                    "has_tables":  has_tables,
                }
            })

            print(f"[Extractor] Page {page_number:3d}: "
                  f"{len(text):5d} chars "
                  f"{'[images]' if has_images else ''}"
                  f"{'[tables]' if has_tables else ''}")

        else:
            # Scanned or image-only page — skip but record it
            reason = "image_only" if has_images else "no_text_layer"

            skipped_pages.append({
                "page_number": page_number,
                "reason":      reason,
                "char_count":  len(text),
            })

            print(f"[Extractor] Page {page_number:3d}: SKIPPED "
                  f"({reason}, {len(text)} chars)")

    pdf_document.close()

    # ── Validation ────────────────────────────────────────────────
    if not extracted_pages:
        raise ValueError(
            f"No extractable text found in '{filename}'. "
            f"This PDF appears to be fully scanned or image-based. "
            f"Please upload a PDF with a text layer."
        )

    # ── Build document-level summary metadata ─────────────────────
    # CONCEPT: This summary is stored in rag.documents so the
    # frontend can display a rich status card for each uploaded PDF:
    #   ✅ lecture_notes.pdf — 48 pages indexed
    #   ⚠️  Pages 12, 23, 31, 45 contain only images and were skipped
    document_metadata = {
        "filename":          filename,
        "s3_key":            s3_key,
        "total_pages":       total_pages,
        "extracted_pages":   len(extracted_pages),
        "skipped_pages":     [p["page_number"] for p in skipped_pages],
        "skipped_count":     len(skipped_pages),
        "extraction_method": "pymupdf",
        "extracted_at":      datetime.now(timezone.utc).isoformat(),
        "file_size_bytes":   len(pdf_bytes),
    }

    # ── Summary log ───────────────────────────────────────────────
    print(f"[Extractor] Complete: "
          f"{len(extracted_pages)} pages extracted, "
          f"{len(skipped_pages)} skipped")

    if skipped_pages:
        skipped_nums = [p["page_number"] for p in skipped_pages]
        print(f"[Extractor] Skipped pages: {skipped_nums}")
        print(f"[Extractor] Note: skipped pages contain images/diagrams "
              f"and will not be searchable")

    return {
        "document_metadata": document_metadata,
        "pages":             extracted_pages,
        "skipped_pages":     skipped_pages,
    }