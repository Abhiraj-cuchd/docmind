# scripts/test_router.py
# Tests the needs_retrieval() routing locally
# Shows raw Sarvam response + think tag stripping
# Run from project root: python scripts/test_router.py

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# ── Setup paths ────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lambdas"))
sys.path.insert(0, str(PROJECT_ROOT / "lambdas" / "shared_lambda"))
sys.path.insert(0, str(PROJECT_ROOT / "lambdas" / "query_lambda"))

load_dotenv(PROJECT_ROOT / ".env")

# ── Import secrets ─────────────────────────────────────────────────────
from shared_lambda.secrets import get_secret

import requests

SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_MODEL   = "sarvam-105b"

# ── Test queries ───────────────────────────────────────────────────────
TEST_QUERIES = [
    # Should be YES (needs retrieval)
    "What does my document say about supervised learning?",
    "Explain neural networks based on my uploaded document",
    "What machine learning algorithms are mentioned in my document?",
    "Summarise the key concepts from my uploaded PDF",
    "What does my document say about gradient descent?",
    "According to my notes, what is backpropagation?",

    # Should be NO (direct answer)
    "What is 2 + 2?",
    "Who invented Python?",
    "What is the capital of France?",
    "Hi there!",
    "Thanks!",
]


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks."""
    if "</think>" in text.lower():
        # Handle both <think> and <THINK> cases
        parts = text.split("</think>") if "</think>" in text else text.split("</THINK>")
        return parts[-1].strip()
    if "<think>" in text.lower():
        # Think block not closed — everything after last > is the answer
        parts = text.rsplit(">", 1)
        if len(parts) > 1:
            return parts[-1].strip()
    return text.strip()


def needs_retrieval_raw(query: str) -> dict:
    """
    Calls Sarvam router and returns full debug info.
    Shows raw response, stripped response, and final decision.
    """

    api_key = get_secret("SARVAM_API_KEY_ROUTER")

    prompt = """Does the following question require searching through 
uploaded documents to answer correctly?

Answer YES if:
- The question mentions "my document", "my PDF", "my notes", "my file"
- The question asks to summarise, explain or find something in a document
- The question says "according to", "what does it say", "based on my"
- The question asks about specific content that would be in a document

Answer NO only if:
- Pure math: "what is 2+2"
- Pure general knowledge: "who invented Python", "what is DNA"
- Conversational only: "thanks", "ok", "bye"

When in doubt, answer YES.

Answer with only YES or NO. No explanation.

Question: """ + query + "\n\nAnswer:"

    response = requests.post(
        SARVAM_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        json={
            "model":       SARVAM_MODEL,
            "messages":    [{"role": "user", "content": prompt}],
            "max_tokens":  100,
            "temperature": 0.0,
        },
        timeout=30,
    )

    if response.status_code != 200:
        return {
            "error": f"API error {response.status_code}: {response.text}",
            "result": None,
        }

    raw      = response.json()["choices"][0]["message"]["content"]
    stripped = strip_think_tags(raw)
    upper    = stripped.upper()
    result   = upper.startswith("YES") or "YES" in upper[:20]

    return {
        "raw":      raw,
        "stripped": stripped,
        "upper":    upper,
        "result":   result,
    }


def main():
    print("\n" + "="*60)
    print("  Sarvam Router — Local Test")
    print("="*60)

    correct = 0
    wrong   = 0
    errors  = 0

    # First 6 should be YES, last 5 should be NO
    expected = [True, True, True, True, True, True,
                False, False, False, False, False]

    for i, query in enumerate(TEST_QUERIES):
        print(f"\n{'─'*60}")
        print(f"Query {i+1}: {query}")
        print(f"Expected: {'YES (retrieval)' if expected[i] else 'NO (direct)'}")

        try:
            result = needs_retrieval_raw(query)

            if "error" in result:
                print(f"❌ Error: {result['error']}")
                errors += 1
                continue

            print(f"\nRaw response:")
            print(f"  {repr(result['raw'][:200])}")
            print(f"\nAfter strip_think_tags:")
            print(f"  {repr(result['stripped'])}")
            print(f"\nUpper:")
            print(f"  {repr(result['upper'][:50])}")

            actual = result["result"]
            exp    = expected[i]

            if actual == exp:
                print(f"\n✅ CORRECT — {'YES' if actual else 'NO'}")
                correct += 1
            else:
                print(f"\n❌ WRONG — got {'YES' if actual else 'NO'}, "
                      f"expected {'YES' if exp else 'NO'}")
                wrong += 1

        except Exception as e:
            print(f"❌ Exception: {e}")
            import traceback
            traceback.print_exc()
            errors += 1

    print(f"\n{'='*60}")
    print(f"Results: {correct} correct, {wrong} wrong, {errors} errors")
    print(f"{'='*60}\n")

    if wrong > 0 or errors > 0:
        print("The strip_think_tags function needs fixing.")
        print("Check the 'Raw response' output above to see")
        print("exactly what Sarvam is returning and adjust accordingly.")


if __name__ == "__main__":
    main()