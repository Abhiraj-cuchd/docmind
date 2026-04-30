# lambdas/indexer/chunker.py
#
# Responsibility: split extracted pages into overlapping chunks.
# Each chunk is one unit that gets embedded and stored in Supabase.
#
# Receives: the "pages" list from extractor.py's return value
# Returns:  a flat list of chunks ready for embedder.py
#
# SQS context: this file sits between extractor.py and embedder.py
# in the pipeline. handler.py calls it after extraction completes.
#
# Input shape (one item from extractor.py's "pages" list):
# {
#     "page_number": 4,
#     "text":        "Support Vector Machines work by finding...",
#     "char_count":  1842,
#     "metadata": {
#         "filename":    "lecture_notes.pdf",
#         "s3_key":      "uploads/.../lecture_notes.pdf",
#         "page_number": 4,
#         "total_pages": 52,
#         "has_images":  False,
#         "has_tables":  True,
#     }
# }
#
# Output shape (one chunk ready for embedder.py):
# {
#     "content":  "Support Vector Machines work by finding the optimal...",
#     "metadata": {
#         "filename":    "lecture_notes.pdf",
#         "s3_key":      "uploads/.../lecture_notes.pdf",
#         "page_number": 4,
#         "total_pages": 52,
#         "has_images":  False,
#         "has_tables":  True,
#         "chunk_index": 7,
#         "chunk_on_page": 2,
#         "char_start":  500,
#         "char_end":    1000,
#         "char_count":  500,
#     }
# }

from langchain.text_splitter import RecursiveCharacterTextSplitter


def chunk_pages(
    pages:         list[dict],
    chunk_size:    int = 400,
    chunk_overlap: int = 100,
) -> list[dict]:
    """
    Splits all extracted pages into overlapping chunks.

    Parameters:
        pages         — the "pages" list from extractor.py
        chunk_size    — target size of each chunk in characters
        chunk_overlap — how many characters consecutive chunks share

    Returns a flat list of chunk dicts ordered by page then
    position within page. This order is preserved into Supabase
    so chunk_index reflects true document order.

    CONCEPT: Why 500 characters and 50 overlap?
    From your Phase 1 experiments in CLAUDE.md:
      chunk_size=200  → loses context across boundaries
      chunk_size=1000 → too much noise per chunk
      chunk_size=500  → best default for lecture-note style PDFs
      overlap=50      → enough to bridge boundary sentences
    These aren't arbitrary — they came from your own measurements.

    CONCEPT: Why RecursiveCharacterTextSplitter over simple slicing?
    Simple slicing cuts at exactly 500 characters regardless of
    where a sentence or paragraph ends:
      "...the gradient descent algorithm converges when the loss
      fu" ← cuts mid-word. Next chunk starts "nction reaches..."
    RecursiveCharacterTextSplitter tries separators in priority order:
      1. paragraph break (\\n\\n) — best split point
      2. line break (\\n)         — good split point
      3. space ( )                — acceptable split point
      4. character               — last resort
    So chunks end at natural language boundaries whenever possible.
    This means the LLM receives coherent text, not truncated sentences.
    """

    # CONCEPT: We initialise the splitter once outside the loop.
    # RecursiveCharacterTextSplitter is stateless — same instance
    # can split any number of texts without interference.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        # Separators tried in order — paragraph first, then line,
        # then word, then character. The splitter stops at the
        # first separator that produces a chunk within chunk_size.
        separators=["\n\n", "\n", " ", ""],
        # CONCEPT: length_function tells the splitter how to measure
        # chunk size. len() counts characters, not tokens.
        # Character counting is consistent across all text —
        # token counting varies by model and adds a dependency.
        # At chunk_size=500 chars, you get roughly 100-150 tokens
        # which is well within Voyage AI's 4096 token limit.
        length_function=len,
    )

    all_chunks  = []
    chunk_index = 0   # global index across the entire document

    for page in pages:
        page_number = page["page_number"]
        text        = page["text"]
        page_meta   = page["metadata"]   # already built by extractor.py

        # Split this page's text into chunks
        # CONCEPT: split_text() returns a list of strings.
        # Each string is one chunk — already trimmed, already within
        # chunk_size characters, already respecting natural boundaries.
        raw_chunks = splitter.split_text(text)

        if not raw_chunks:
            print(f"[Chunker] Page {page_number}: no chunks produced "
                  f"(text may be too short)")
            continue

        for chunk_on_page, chunk_text in enumerate(raw_chunks):

            # Skip empty or whitespace-only chunks
            # (can happen on pages with lots of whitespace)
            if not chunk_text.strip():
                continue

            cleaned_text = chunk_text.strip()

            # Find where this chunk sits in the original page text.
            # CONCEPT: We store char_start and char_end so you can
            # later highlight the exact passage in the original PDF
            # if you ever build a "show source" feature in the frontend.
            char_start = text.find(cleaned_text)
            char_end   = char_start + len(cleaned_text) if char_start != -1 else -1

            # Build chunk metadata by extending the page metadata.
            # CONCEPT: We copy page_meta so every chunk knows which
            # file and page it came from. Then we add chunk-specific
            # fields on top. This means the LLM context window will
            # always know the provenance of every retrieved chunk.
            chunk_metadata = {
                **page_meta,           # inherit all page-level metadata
                "chunk_index":    chunk_index,     # position in whole document
                "chunk_on_page":  chunk_on_page,   # position on this page
                "char_start":     char_start,       # character offset in page
                "char_end":       char_end,         # character offset in page
                "char_count":     len(cleaned_text),
            }

            all_chunks.append({
                "content":  cleaned_text,
                "metadata": chunk_metadata,
            })

            chunk_index += 1

        print(f"[Chunker] Page {page_number:3d}: "
              f"{len(raw_chunks)} chunks produced")

    # ── Summary ───────────────────────────────────────────────────
    if not all_chunks:
        raise ValueError(
            "Chunking produced zero chunks. "
            "The extracted text may be empty or too short."
        )

    total_chars = sum(c["metadata"]["char_count"] for c in all_chunks)
    avg_chars   = total_chars // len(all_chunks)

    print(f"[Chunker] Complete: {len(all_chunks)} chunks total, "
          f"avg {avg_chars} chars/chunk, "
          f"chunk_size={chunk_size}, overlap={chunk_overlap}")

    return all_chunks