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
SARVAM_MODEL   = "sarvam-m"

# Retry settings for transient failures
MAX_RETRIES    = 3
RETRY_DELAY    = 2   # seconds, doubles each retry


def generate_answer(
    query:          str,
    context_chunks: list[dict],
    history:        list[dict],
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

    prompt = _build_rag_prompt(query, context_chunks, history)

    print(f"[Sarvam] Generating RAG answer for: '{query[:80]}'")
    print(f"[Sarvam] Context: {len(context_chunks)} chunks, "
          f"History: {len(history)} messages")

    raw_response = _call_sarvam(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=0.3,
        # CONCEPT: temperature=0.3 for RAG generation.
        # Lower temperature = more focused, less creative.
        # We want factual answers grounded in the context,
        # not creative elaboration. 0.3 is a good balance —
        # deterministic enough to stay on-topic, not so rigid
        # that the answer reads like a list of bullet points.
    )

    answer = _strip_think_tags(raw_response)

    print(f"[Sarvam] Answer generated ({len(answer)} chars)")
    return answer


def direct_answer(query: str, history: list[dict]) -> str:
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

    history_text = _format_history(history)

    prompt = f"""You are a helpful assistant. Answer the following 
question concisely and accurately using your own knowledge.
{history_text}
Question: {query}

Answer:"""

    raw_response = _call_sarvam(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.5,
    )

    answer = _strip_think_tags(raw_response)
    print(f"[Sarvam] Direct answer generated ({len(answer)} chars)")
    return answer

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
    context_block = "\n\n".join([
        f"[Chunk {i+1} — "
        f"Page {chunk['metadata'].get('page_number', '?')} of "
        f"{chunk['metadata'].get('filename', 'document')}]\n"
        f"{chunk['content']}"
        for i, chunk in enumerate(context_chunks)
    ])

    history_text = _format_history(history)

    prompt = f"""You are a helpful assistant that answers questions \
based strictly on the provided document context.

Rules:
- Answer ONLY using information from the context chunks below
- If the answer is not in the context, say: \
"I could not find this information in your documents"
- Be concise and specific
- Reference which chunk or page your answer comes from \
when relevant
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
                return content

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