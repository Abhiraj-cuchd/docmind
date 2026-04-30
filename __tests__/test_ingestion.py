# scripts/test_indexer.py
# Tests the full indexer pipeline on a local PDF
# Does NOT use SQS — calls the functions directly

import sys
import os
sys.path.insert(0, "lambdas")

from load_env import *

def test_indexer():
    print("\n=== Testing Indexer Pipeline ===")

    # ── Step 1: Test PDF extraction ────────────────────────────────
    print("\n--- Step 1: PDF Extraction ---")
    from ingestion_lambda.extractor import extract_text_from_pdf

    pdf_path = "scripts/test_data/sample.pdf"
    if not os.path.exists(pdf_path):
        print(f"❌ Test PDF not found at {pdf_path}")
        print("   Add any PDF to scripts/test_data/sample.pdf")
        return

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    result = extract_text_from_pdf(
        pdf_bytes=pdf_bytes,
        s3_key="uploads/test-user/test-doc/sample.pdf",
        filename="sample.pdf",
    )

    pages         = result["pages"]
    skipped       = result["skipped_pages"]
    doc_metadata  = result["document_metadata"]

    print(f"✅ Extracted {len(pages)} pages")
    print(f"✅ Skipped {len(skipped)} pages "
          f"(image-only): {[p['page_number'] for p in skipped]}")
    print(f"✅ Document metadata: {doc_metadata}")

    if pages:
        print(f"   First page preview: "
              f"'{pages[0]['text'][:100]}'...")

    # ── Step 2: Test chunking ──────────────────────────────────────
    print("\n--- Step 2: Chunking ---")
    from ingestion_lambda.chunker import chunk_pages

    chunks = chunk_pages(pages, chunk_size=500, chunk_overlap=50)
    print(f"✅ Created {len(chunks)} chunks")

    if chunks:
        sample = chunks[0]
        print(f"   First chunk ({len(sample['content'])} chars): "
              f"'{sample['content'][:100]}'...")
        print(f"   Metadata: {sample['metadata']}")

    # ── Step 3: Test embedding (real Voyage AI call) ───────────────
    print("\n--- Step 3: Embedding (Voyage AI) ---")
    print("   Embedding first 3 chunks only to conserve quota...")

    from ingestion_lambda.embedder import embed_chunks
    test_chunks = chunks[:3]

    embedded = embed_chunks(test_chunks)
    print(f"✅ Embedded {len(embedded)} chunks")
    print(f"   Embedding dimensions: {len(embedded[0]['embedding'])}")
    print(f"   First 5 values: {embedded[0]['embedding'][:5]}")

    assert len(embedded[0]['embedding']) == 1024, \
        f"Expected 1024 dims, got {len(embedded[0]['embedding'])}"
    print("✅ Embedding dimensions correct (1024)")

    print("\n✅ Indexer pipeline working end to end")
    print("\nNote: Full Supabase storage test requires a real user_id")
    print("Run test_full_flow.py after creating a test user")

if __name__ == "__main__":
    test_indexer()