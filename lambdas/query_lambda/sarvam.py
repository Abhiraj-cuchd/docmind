# lambdas/processor/sarvam.py
#
# Responsibility: all Sarvam AI LLM interactions.
# Every call to Sarvam AI in the processor goes through this file.
#
# Functions exposed:
#   generate_answer()  → main RAG answer generation
#   direct_answer()    → answer without retrieval (factual questions)
#
# CONCEPT: We centralise all Sarvam calls here so:
#   - Retry logic is written once, not in every handler
#   - Think tag stripping is written once
#   - Rate limit handling is consistent across all call types
#   - Easy to swap Sarvam for another LLM later

import requests
import time
import re
from shared_lambda.secrets import get_secret

SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_MODEL   = "sarvam-105b"

MAX_RETRIES    = 3
RETRY_DELAY    = 2

STYLE_INSTRUCTIONS = {
    "concise": (
        "Write a short answer in 3-5 lines.\n"
        "No bullets, no sections, no extra explanation.\n"
        "Only include the most important information."
    ),
    "explanatory": (
        "You MUST follow this exact structure:\n"
        "Answer:<1-2 line direct answer>\n"
        "Explanation:\n"
        "- What it is: <1-2 lines>\n"
        "- How it works: <2-3 lines>\n"
        "- Why it matters: <1-2 lines>\n"
        "Rules:\n"
        "- Always include all three sections\n"
        "- Keep explanations concise but clear\n"
        "- Do not skip sections\n"
        "- Do not write long paragraphs"
    ),
    "conversational": (
        "Explain like you're talking to a friend.\n"
        "- Use simple language\n"
        "- Use analogies if helpful\n"
        "- Avoid structured sections\n"
        "- Keep it natural and easy to follow"
    ),
}


def generate_answer(
    query:          str,
    context_chunks: list[dict],
    history:        list[dict],
    style:          str = "explanatory",
) -> str:
    """
    Generates a RAG answer from retrieved context chunks.
    This is the main generation call — called after HyDE + RRF + MMR.

    Parameters:
        query          — the user's original question
        context_chunks — top-k chunks from MMR (each has 'content' key)
        history        — last N message dicts from history.py

    Returns the final answer string with think tags stripped.

    CONCEPT: We pass context chunks as a formatted block and
    instruct Sarvam to answer ONLY from that context. This is
    the core RAG constraint — the model should not hallucinate
    information that isn't in the retrieved chunks.
    """

    prompt = _build_rag_prompt(query, context_chunks, history, style)

    print(f"[Sarvam] Generating RAG answer for: '{query[:80]}'")
    print(f"[Sarvam] Context: {len(context_chunks)} chunks, "
          f"History: {len(history)} messages")

    raw_response = _call_sarvam(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=0.5,
    )

    answer = _strip_think_tags(raw_response)

    print(f"[Sarvam] Answer generated ({len(answer)} chars)")
    return answer


def direct_answer(query: str, history: list[dict], style: str = "explanatory") -> str:
    """
    Generates an answer directly without retrieved context.
    Used when the query is a general knowledge question that
    doesn't need document retrieval — e.g. "what is 2 + 2?"
    or "summarise our last conversation".

    CONCEPT: Not every question needs RAG. Simple factual queries,
    greetings, and follow-ups about the conversation itself can
    be answered directly from the LLM's parametric knowledge.
    Calling retrieval for these wastes Voyage AI calls and
    adds unnecessary latency.
    """

    print(f"[Sarvam] Generating direct answer for: '{query[:80]}'")

    prompt = _build_direct_prompt(query, history, style)

    raw_response = _call_sarvam(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.5,
    )

    answer = _strip_think_tags(raw_response)
    print(f"[Sarvam] Direct answer generated ({len(answer)} chars)")
    return answer



def rewrite_query(query: str, history: list[dict]) -> str:
    if not history:
        return query

    # --- Normalize words ---
    words = set(re.findall(r"\b\w+\b", query.lower()))

    pronouns = {
        "it", "this", "that", "they", "them", "its",
        "these", "those", "he", "she",
    }

    vague_patterns = {"how", "why", "explain", "what", "tell"}

    is_short = len(query.split()) <= 10
    has_pronoun = bool(words & pronouns)
    is_vague = any(word in words for word in vague_patterns)

    # --- Skip unnecessary rewrites ---
    if not (is_short or has_pronoun or is_vague):
        return query

    # --- Limit history (token optimization) ---
    history = history[-3:]
    history_text = _format_history(history)

    prompt = (
        "Rewrite the query into a complete, standalone search query.\n"
        "Resolve references using history. Keep meaning same.\n"
        "Output only the query.\n\n"
        f"{history_text}\n"
        f"Query: {query}\n"
        "Rewritten:"
    )

    raw = _call_sarvam(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=80,
        temperature=0.0,
    )

    rewritten = _strip_think_tags(raw).strip()

    # --- Safety fallback ---
    if not rewritten or len(rewritten) > 200:
        return query

    print(f"[Rewrite] '{query[:50]}' -> '{rewritten[:50]}'")

    return rewritten
