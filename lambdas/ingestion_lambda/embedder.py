# lambdas/ingestion_lambda/embedder.py
#
# Embeds text chunks using Amazon Titan Embeddings V2 via AWS Bedrock.
# Replaces Voyage AI — no rate limits, same AWS region, fast.
#
# CONCEPT: Amazon Bedrock is AWS's managed AI service. Calling Titan
# via Bedrock is an internal AWS API call — no external network hop,
# no rate limits, no API keys. IAM handles auth automatically.
#
# Model: amazon.titan-embed-text-v2:0
# Dimensions: 1024 (matches VECTOR(1024) in Supabase schema)
# Max input: 8192 tokens per call
# Cost: ~$0.00002 per 1K tokens (~$0.03/month at our scale)

import boto3
import json
import os

bedrock_client = boto3.client(
    "bedrock-runtime",
    region_name=os.getenv("AWS_REGION", "ap-south-1"),
)

TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMS = 1024


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """
    Embeds all chunks using Amazon Titan Embeddings V2.
    One Bedrock call per chunk — no batching needed since
    Bedrock has no rate limits and each call takes ~100ms.

    CONCEPT: 600 chunks × 100ms = ~60 seconds total.
    Compare to Voyage AI with rate limits: 3+ minutes.
    No retry logic needed — Bedrock is reliable and unlimited.
    """

    if not chunks:
        raise ValueError("[Embedder] Received empty chunks list")

    print(f"[Embedder] Embedding {len(chunks)} chunks "
          f"using {TITAN_MODEL_ID} ({EMBEDDING_DIMS} dims)")

    for i, chunk in enumerate(chunks):
        chunk["embedding"] = _embed_single(chunk["content"])

        if (i + 1) % 50 == 0:
            print(f"[Embedder] Progress: {i + 1}/{len(chunks)} chunks")

    # Verify dimensions on first chunk
    sample_dim = len(chunks[0]["embedding"])
    if sample_dim != EMBEDDING_DIMS:
        raise ValueError(
            f"[Embedder] Expected {EMBEDDING_DIMS} dims, got {sample_dim}. "
            f"Check Titan model configuration."
        )

    print(f"[Embedder] ✅ Complete: {len(chunks)} chunks embedded "
          f"({EMBEDDING_DIMS} dimensions each)")

    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embeds a list of raw text strings.
    Used by embed_worker.py.
    Returns list of 1024-dim vectors in same order as input.
    """

    print(f"[Embedder] Embedding {len(texts)} texts via Titan")

    embeddings = []
    for text in texts:
        embeddings.append(_embed_single(text))

    return embeddings


def embed_single_text(text: str) -> list[float]:
    """
    Embeds a single text string.
    Public wrapper around _embed_single for use by other modules.
    """
    return _embed_single(text)


def _embed_single(text: str) -> list[float]:
    """
    Calls Bedrock to embed one text string using Titan V2.
    Returns a list of 1024 floats.

    CONCEPT: Titan V2 body parameters:
      inputText  — the text to embed (max 8192 tokens)
      dimensions — output vector size: 256, 512, or 1024
      normalize  — L2-normalise the vector (True for cosine similarity)

    We use dimensions=1024 to match rag.chunks VECTOR(1024) column.
    normalize=True is required for accurate cosine distance with
    pgvector's <=> operator.
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