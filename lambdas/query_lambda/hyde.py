# lambdas/query_lambda/hyde.py
#
# HyDE (Hypothetical Document Embeddings) implementation.
# Generates a fake answer to the query, then embeds it.
# Uses Amazon Titan V2 for embeddings — no rate limits.
#
# CONCEPT: HyDE bridges the gap between question and answer space.
# A question "How does Q-learning work?" lives in a different part
# of embedding space than the answer "Q-learning works by updating
# Q-values using the Bellman equation...".
# By generating a fake answer and embedding it, our query vector
# lands in the neighbourhood of real answer chunks.
#
# From CLAUDE.md Phase 3:
#   "Sarvam-m outputs <think>...</think> reasoning tags.
#    Strip these before embedding or the vector is noisy."

import boto3
import json
import os
import requests
import re
from shared_lambda.secrets import get_secret

bedrock_client = boto3.client(
    "bedrock-runtime",
    region_name=os.getenv("AWS_REGION", "ap-south-1"),
)

TITAN_MODEL_ID  = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMS  = 1024
SARVAM_API_URL  = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_MODEL    = "sarvam-105b"


def embed_query(query: str) -> list[float]:
    """
    Embeds the raw query text using Titan V2.
    Used for direct embedding before hybrid search.
    input_type is "query" context — same model handles both
    documents and queries in Titan (symmetric embeddings).
    """
    print(f"[HyDE] Embedding query directly via Titan")
    return _embed_text(query)


def generate_hyde_embedding(query: str) -> tuple[list[float], str]:
    """
    Generates a hypothetical answer via Sarvam AI,
    strips think tags, then embeds via Titan.
    Falls back to direct query embedding if Sarvam fails.

    Returns:
        (embedding, hypothetical_answer_text)
    """

    print(f"[HyDE] Generating hypothetical answer for: '{query[:80]}'")

    hypothetical_answer = _generate_hypothetical_answer(query)

    print(f"[HyDE] Hypothetical answer ({len(hypothetical_answer)} chars): "
          f"'{hypothetical_answer[:100]}'")

    embedding = _embed_text(hypothetical_answer)

    return embedding, hypothetical_answer


# ─────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _embed_text(text: str) -> list[float]:
    """
    Embeds text via Amazon Titan V2.
    No API key needed — IAM role grants bedrock:InvokeModel.
    """

    body = json.dumps({
        "inputText":  text[:8000],
        "dimensions": EMBEDDING_DIMS,
        "normalize":  True,
    })

    response = bedrock_client.invoke_model(
        modelId=TITAN_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )

    response_body = json.loads(response["body"].read())
    return response_body["embedding"]


def _generate_hypothetical_answer(query: str) -> str:
    """
    Calls Sarvam AI to generate a concise hypothetical answer.
    Strips <think> tags before returning.
    Falls back to original query on any failure.
    """

    sarvam_api_key = get_secret("SARVAM_API_KEY_RAG")

    hyde_prompt = f"""Write a textbook passage that teaches the following concept.
Include: what it is, how it works, and a concrete example.
Be specific and factual.

Question: {query}

Passage:"""

    try:
        response = requests.post(
            SARVAM_API_URL,
            headers={
                "Authorization": f"Bearer {sarvam_api_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       SARVAM_MODEL,
                "messages":    [{"role": "user", "content": hyde_prompt}],
                "max_tokens":  300,
                "temperature": 0.7,
            },
            timeout=30,
        )

        if response.status_code != 200:
            print(f"[HyDE] Sarvam error {response.status_code} — "
                  f"falling back to direct query")
            return query

        raw = response.json()["choices"][0]["message"]["content"]
        cleaned = _strip_think_tags(raw).strip()

        if not cleaned:
            print(f"[HyDE] Empty after stripping think tags — "
                  f"falling back to direct query")
            return query

        return cleaned

    except Exception as e:
        print(f"[HyDE] Generation failed: {e} — "
              f"falling back to direct query")
        return query


def _strip_think_tags(text: str) -> str:
    """
    Strips <think>...</think> reasoning blocks from Sarvam output.
    CONCEPT: Sarvam-m prepends chain-of-thought inside <think> tags.
    We only want the actual answer — not the reasoning process —
    in our HyDE embedding, or it pulls the vector off-topic.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()
