import json
from shared_lambda.supabase_client import get_service_client
from shared_lambda.rate_limiter    import acquire_nvidia_token
from shared_lambda                 import summarizer_llm

# Chars below which we stuff all chunks into a single call (~50k tokens,
# safely within Nemotron's 128k context window).
STUFF_THRESHOLD = 200_000

# Max chars per map-reduce batch (~4k tokens each — keeps batches fast).
BATCH_CHARS = 15_000

# Hard cap on chunks processed in v1 (guards against runaway map-reduce cost).
MAX_CHUNKS = 500


# ── Conversation summary ───────────────────────────────────────────────

def summarize_conversation(
    job_id:          str,
    user_id:         str,
    conversation_id: str,
    r,
) -> None:
    from generation_lambda.handler import _write_result

    if not conversation_id:
        _write_result(r, job_id, {"status": "error", "message": "conversation_id is required"})
        return

    supabase = get_service_client()

    # Fetch all messages in chronological order — no LIMIT unlike history.py
    result = supabase.schema("rag").table("messages") \
        .select("role, content") \
        .eq("conversation_id", conversation_id) \
        .eq("user_id", user_id) \
        .order("created_at", desc=False) \
        .execute()

    messages = result.data or []

    if not messages:
        _write_result(r, job_id, {
            "status":  "error",
            "message": "Conversation has no messages to summarize",
        })
        return

    transcript = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in messages
    )

    print(f"[Summarize] conversation={conversation_id}: "
          f"{len(messages)} messages, {len(transcript)} chars")

    acquired = acquire_nvidia_token(r)
    if not acquired:
        raise Exception("RATE_LIMIT_WAIT")

    summary = summarizer_llm.generate([
        {
            "role":    "system",
            "content": (
                "Summarize the following conversation in 3-5 sentences. "
                "Capture the main topics discussed and any conclusions reached. "
                "Be concise and factual."
            ),
        },
        {
            "role":    "user",
            "content": transcript,
        },
    ])

    _persist_conversation_summary(supabase, user_id, conversation_id, summary)

    _write_result(r, job_id, {
        "status":  "done",
        "summary": summary,
    })

    print(f"[Summarize] conversation={conversation_id} done ({len(summary)} chars)")


def _persist_conversation_summary(supabase, user_id, conversation_id, summary):
    # Upsert into rag.summaries — latest summary wins on re-generate
    supabase.schema("rag").table("summaries").upsert(
        {
            "user_id":         user_id,
            "source_type":     "conversation",
            "conversation_id": conversation_id,
            "document_id":     None,
            "content":         summary,
        },
        on_conflict="user_id,source_type,conversation_id,document_id",
    ).execute()

    # Also populate conversations.summary for quick UI display without a join
    supabase.schema("rag").table("conversations") \
        .update({"summary": summary}) \
        .eq("id", conversation_id) \
        .eq("user_id", user_id) \
        .execute()

    print(f"[Summarize] Persisted summary for conversation={conversation_id}")


# ── Document summary ───────────────────────────────────────────────────

def summarize_document(
    job_id:      str,
    user_id:     str,
    document_id: str,
    r,
) -> None:
    from generation_lambda.handler import _write_result

    if not document_id:
        _write_result(r, job_id, {"status": "error", "message": "document_id is required"})
        return

    supabase = get_service_client()

    # Gate on document belonging to user and being ready
    doc_result = supabase.schema("rag").table("documents") \
        .select("id, filename, status") \
        .eq("id", document_id) \
        .eq("user_id", user_id) \
        .single() \
        .execute()

    if not doc_result.data:
        _write_result(r, job_id, {"status": "error", "message": "Document not found"})
        return

    doc = doc_result.data
    if doc["status"] != "ready":
        _write_result(r, job_id, {
            "status":  "error",
            "message": f"Document is not ready (status: {doc['status']})",
        })
        return

    # Fetch chunks ordered by chunk_index, capped at MAX_CHUNKS
    chunks_result = supabase.schema("rag").table("chunks") \
        .select("content, metadata") \
        .eq("document_id", document_id) \
        .eq("user_id", user_id) \
        .order("metadata->>chunk_index") \
        .limit(MAX_CHUNKS) \
        .execute()

    chunks = chunks_result.data or []

    if not chunks:
        _write_result(r, job_id, {
            "status":  "error",
            "message": "Document has no chunks — re-index may be needed",
        })
        return

    total_chars = sum(len(c["content"]) for c in chunks)
    filename    = doc["filename"]

    print(f"[Summarize] document={document_id} ({filename}): "
          f"{len(chunks)} chunks, {total_chars} chars")

    if total_chars < STUFF_THRESHOLD:
        summary, strategy = _stuff_summarize(chunks, filename, r)
    else:
        summary, strategy = _map_reduce_summarize(chunks, filename, r)

    _persist_document_summary(supabase, user_id, document_id, summary)

    _write_result(r, job_id, {
        "status":   "done",
        "summary":  summary,
        "strategy": strategy,
    })

    print(f"[Summarize] document={document_id} done "
          f"(strategy={strategy}, {len(summary)} chars)")


