# lambdas/processor/classifier.py
#
# Classifies incoming queries into one of three types:
#   "conversational" → greetings, thanks, social exchanges
#   "general"        → factual questions not needing documents
#   "document"       → questions requiring retrieval from uploaded PDFs
#
# Classification is intentionally cheap:
#   Layer 1 — rule-based keyword matching (zero cost, zero latency)
#   Layer 2 — embedding cosine similarity (zero LLM cost)
#
# CONCEPT: We never want to run retrieval on a greeting.
# "Hi there!" should get "Hello! How can I help you today?"
# not "I could not find this in your documents."
# Classification routes each query to the right handler
# before any expensive operations run.

import re
from shared_lambda.utils import cosine_similarity

# ── Layer 1: Rule-based patterns ──────────────────────────────────────
# These are checked first — zero cost, instant response.
# Covers the vast majority of conversational inputs.

CONVERSATIONAL_PATTERNS = [

    # Greetings
    r"^(hi|hey|hello|howdy|hiya|sup|what'?s up|yo)\b",
    r"^good (morning|afternoon|evening|night|day)\b",
    r"^(namaste|salaam|namaskar)\b",

    # Farewells
    r"^(bye|goodbye|see you|see ya|later|cya|ttyl|take care)\b",
    r"^(good night|good bye)\b",

    # Thanks
    r"^(thanks|thank you|thank u|thx|ty|cheers|appreciated)\b",
    r"^(great|awesome|perfect|wonderful|excellent|fantastic)\s*[!.]?$",
    r"^(ok|okay|got it|understood|makes sense|cool|nice)\s*[!.]?$",

    # How are you / small talk
    r"^how are you\b",
    r"^how'?s it going\b",
    r"^what'?s (up|new|going on)\b",
    r"^(are you (okay|alright|good|fine|there|ready))\b",

    # Questions about the assistant itself
    r"^what (can|do) you do\b",
    r"^(who|what) are you\b",
    r"^(tell me about yourself|introduce yourself)\b",
    r"^(help|can you help( me)?)\s*[?!.]?$",

    # Acknowledgements
    r"^(yes|no|yeah|nope|yep|nah|sure|of course|absolutely)\s*[!.]?$",
]

# Pre-compile for performance
# CONCEPT: re.compile() converts the pattern string into a
# compiled regex object. Compilation happens once at module load
# time (Lambda cold start) and is reused on every warm invocation.
# Matching a pre-compiled pattern is ~10x faster than re.match()
# with a raw string — matters when classifying thousands of queries.
_COMPILED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in CONVERSATIONAL_PATTERNS
]

# ── Conversational responses ───────────────────────────────────────────
# Pre-written responses for common conversational inputs.
# No LLM call needed — deterministic and instant.

CONVERSATIONAL_RESPONSES = {
    "greeting": (
        "Hello! I'm your document assistant. "
        "You can upload PDFs and ask me questions about them. "
        "What would you like to know?"
    ),
    "farewell": (
        "Goodbye! Feel free to come back anytime "
        "if you have more questions about your documents."
    ),
    "thanks": (
        "You're welcome! Is there anything else "
        "you'd like to know from your documents?"
    ),
    "how_are_you": (
        "I'm doing well, thanks for asking! "
        "I'm ready to help you explore your documents. "
        "What would you like to know?"
    ),
    "what_can_you_do": (
        "I can help you find information in your uploaded documents. "
        "Upload a PDF and ask me anything about it — "
        "I'll search through it and give you precise answers. "
        "I also remember our conversation so you can ask follow-up questions."
    ),
    "acknowledgement": (
        "Got it! Let me know if you have any questions "
        "about your documents."
    ),
    "default": (
        "Hello! I'm here to help you with your documents. "
        "What would you like to know?"
    ),
}


def classify_query(
    query:           str,
    query_embedding: list[float] | None = None,
) -> dict:
    """
    Classifies a query into one of three types.
    Returns a dict with 'type' and optional 'response' for
    conversational queries.

    Return shapes:
      {"type": "conversational", "response": "Hello! I'm your..."}
      {"type": "general"}
      {"type": "document"}

    Parameters:
        query           — raw user query text
        query_embedding — optional pre-computed Voyage AI embedding
                          used for Layer 2 if Layer 1 doesn't match
                          pass None to skip Layer 2

    CONCEPT: We return the response text for conversational queries
    directly from this function so handler.py can short-circuit
    immediately without calling any other service.
    """

    cleaned = query.strip()

    # ── Layer 1: Rule-based matching ──────────────────────────────
    layer1_result = _classify_by_rules(cleaned)

    if layer1_result is not None:
        print(f"[Classifier] Layer 1 match: "
              f"'{cleaned[:60]}' → conversational ({layer1_result})")
        return {
            "type":     "conversational",
            "response": CONVERSATIONAL_RESPONSES.get(
                layer1_result,
                CONVERSATIONAL_RESPONSES["default"]
            ),
        }

    # ── Layer 2: Embedding similarity ────────────────────────────
    # CONCEPT: If we have the query embedding (computed for free
    # by Voyage AI), we can compare it against reference embeddings
    # to distinguish general knowledge from document queries.
    # This catches cases like "what is machine learning?" which
    # don't match any keyword pattern but clearly don't need
    # document retrieval.
    #
    # In practice for a RAG assistant, we err on the side of
    # retrieval — if unsure, retrieve. A general knowledge question
    # that goes through retrieval just returns low-confidence chunks
    # and the LLM answers from its own knowledge anyway.
    # So we only split "general" vs "document" when it's obvious.

    if query_embedding is not None:
        layer2_result = _classify_by_embedding(cleaned, query_embedding)
        print(f"[Classifier] Layer 2: "
              f"'{cleaned[:60]}' → {layer2_result}")
        return {"type": layer2_result}

    # Default: treat as document query (safe fallback — retrieval
    # will find nothing relevant if it truly isn't a doc question,
    # and the LLM will say so gracefully)
    print(f"[Classifier] No embedding available — "
          f"defaulting to document query")
    return {"type": "document"}


