# lambdas/ingestion_lambda/chunker.py
#
# Section-aware, cross-page document chunker.
#
# Processing order:
#   1. structure_detector.detect_sections(pages)
#        → flat list of Section objects (prose/code/list/table)
#        → headings consumed and attached to the section below them
#   2. For each section, pick a splitter based on content_type:
#        prose/list/table → RecursiveCharacterTextSplitter (paragraph-first)
#        code             → RecursiveCharacterTextSplitter (function-first)
#   3. Hard boundary at every section edge — no overlap bleeds across sections
#   4. Continuation bridge: if the first sentence of a section starts
#        with a lowercase letter (likely a mid-sentence page break), prepend
#        the last sentence of the previous chunk as a 1-sentence bridge
#   5. Each chunk prefixed with "[Page N][Section: heading]" for BM25
#   6. Metadata: page_number, page_number_end, pages[], heading,
#        section_id, content_type, chunk_index
#
# For windowed ingestion (large documents), chunk_pages() accepts an
# optional `global_chunk_offset` so chunk_index stays globally monotonic
# across windows.

import re
from dataclasses import dataclass
from langchain.text_splitter import RecursiveCharacterTextSplitter
from structure_detector import detect_sections, Section

# ── Splitter configs ──────────────────────────────────────────────────

_PROSE_SPLITTER_ARGS = dict(
    separators   = ["\n\n", "\n", ". ", " ", ""],
    length_function = len,
    add_start_index = True,
)

_CODE_SPLITTER_ARGS = dict(
    # Keep function/class definitions together before splitting on newlines
    separators   = ["\nclass ", "\ndef ", "\n\n", "\n", " ", ""],
    length_function = len,
    add_start_index = True,
)

_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')


def chunk_pages(
    pages:              list[dict],
    chunk_size:         int = 600,
    chunk_overlap:      int = 150,
    global_chunk_offset: int = 0,
) -> list[dict]:
    """
    Splits pages into semantically coherent chunks respecting structure.

    Parameters
    ----------
    pages               extractor.py "pages" list
    chunk_size          target chars per chunk
    chunk_overlap       overlap within a section (not across sections)
    global_chunk_offset add this to chunk_index (for windowed ingestion)

    Returns a flat list of chunk dicts ordered by document position.
    """
    sections = detect_sections(pages)

    if not sections:
        raise ValueError("Structure detector produced no sections — text may be empty.")

    prose_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        **_PROSE_SPLITTER_ARGS,
    )
    code_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=0,   # no overlap for code
        **_CODE_SPLITTER_ARGS,
    )

    all_chunks:    list[dict] = []
    chunk_index:   int        = global_chunk_offset
    last_sentence: str | None = None  # continuation bridge state

    for sec in sections:
        splitter = code_splitter if sec.content_type == "code" else prose_splitter
        docs     = splitter.create_documents([sec.text])

        for doc_idx, doc in enumerate(docs):
            raw_text = doc.page_content.strip()
            if not raw_text:
                continue

            # ── Continuation bridge ───────────────────────────────
            # If this chunk's first word starts lowercase and we have
            # a previous sentence, it's likely a mid-sentence page break.
            # Prepend the last sentence for coherent context.
            first_word = raw_text.lstrip()[0] if raw_text.lstrip() else ""
            if (
                doc_idx == 0
                and last_sentence
                and first_word.islower()
                and sec.content_type == "prose"
            ):
                raw_text = f"{last_sentence} {raw_text}"

            # ── BM25-friendly prefix ──────────────────────────────
            prefix_parts = [f"[Page {sec.page_number}]"]
            if sec.heading:
                prefix_parts.append(f"[Section: {sec.heading}]")
            prefix   = " ".join(prefix_parts)
            content  = f"{prefix}\n{raw_text}"

            # ── Page span ─────────────────────────────────────────
            # Approximate: the section starts on sec.page_number.
            # Cross-page spans are resolved at the window level by the
            # ingestion handler which tracks actual page boundaries.
            all_chunks.append({
                "content": content,
                "metadata": {
                    "page_number":     sec.page_number,
                    "page_number_end": sec.page_number,
                    "pages":           [sec.page_number],
                    "heading":         sec.heading,
                    "section_id":      sec.section_id,
                    "content_type":    sec.content_type,
                    "chunk_index":     chunk_index,
                    "char_count":      len(content),
                },
            })
            chunk_index += 1

            # Update last_sentence for next section's bridge check
            sentences = _SENTENCE_END.split(raw_text)
            last_sentence = sentences[-1].strip() if sentences else None

    if not all_chunks:
        raise ValueError("Chunking produced zero chunks.")

    cross_section = 0  # future: count cross-section bridges
    print(
        f"[Chunker] {len(all_chunks)} chunks, "
        f"chunk_size={chunk_size}, overlap={chunk_overlap}, "
        f"sections={len(sections)}"
    )
    return all_chunks