def _stuff_summarize(chunks: list[dict], filename: str, r) -> tuple[str, str]:
    content_block = "\n\n".join(c["content"] for c in chunks)

    acquired = acquire_nvidia_token(r)
    if not acquired:
        raise Exception("RATE_LIMIT_WAIT")

    summary = summarizer_llm.generate([
        {
            "role":    "system",
            "content": (
                "Summarize the following document in clear, structured paragraphs. "
                "Cover the main topics, key findings, and any conclusions. "
                "Be thorough but concise."
            ),
        },
        {
            "role":    "user",
            "content": f"Document: {filename}\n\n{content_block}",
        },
    ], max_tokens=1024)

    return summary, "stuff"


def _map_reduce_summarize(chunks: list[dict], filename: str, r) -> tuple[str, str]:
    # ── Map phase: summarize each batch ───────────────────────────────
    batches  = _make_batches(chunks, BATCH_CHARS)
    partials = []

    print(f"[Summarize] map-reduce: {len(batches)} batches for {filename}")

    for i, batch in enumerate(batches):
        acquired = acquire_nvidia_token(r)
        if not acquired:
            raise Exception("RATE_LIMIT_WAIT")

        batch_text = "\n\n".join(c["content"] for c in batch)
        partial    = summarizer_llm.generate([
            {
                "role":    "system",
                "content": (
                    "Summarize the following excerpt in 3-5 sentences. "
                    "Focus on the key information presented."
                ),
            },
            {
                "role":    "user",
                "content": f"Excerpt {i + 1}/{len(batches)} from {filename}:\n\n{batch_text}",
            },
        ], max_tokens=512)

        partials.append(partial)
        print(f"[Summarize] map batch {i + 1}/{len(batches)} done")

    # ── Reduce phase: combine partial summaries ────────────────────────
    combined = "\n\n".join(f"Part {i + 1}: {p}" for i, p in enumerate(partials))

    acquired = acquire_nvidia_token(r)
    if not acquired:
        raise Exception("RATE_LIMIT_WAIT")

    summary = summarizer_llm.generate([
        {
            "role":    "system",
            "content": (
                "You are given partial summaries of different sections of a document. "
                "Combine them into a single coherent summary covering the full document. "
                "Do not repeat information — synthesize it into clear paragraphs."
            ),
        },
        {
            "role":    "user",
            "content": f"Document: {filename}\n\nPartial summaries:\n\n{combined}",
        },
    ], max_tokens=1024)

    return summary, "map_reduce"


def _make_batches(chunks: list[dict], max_chars: int) -> list[list[dict]]:
    batches, current, current_chars = [], [], 0

    for chunk in chunks:
        chunk_len = len(chunk["content"])
        if current and current_chars + chunk_len > max_chars:
            batches.append(current)
            current, current_chars = [], 0
        current.append(chunk)
        current_chars += chunk_len

    if current:
        batches.append(current)

    return batches


def _persist_document_summary(supabase, user_id, document_id, summary):
    supabase.schema("rag").table("summaries").upsert(
        {
            "user_id":         user_id,
            "source_type":     "document",
            "conversation_id": None,
            "document_id":     document_id,
            "content":         summary,
        },
        on_conflict="user_id,source_type,conversation_id,document_id",
    ).execute()

    print(f"[Summarize] Persisted summary for document={document_id}")
