# lambdas/query_lambda/mmr.py
#
# Responsibility: apply MMR (Maximal Marginal Relevance) to
# diversify the top-k chunks selected from RRF results.
#
# CONCEPT: MMR was introduced by Carbonell & Goldstein (1998).
# The problem it solves: naive top-k retrieval often returns
# near-duplicate chunks because similar content clusters together
# in embedding space. If your PDF has 5 paragraphs all saying
# "K-means assigns points to the nearest centroid", top-3 retrieval
# gives you 3 near-identical chunks — wasting LLM context space.
#
# MMR balances two competing goals:
#   Relevance  → how similar is this chunk to the query?
#   Diversity  → how different is this chunk from already-selected chunks?
#
# lambda_mult parameter:
#   1.0 → pure relevance (same as top-k, no diversity)
#   0.0 → pure diversity (ignores relevance entirely)
#   0.7 → good default (from CLAUDE.md Phase 3 experiments)
#
# IMPORTANT: Supabase returns pgvector embeddings as strings in the
# format "[0.1, 0.2, 0.3, ...]". All vectors must be parsed into
# Python lists of floats before any arithmetic can be done on them.
# This is the root cause of the TypeError we fixed here.

import numpy as np


def mmr_rerank(
    query_embedding:  list,
    chunks:           list[dict],
    top_k:            int   = 3,
    lambda_mult:      float = 0.7,
) -> list[dict]:
    """
    Applies MMR to select top_k diverse and relevant chunks.

    Parameters:
        query_embedding — the HyDE or direct embedding of the query
        chunks          — candidates from RRF hybrid search
                          each chunk must have an "embedding" key
        top_k           — how many chunks to return (default 3)
        lambda_mult     — relevance vs diversity trade-off (default 0.7)

    Returns top_k chunks ordered by MMR selection order.
    """

    if not chunks:
        return []

    if len(chunks) <= top_k:
        print(f"[MMR] Only {len(chunks)} candidates — returning all")
        return chunks

    print(f"[MMR] Applying MMR: {len(chunks)} candidates → top {top_k} "
          f"(lambda_mult={lambda_mult})")

    # ── Parse query embedding ──────────────────────────────────────
    # CONCEPT: Supabase may return the query embedding as a string.
    # Parse it to a list of floats before any calculations.
    parsed_query = _parse_vector(query_embedding)

    if not parsed_query:
        print(f"[MMR] Could not parse query embedding — "
              f"returning top {top_k} by RRF score")
        return chunks[:top_k]

    # ── Filter chunks that have embeddings ─────────────────────────
    # CONCEPT: In the new async embed pipeline, some chunks may not
    # have embeddings yet (embedding=None while embed worker is running).
    # We skip those chunks for MMR and fall back to RRF ordering.
    chunks_with_embeddings = []
    chunks_without_embeddings = []

    for chunk in chunks:
        raw_vec = chunk.get("embedding")
        parsed  = _parse_vector(raw_vec)

        if parsed:
            chunk["_parsed_embedding"] = parsed
            chunks_with_embeddings.append(chunk)
        else:
            chunks_without_embeddings.append(chunk)

    if chunks_without_embeddings:
        print(f"[MMR] {len(chunks_without_embeddings)} chunks have no embedding — "
              f"skipping them for MMR diversity calculation")

    if not chunks_with_embeddings:
        print(f"[MMR] No chunks have embeddings — "
              f"returning top {top_k} by RRF score")
        return chunks[:top_k]

    # ── MMR selection loop ─────────────────────────────────────────
    selected_indices  = []
    remaining_indices = list(range(len(chunks_with_embeddings)))

    for iteration in range(min(top_k, len(chunks_with_embeddings))):
        best_index = None
        best_score = float("-inf")

        for idx in remaining_indices:
            chunk_vec = chunks_with_embeddings[idx]["_parsed_embedding"]

            # ── Relevance term ─────────────────────────────────────
            # How similar is this chunk to the query?
            # Higher = more relevant to what the user asked.
            relevance = cosine_similarity(parsed_query, chunk_vec)

            # ── Diversity term ─────────────────────────────────────
            # How similar is this chunk to already-selected chunks?
            # High similarity to selected = penalise (near-duplicate).
            # On first iteration selected_indices is empty → max_sim = 0.
            if selected_indices:
                max_sim_to_selected = max(
                    cosine_similarity(
                        chunk_vec,
                        chunks_with_embeddings[s]["_parsed_embedding"]
                    )
                    for s in selected_indices
                )
            else:
                max_sim_to_selected = 0.0

            # ── MMR score ──────────────────────────────────────────
            # CONCEPT: score = λ·relevance - (1-λ)·max_similarity_to_selected
            # λ=0.7 means 70% weight on relevance, 30% on diversity.
            # A chunk very similar to an already-selected chunk gets
            # penalised by the second term — bringing diverse chunks
            # into the selection even if they're slightly less relevant.
            mmr_score = (
                lambda_mult * relevance
                - (1 - lambda_mult) * max_sim_to_selected
            )

            if mmr_score > best_score:
                best_score = mmr_score
                best_index = idx

        if best_index is not None:
            selected_indices.append(best_index)
            remaining_indices.remove(best_index)

            page = chunks_with_embeddings[best_index]["metadata"].get(
                "page_number", "?"
            )
            print(f"[MMR] Iteration {iteration + 1}: "
                  f"selected chunk index {best_index} "
                  f"(score={best_score:.4f}, page={page})")

    selected = [chunks_with_embeddings[i] for i in selected_indices]

    # Clean up temporary parsed embedding key before returning
    for chunk in selected:
        chunk.pop("_parsed_embedding", None)

    print(f"[MMR] Complete: selected {len(selected)} chunks from pages "
          f"{[c['metadata'].get('page_number', '?') for c in selected]}")

    return selected