# lambdas/query_lambda/sarvam.py
# Fix needs_retrieval() — search for YES/NO in full response
# including inside think tags

def needs_retrieval(query: str) -> bool:
    print(f"[Sarvam] Checking if retrieval needed for: '{query[:80]}'")

    prompt = (
        "Does the following question require searching through "
        "uploaded documents to answer correctly?\n\n"
        "Answer YES if the question mentions 'my document', 'my PDF', "
        "'my notes', asks to summarise uploaded content, or references "
        "specific document content.\n"
        "Answer NO only for pure math, pure general knowledge, or greetings.\n\n"
        "Answer with only YES or NO.\n\n"
        f"Question: {query}\n\nAnswer:"
    )

    raw = _call_sarvam(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=0.0,
    )

    # CONCEPT: Sarvam-m writes its reasoning inside <think> tags then
    # outputs YES or NO after </think>. At low max_tokens the think block
    # gets cut off mid-sentence and </think> never appears.
    # Fix: search the entire response for the LAST occurrence of YES or NO.
    # The model always concludes its reasoning with "the answer is YES/NO"
    # so the last match is always the final decision.
    yes_positions = [m.start() for m in re.finditer(r'\bYES\b', raw.upper())]
    no_positions  = [m.start() for m in re.finditer(r'\bNO\b',  raw.upper())]

    last_yes = yes_positions[-1] if yes_positions else -1
    last_no  = no_positions[-1]  if no_positions  else -1

    # Default to True (retrieve) if neither found — safe fallback
    if last_yes == -1 and last_no == -1:
        result = True
    else:
        result = last_yes > last_no

    print(f"[Sarvam] Retrieval needed: {result} "
          f"(last YES pos={last_yes}, last NO pos={last_no})")

    return result

    # CONCEPT: Sarvam-m hits max_tokens mid-think-block at low limits.
    # The </think> tag never appears so stripping finds nothing.
    # Solution: search the ENTIRE response for YES or NO.
    # The think block reasoning always concludes with "answer should be YES/NO"
    # We find the LAST occurrence of YES or NO in the response
    # which is almost always the model's final conclusion.

# ─────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _build_rag_prompt(
    query:          str,
    context_chunks: list[dict],
    history:        list[dict],
    style:          str = "explanatory",
) -> str:
    """
    Builds the full RAG prompt with context and history.

    CONCEPT: Prompt structure order matters. Sarvam AI (like most
    LLMs) attends more strongly to content near the end of the
    prompt. So we order:
      1. System instruction  (sets the rules)
      2. Chat history        (background context)
      3. Retrieved chunks    (specific evidence)
      4. Current question    (what to answer right now)

    The current question is last so it's freshest in the model's
    attention when generating the answer.
    """

    # Format retrieved chunks as a numbered list
    # CONCEPT: Numbering helps the model reference specific chunks
    # and makes the context block scannable.
    context_lines = []
    for i, chunk in enumerate(context_chunks):
        section = chunk["metadata"].get("section", "")
        section_part = f" | Section: {section}" if section else ""
        context_lines.append(
            f"[Chunk {i+1} - Page {chunk['metadata'].get('page_number', '?')}"
            f"{section_part} | {chunk['metadata'].get('filename', 'document')}]\n"
            f"{chunk['content']}"
        )
    context_block = "\n\n".join(context_lines)

    history_text = _format_history(history)

    style_block = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["explanatory"])

    prompt = f"""You are a knowledgeable tutor helping a student understand their uploaded documents.

{style_block}

Context usage:
- Use retrieved chunks as the primary source
- Combine multiple chunks into one coherent explanation
- Simplify fragmented context

Rules:
- Do NOT say "based on the context"
- If not found in documents: "This is not clearly covered in your document. Based on my knowledge: [answer]"
- Never fabricate document content
{history_text}
Document context:
{context_block}

Current question: {query}

Answer:"""

    return prompt


def _format_history(history: list[dict]) -> str:
    """
    Formats chat history as plain text for injection into prompts.
    Returns empty string if no history.
    """

    if not history:
        return ""

    lines = ["\nPrior conversation:"]
    for msg in history:
        label = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{label}: {msg['content']}")

    return "\n".join(lines) + "\n"


def _build_direct_prompt(query: str, history: list[dict], style: str) -> str:
    history_text = _format_history(history)
    style_block = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["explanatory"])

    return f"""You are a helpful assistant. Answer the following question accurately using your own knowledge.

{style_block}
{history_text}
Question: {query}

Answer:"""


