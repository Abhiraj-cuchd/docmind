# lambdas/query_lambda/nvidia.py
#
# Responsibility: all LLM generation calls, dispatched per model to its
# own provider:
#
#   Llama 3.3 70B  — single-doc Q&A      → Groq   (fast, free tier)
#   Kimi K2.6      — multi-doc reasoning → NVIDIA NIM
#
# Both providers are OpenAI-compatible, so one transport handles both —
# only the URL, API key, and model id differ (see _PROVIDERS).
# Model is selected upstream by sarvam.route_generation_model().

import requests
import time
import re
from shared_lambda.secrets import get_secret

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GROQ_API_URL   = "https://api.groq.com/openai/v1/chat/completions"

MODEL_LLAMA = "llama-3.3-70b-versatile"   # Groq model id
MODEL_KIMI  = "moonshotai/kimi-k2.6"      # NVIDIA NIM model id

# Keep MODEL_DEEPSEEK as alias so any existing references don't break
MODEL_DEEPSEEK = MODEL_LLAMA

# Per-model provider routing. Each model goes to the endpoint that hosts it.
_PROVIDERS = {
    MODEL_LLAMA: {"url": GROQ_API_URL,   "secret": "GROQ_API_KEY",   "label": "Groq"},
    MODEL_KIMI:  {"url": NVIDIA_API_URL, "secret": "NVIDIA_API_KEY", "label": "NVIDIA"},
}

MAX_RETRIES  = 3
RETRY_DELAY  = 2

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
    model:          str = MODEL_DEEPSEEK,
) -> str:
    prompt = _build_rag_prompt(query, context_chunks, history, style)

    n_docs = len({c["metadata"].get("filename") for c in context_chunks if c.get("metadata")})
    print(f"[{_tag(model)}] RAG answer: '{query[:80]}' | "
          f"{len(context_chunks)} chunks, {n_docs} doc(s)")

    raw    = _call_llm(model=model, messages=[{"role": "user", "content": prompt}],
                       max_tokens=4096, temperature=0.5)
    answer = _strip_think_tags(raw)
    print(f"[{_tag(model)}] Answer: {len(answer)} chars")
    return answer


def direct_answer(
    query:   str,
    history: list[dict],
    style:   str = "explanatory",
    model:   str = MODEL_DEEPSEEK,
) -> str:
    print(f"[{_tag(model)}] Direct answer: '{query[:80]}'")

    prompt = _build_direct_prompt(query, history, style)
    raw    = _call_llm(model=model, messages=[{"role": "user", "content": prompt}],
                       max_tokens=1024, temperature=0.5)
    answer = _strip_think_tags(raw)
    print(f"[{_tag(model)}] Direct: {len(answer)} chars")
    return answer


# ─────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _build_rag_prompt(
    query:          str,
    context_chunks: list[dict],
    history:        list[dict],
    style:          str,
) -> str:
    by_doc: dict[str, list] = {}
    for chunk in context_chunks:
        fname = chunk["metadata"].get("filename", "document")
        by_doc.setdefault(fname, []).append(chunk)

    context_lines = []
    chunk_num = 1
    for fname, chunks in by_doc.items():
        context_lines.append(f"=== Document: {fname} ===")
        for chunk in chunks:
            section      = chunk["metadata"].get("section", "")
            section_part = f" | Section: {section}" if section else ""
            context_lines.append(
                f"[Chunk {chunk_num} - Page {chunk['metadata'].get('page_number', '?')}"
                f"{section_part}]\n{chunk['content']}"
            )
            chunk_num += 1

    context_block = "\n\n".join(context_lines)
    history_text  = _format_history(history)
    style_block   = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["explanatory"])

    multi_doc_note = (
        "\nImportant: chunks come from multiple documents. "
        "Synthesize across all of them into a single coherent answer. "
        "Reference document names only if the distinction matters.\n"
        if len(by_doc) > 1 else ""
    )

    return f"""You are a knowledgeable tutor helping a student understand their uploaded documents.

{style_block}
{multi_doc_note}
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


def _build_direct_prompt(query: str, history: list[dict], style: str) -> str:
    history_text = _format_history(history)
    style_block  = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["explanatory"])

    return f"""You are a helpful assistant. Answer the following question accurately using your own knowledge.

{style_block}
{history_text}
Question: {query}

Answer:"""


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["\nPrior conversation:"]
    for msg in history:
        label = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{label}: {msg['content']}")
    return "\n".join(lines) + "\n"


def _strip_think_tags(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _short(model: str) -> str:
    return model.split("/")[-1]


def _provider(model: str) -> dict:
    # Default to the Groq/Llama provider for any unmapped model id.
    return _PROVIDERS.get(model, _PROVIDERS[MODEL_LLAMA])


def _tag(model: str) -> str:
    return f"{_provider(model)['label']}/{_short(model)}"


def _call_llm(
    model:       str,
    messages:    list[dict],
    max_tokens:  int,
    temperature: float,
) -> str:
    provider    = _provider(model)
    url         = provider["url"]
    api_key     = get_secret(provider["secret"])
    tag         = _tag(model)
    retry_delay = RETRY_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                    "Accept":        "application/json",
                },
                json={
                    "model":       model,
                    "messages":    messages,
                    "max_tokens":  max_tokens,
                    "temperature": temperature,
                    "top_p":       1.0,
                    "stream":      False,
                },
                timeout=90,
            )

            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"] or ""

            elif response.status_code == 429:
                wait = retry_delay * attempt * 2
                print(f"[{tag}] Rate limited. "
                      f"Waiting {wait}s (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)

            elif response.status_code >= 500:
                print(f"[{tag}] Server error {response.status_code}. "
                      f"Waiting {retry_delay}s (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(retry_delay)
                retry_delay *= 2

            else:
                raise ValueError(
                    f"[{tag}] API error {response.status_code}: "
                    f"{response.text}"
                )

        except requests.exceptions.Timeout:
            print(f"[{tag}] Timeout. "
                  f"Waiting {retry_delay}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(retry_delay)
            retry_delay *= 2

        except requests.exceptions.ConnectionError:
            print(f"[{tag}] Connection error. "
                  f"Waiting {retry_delay}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(retry_delay)
            retry_delay *= 2

    raise Exception(
        f"[{tag}] API failed after {MAX_RETRIES} attempts. "
        f"SQS will retry this message."
    )