def cosine_similarity(vec_a, vec_b) -> float:
    """
    Computes cosine similarity between two vectors.
    Returns a value between -1 and 1.
    1.0  = identical direction (maximum similarity)
    0.0  = perpendicular (no similarity)
    -1.0 = opposite direction (maximum dissimilarity)

    CONCEPT: Cosine similarity measures the angle between two vectors,
    not their magnitude. Two chunks about the same topic will have
    vectors pointing in nearly the same direction regardless of
    how long the chunks are.

    IMPORTANT: Both inputs are parsed through _parse_vector() before
    arithmetic. Supabase returns pgvector columns as strings like
    "[0.023, -0.089, 0.154, ...]" which cannot be used directly
    in Python arithmetic — they must be converted to list[float] first.
    """

    a = np.array(_parse_vector(vec_a), dtype=np.float32)
    b = np.array(_parse_vector(vec_b), dtype=np.float32)

    if a.size == 0 or b.size == 0 or len(a) != len(b):
        return 0.0

    # Vectors are already normalized by Titan (normalize=True)
    # so magnitude is always 1.0 — dot product equals cosine similarity.
    return float(np.dot(a, b))


def _parse_vector(vec) -> list[float]:
    """
    Parses any vector representation into a list of floats.

    Handles all formats Supabase might return:
      - list[float]  → [0.1, 0.2, 0.3]        already correct
      - list[str]    → ["0.1", "0.2", "0.3"]   convert each element
      - str          → "[0.1, 0.2, 0.3]"        parse the string
      - None         → []                        return empty

    CONCEPT: pgvector in Supabase/PostgREST serialises VECTOR columns
    differently depending on the client and query type:
      - Direct table queries → Python list of floats (correct)
      - RPC function returns → sometimes a string representation
    We handle all cases defensively so MMR never crashes on type issues.
    """

    if vec is None:
        return []

    # Already a list
    if isinstance(vec, list):
        if not vec:
            return []
        try:
            return [float(x) for x in vec]
        except (ValueError, TypeError):
            return []

    # String representation "[0.1, 0.2, ...]"
    if isinstance(vec, str):
        vec = vec.strip()
        if not vec:
            return []

        # Remove surrounding brackets if present
        if vec.startswith("["):
            vec = vec[1:]
        if vec.endswith("]"):
            vec = vec[:-1]

        if not vec.strip():
            return []

        try:
            return [float(x.strip()) for x in vec.split(",") if x.strip()]
        except (ValueError, TypeError):
            return []

    # Unexpected type
    print(f"[MMR] Warning: unexpected vector type {type(vec)} — returning []")
    return []