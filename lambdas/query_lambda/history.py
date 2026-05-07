# lambdas/processor/history.py
#
# Responsibility: fetch recent chat history from Supabase
# and save new messages after generation completes.
#
# CONCEPT: Chat history gives Sarvam AI memory across turns.
# Without it every question is answered in isolation:
#   User: "Explain gradient descent"
#   Assistant: "Gradient descent is..."
#   User: "How does it relate to backprop?"  ← model has no context
#   Assistant: "What does 'it' refer to?"   ← frustrating UX
#
# With history (last 3 Q&A pairs injected into the prompt):
#   User: "How does it relate to backprop?"
#   Assistant: "Building on gradient descent we just discussed..."
#
# We limit to last 3 pairs (6 messages) because:
#   - 3 pairs covers "what did I just ask?" style follow-ups
#   - Each pair adds ~200-400 tokens to the prompt
#   - 3 pairs = 600-1200 extra tokens — within Sarvam's context window
#   - More pairs = diminishing returns + higher latency

from shared_lambda.supabase_client import get_service_client

# Number of Q&A pairs to include in history
HISTORY_PAIRS = 3


def fetch_conversation_history(
    conversation_id: str,
    user_id:         str,
) -> list[dict]:
    """
    Fetches the last HISTORY_PAIRS Q&A pairs from Supabase.
    Returns messages in chronological order (oldest first).

    Returns a list of dicts like:
    [
        {"role": "user",      "content": "What is gradient descent?"},
        {"role": "assistant", "content": "Gradient descent is..."},
        {"role": "user",      "content": "How does learning rate affect it?"},
        {"role": "assistant", "content": "The learning rate controls..."},
    ]
    """

    supabase = get_service_client()

    result = supabase \
        .schema("rag").table("messages") \
        .select("role, content") \
        .eq("conversation_id", conversation_id) \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(HISTORY_PAIRS * 2) \
        .execute()

    if not result.data:
        print(f"[History] No history found for "
              f"conversation {conversation_id}")
        return []

    # Reverse to get chronological order
    # CONCEPT: We fetch DESC (newest first) with LIMIT to get the
    # most recent N messages efficiently. Then reverse so the
    # prompt reads oldest → newest which is natural reading order.
    messages = list(reversed(result.data))

    print(f"[History] Loaded {len(messages)} messages "
          f"from conversation {conversation_id}")

    return messages


def save_user_message(
    conversation_id: str,
    user_id:         str,
    content:         str,
) -> None:
    """
    Saves the user's question to rag.messages.
    Called before generation so history is accurate
    even if generation fails.
    """

    supabase = get_service_client()

    supabase \
        .schema("rag").table("messages") \
        .insert({
            "conversation_id": conversation_id,
            "user_id":         user_id,
            "role":            "user",
            "content":         content,
            "voice_used":      False,
        }) \
        .execute()

    print(f"[History] Saved user message to "
          f"conversation {conversation_id}")


def save_assistant_message(
    conversation_id:  str,
    user_id:          str,
    content:          str,
    retrieved_chunks: list[dict] = None,
    voice_url:        str        = None,
    voice_used:       bool       = False,
) -> None:
    """
    Saves the assistant's answer to rag.messages.
    Called after generation completes successfully.

    CONCEPT: We store retrieved_chunks as JSONB so you can later
    audit exactly which document sections were used to generate
    each answer. This is invaluable for debugging retrieval quality:
    "Why did the model give a wrong answer?"
    → check retrieved_chunks → see what context it was given
    → was the right chunk retrieved? was retrieval the problem?
    """

    supabase = get_service_client()

    # Store only essential chunk info — not the full embedding
    # (embeddings are 1024 floats = large, no need to store again)
    chunks_for_storage = [
        {
            "id":          chunk.get("id"),
            "document_id": chunk.get("document_id"),
            "content":     chunk.get("content"),
            "page_number": chunk.get("metadata", {}).get("page_number"),
            "filename":    chunk.get("metadata", {}).get("filename"),
            "section":     chunk.get("metadata", {}).get("section"),
            "rrf_score":   chunk.get("rrf_score"),
        }
        for chunk in (retrieved_chunks or [])
    ]

    supabase \
        .schema("rag").table("messages") \
        .insert({
            "conversation_id":  conversation_id,
            "user_id":          user_id,
            "role":             "assistant",
            "content":          content,
            "retrieved_chunks": chunks_for_storage,
            "voice_url":        voice_url,
            "voice_used":       voice_used,
        }) \
        .execute()

    print(f"[History] Saved assistant message "
          f"({len(chunks_for_storage)} chunks stored) "
          f"to conversation {conversation_id}")


def update_conversation_timestamp(conversation_id: str) -> None:
    """
    Updates conversations.updated_at so the sidebar shows
    most recently active conversations at the top.

    CONCEPT: updated_at is how chat apps sort conversations —
    exactly like WhatsApp showing your most recent chat first.
    We update it after every completed Q&A exchange.
    """

    supabase = get_service_client()

    supabase \
        .schema("rag").table("conversations") \
        .update({"updated_at": "NOW()"}) \
        .eq("id", conversation_id) \
        .execute()