def get_conversational_response(query: str) -> str | None:
    """
    Quick check — returns a pre-written response if the query
    is conversational, None otherwise.
    Used by handler.py as a fast pre-check before embedding.
    Zero cost — no Voyage AI call needed.
    """

    cleaned      = query.strip()
    layer1_result = _classify_by_rules(cleaned)

    if layer1_result is not None:
        return CONVERSATIONAL_RESPONSES.get(
            layer1_result,
            CONVERSATIONAL_RESPONSES["default"]
        )

    return None


# ─────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _classify_by_rules(query: str) -> str | None:
    """
    Matches query against conversational patterns.
    Returns a response key string if matched, None if no match.
    """

    q_lower = query.lower().strip()

    # Check each compiled pattern
    for pattern in _COMPILED_PATTERNS:
        if pattern.match(q_lower):
            # Determine which response category to use
            return _get_response_key(q_lower)

    # Also catch very short inputs (1-2 words) that aren't questions
    words = q_lower.split()
    if len(words) <= 2 and "?" not in query and not _looks_like_question(q_lower):
        return "default"

    return None


def _get_response_key(query: str) -> str:
    """
    Maps a matched conversational query to a response category.
    """

    q = query.lower()

    if any(word in q for word in
           ["bye", "goodbye", "see you", "later", "take care", "night"]):
        return "farewell"

    if any(word in q for word in
           ["thank", "thanks", "thx", "ty", "cheers", "appreciated"]):
        return "thanks"

    if any(phrase in q for phrase in
           ["how are you", "how's it", "how are u"]):
        return "how_are_you"

    if any(phrase in q for phrase in
           ["what can you do", "what do you do",
            "who are you", "what are you",
            "tell me about yourself", "introduce yourself"]):
        return "what_can_you_do"

    if any(word in q for word in
           ["yes", "no", "yeah", "nope", "yep", "ok",
            "okay", "got it", "understood", "cool",
            "great", "awesome", "perfect", "nice"]):
        return "acknowledgement"

    # Default to greeting
    return "greeting"


def _classify_by_embedding(
    query:           str,
    query_embedding: list[float],
) -> str:
    """
    Uses cosine similarity against reference directions to classify
    as "general" or "document".

    CONCEPT: We don't store reference embeddings — we use simple
    heuristics based on query structure instead, since we don't
    want to make a Voyage AI call just for classification.

    Heuristics that suggest a DOCUMENT query:
      - Contains "document", "pdf", "file", "uploaded", "page"
      - Contains "my", "our" (possessive → their documents)
      - Contains "summarise", "summarize", "explain this"
      - Ends with "in the document/notes/paper"

    Heuristics that suggest a GENERAL knowledge query:
      - Starts with "what is", "who is", "how does X work" (general)
      - Contains well-known general knowledge terms
      - No possessives, no document references

    If unclear → default to "document" (safe — retrieval
    with weak results is better than skipping retrieval entirely)
    """

    q_lower = query.lower()

    # Strong document signals
    document_signals = [
        "my document", "my pdf", "my file", "my notes",
        "my paper", "uploaded", "the document", "the pdf",
        "the file", "the paper", "the notes", "the text",
        "page ", "chapter ", "section ",
        "summarise", "summarize", "according to",
        "what does it say", "what does the",
        "in the document", "in my", "from my",
        "based on", "from the",
    ]

    if any(signal in q_lower for signal in document_signals):
        return "document"

    # Strong general knowledge signals
    general_signals = [
        "what is the capital",
        "who invented",
        "when was",
        "how many",
        "what year",
        "who is the president",
        "what does the word",
        "define ",
        "meaning of ",
        "translate ",
        "what time",
        "what's the weather",
        "calculate ",
        "how many days",
    ]

    if any(signal in q_lower for signal in general_signals):
        return "general"

    # Default to document — err on the side of retrieval
    # CONCEPT: A general knowledge question that goes through
    # retrieval just finds low-scoring chunks. The LLM will
    # answer from its own knowledge when context is weak.
    # A document question that skips retrieval gives a wrong answer.
    # The asymmetry of failure modes favours defaulting to retrieval.
    return "document"


def _looks_like_question(query: str) -> bool:
    """
    Simple check for question indicators.
    Used to avoid classifying short questions as conversational.
    """

    question_starters = [
        "what", "where", "when", "why", "who",
        "how", "which", "can", "could", "would",
        "should", "is", "are", "does", "do", "did",
    ]

    first_word = query.split()[0] if query.split() else ""
    return first_word in question_starters or "?" in query