def _strip_think_tags(text: str) -> str:
    """
    Removes <think>...</think> blocks from Sarvam AI output.

    CONCEPT: Sarvam-m (105B) uses chain-of-thought reasoning and
    outputs its thinking process inside <think> tags before the
    actual answer. We never want to show this to the user or
    embed it as part of the answer.

    From CLAUDE.md Phase 3:
    "Sarvam-m outputs <think>...</think> reasoning tags before
     the actual answer. HyDE must strip these before embedding
     or the vector is noisy and retrieval drifts."

    Same applies here — we always strip before returning.
    """

    # Defensive: callers may pass None if an upstream API returned an
    # empty completion. Treat that as empty string, not a crash.
    if not text:
        return ""

    # Strip any think blocks (handles multiline content).
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()


def _call_sarvam(
    messages:    list[dict],
    max_tokens:  int,
    temperature: float,
) -> str:
    """
    Makes a single Sarvam AI API call with retry logic.
    Returns raw response text (think tags not yet stripped).

    CONCEPT: Exponential backoff on retries — each retry waits
    twice as long as the previous one:
      Attempt 1 fails → wait 2s
      Attempt 2 fails → wait 4s
      Attempt 3 fails → raise exception → SQS retries the message
    This gives transient failures (network blips, brief overloads)
    time to resolve without hammering the API.
    """

    api_key     = get_secret("SARVAM_API_KEY_RAG")
    retry_delay = RETRY_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                SARVAM_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       SARVAM_MODEL,
                    "messages":    messages,
                    "max_tokens":  max_tokens,
                    "temperature": temperature,
                },
                timeout=60,
            )

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                # Sarvam can return content: null (empty/reasoning-only
                # completion). Never propagate None to callers.
                return content or ""

            elif response.status_code == 429:
                # Rate limit — wait longer
                wait = retry_delay * attempt * 2
                print(f"[Sarvam] Rate limited. "
                      f"Waiting {wait}s (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)

            elif response.status_code >= 500:
                # Server error — retry with backoff
                print(f"[Sarvam] Server error {response.status_code}. "
                      f"Waiting {retry_delay}s "
                      f"(attempt {attempt}/{MAX_RETRIES})")
                time.sleep(retry_delay)
                retry_delay *= 2

            else:
                # Client error — retrying won't help
                raise ValueError(
                    f"[Sarvam] API error {response.status_code}: "
                    f"{response.text}"
                )

        except requests.exceptions.Timeout:
            print(f"[Sarvam] Timeout. "
                  f"Waiting {retry_delay}s "
                  f"(attempt {attempt}/{MAX_RETRIES})")
            time.sleep(retry_delay)
            retry_delay *= 2

        except requests.exceptions.ConnectionError:
            print(f"[Sarvam] Connection error. "
                  f"Waiting {retry_delay}s "
                  f"(attempt {attempt}/{MAX_RETRIES})")
            time.sleep(retry_delay)
            retry_delay *= 2

    raise Exception(
        f"[Sarvam] API failed after {MAX_RETRIES} attempts. "
        f"SQS will retry this message."
    )


def route_generation_model(query: str, n_docs: int) -> str:
    """
    Classifies the query and returns the appropriate generation model name.

    Returns one of: "deepseek" | "kimi"

    Routing intent:
      deepseek — single-document work: summarise, explain, extract, find section
      kimi     — cross-document reasoning: compare, gap analysis, contradictions,
                 compliance, research synthesis

    When n_docs > 1 we still ask Sarvam because even with multiple docs the
    query might be "summarise document A" (deepseek) vs "compare A and B" (kimi).

    Falls back to:
      - "kimi"     when n_docs > 1 and Sarvam fails
      - "deepseek" when n_docs <= 1 and Sarvam fails
    """
    fallback = "kimi" if n_docs > 1 else "deepseek"
    print(f"[Sarvam] Routing generation model for: '{query[:80]}' (n_docs={n_docs})")

    prompt = (
        "You are a routing classifier. Given a user query, decide which LLM model "
        "should handle it.\n\n"
        "Reply with ONLY the model name — no explanation, no punctuation.\n\n"
        "Models:\n"
        "  deepseek — single-document tasks: summarise, explain a concept, "
        "find a section, extract dates/entities/requirements, list items, "
        "answer a factual question from one document\n"
        "  kimi — cross-document tasks: compare documents, identify contradictions, "
        "gap analysis, compliance check across policies, research synthesis, "
        "find missing requirements across sources\n\n"
        f"Query: {query}\n\n"
        "Model:"
    )

    try:
        raw = _call_sarvam(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0,
        )
    except Exception as e:
        print(f"[Sarvam] route_generation_model failed: {e} — using fallback '{fallback}'")
        return fallback

    decision = _strip_think_tags(raw).strip().lower()

    if "kimi" in decision:
        result = "kimi"
    elif "deepseek" in decision:
        result = "deepseek"
    else:
        print(f"[Sarvam] Unexpected routing output '{decision}' — using fallback '{fallback}'")
        result = fallback

    print(f"[Sarvam] Generation model routed → {result}")
    return result
