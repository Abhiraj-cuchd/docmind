# lambdas/ingestion_lambda/structure_detector.py
#
# Detects structural boundaries in extracted PDF pages before chunking.
# Produces Section objects that the chunker uses as hard split points.
#
# Why this exists:
#   RecursiveCharacterTextSplitter is pure character math — it has no
#   idea that a function definition or a section heading is starting.
#   Without structure detection, chunks routinely end mid-code-block,
#   mid-list, or mid-table-row. The LLM gets incoherent context.
#
# What it detects:
#   HEADING   — numbered sections, hash-style headings, ALL-CAPS titles,
#               short standalone lines followed by a blank line
#   CODE      — runs of lines with 4+ leading spaces, or lines with
#               language keywords (def, class, function, for, while, if)
#               that are consistently indented
#   LIST      — lines beginning with -, *, •, numbers + dot/paren
#   TABLE     — lines with multiple tab or pipe (|) separators
#   PROSE     — everything else

import re
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────
# DATA TYPES
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Section:
    heading:      str | None        # nearest detected heading, or None
    content_type: str               # prose | code | list | table
    text:         str               # raw section text
    page_number:  int               # page this section starts on
    section_id:   str               # stable ID: "p{page}s{index}"


# ─────────────────────────────────────────────────────────────────────
# REGEX PATTERNS
# ─────────────────────────────────────────────────────────────────────

_HEADING_PATTERNS = [
    # Numbered: "1.", "1.1", "1.1.2", "A.", "IV."
    re.compile(r'^(\d+\.)+\d*\s+\S', re.MULTILINE),
    re.compile(r'^[A-Z]{1,5}\.\s+\S', re.MULTILINE),
    # Hash-style markdown headings
    re.compile(r'^#{1,4}\s+\S', re.MULTILINE),
    # ALL-CAPS title (4+ chars, not a variable name)
    re.compile(r'^[A-Z][A-Z\s\-]{3,60}$', re.MULTILINE),
    # "Chapter X", "Section X", "Part X"
    re.compile(r'^(Chapter|Section|Part|Unit|Module|Lecture)\s+[\dIVXA-Z]', re.MULTILINE | re.IGNORECASE),
]

_CODE_KEYWORDS = re.compile(
    r'^\s*(def |class |function |public |private |void |int |float |bool |'
    r'return |import |from |#include |SELECT |INSERT |UPDATE |DELETE |'
    r'if\s*\(|for\s*\(|while\s*\(|switch\s*\()',
    re.MULTILINE,
)
_LEADING_SPACES = re.compile(r'^( {4}|\t)', re.MULTILINE)
_FENCE          = re.compile(r'^```', re.MULTILINE)

_LIST_LINE      = re.compile(r'^(\s*)([-*•]|\d+[.)]\s|[a-zA-Z][.)]\s)\S', re.MULTILINE)

_TABLE_LINE     = re.compile(r'^.*(\|.*){2,}', re.MULTILINE)
_TABLE_TAB      = re.compile(r'^[^\n]*\t[^\n]*\t[^\n]*', re.MULTILINE)


# ─────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────

def detect_sections(pages: list[dict]) -> list[Section]:
    """
    Analyses all pages and returns a flat list of Section objects
    in document order.

    Each section has a single dominant content_type and carries the
    nearest heading above it (or None if no heading precedes it).

    Called by chunker.py before splitting. The chunker iterates
    sections instead of raw page text, ensuring chunk boundaries
    align with structural boundaries.
    """
    all_sections: list[Section] = []
    current_heading: str | None  = None

    for page in pages:
        page_number = page["page_number"]
        page_text   = page["text"]

        sections = _split_page_into_sections(page_text, page_number)

        for sec in sections:
            # Propagate heading context: if this section IS a heading,
            # update the running heading for subsequent sections.
            if sec.content_type == "heading":
                current_heading = sec.heading
                # Merge heading section into the next prose/code block
                # by carrying the heading forward — don't emit a
                # standalone 1-2 line heading chunk.
                continue

            sec.heading = current_heading
            all_sections.append(sec)

    return all_sections


# ─────────────────────────────────────────────────────────────────────
# PRIVATE — PAGE SPLITTING
# ─────────────────────────────────────────────────────────────────────

def _split_page_into_sections(text: str, page_number: int) -> list[Section]:
    """
    Splits a single page's text into structural segments.
    Works line by line, grouping consecutive lines of the same type.
    """
    lines    = text.splitlines(keepends=True)
    sections: list[Section] = []
    buffer:  list[str]      = []
    cur_type: str           = "prose"
    sec_idx:  int           = 0
    in_fence: bool          = False   # inside a ``` code fence

    def _flush(t: str) -> None:
        nonlocal sec_idx
        raw = "".join(buffer).strip()
        if not raw:
            return
        heading = raw if t == "heading" else None
        sections.append(Section(
            heading=heading,
            content_type=t,
            text=raw,
            page_number=page_number,
            section_id=f"p{page_number}s{sec_idx}",
        ))
        sec_idx += 1
        buffer.clear()

    for line in lines:
        stripped = line.rstrip()

        # ── Code fence toggle ─────────────────────────────────────
        if _FENCE.match(stripped):
            if not in_fence:
                _flush(cur_type)
                cur_type = "code"
                in_fence = True
            else:
                in_fence = False
                _flush("code")
                cur_type = "prose"
            continue

        if in_fence:
            buffer.append(line)
            continue

        # ── Classify this line ────────────────────────────────────
        line_type = _classify_line(stripped)

        # ── State machine: flush when type changes ────────────────
        # Allow short prose lines (headings) to interrupt code/list
        if line_type != cur_type:
            # Don't split on a single blank line — absorb it
            if not stripped and len(buffer) > 0:
                buffer.append(line)
                continue
            _flush(cur_type)
            cur_type = line_type

        buffer.append(line)

    _flush(cur_type)
    return sections


def _classify_line(line: str) -> str:
    """
    Returns the structural type of a single line.
    Priority: heading > code > list > table > prose.
    """
    if not line.strip():
        return "prose"

    # Heading: short line matching a heading pattern
    if len(line.strip()) < 120:
        for pat in _HEADING_PATTERNS:
            if pat.match(line.strip()):
                return "heading"

    # Table: multiple pipes or tabs
    if _TABLE_LINE.match(line) or _TABLE_TAB.match(line):
        return "table"

    # Code: leading indentation or language keyword
    if _LEADING_SPACES.match(line) or _CODE_KEYWORDS.match(line):
        return "code"

    # List: bullet or numbered item
    if _LIST_LINE.match(line):
        return "list"

    return "prose"
