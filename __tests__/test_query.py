# scripts/test_processor.py
# Tests the processor pipeline with a real query
# Requires: at least one document indexed in Supabase

import sys
sys.path.insert(0, "lambdas")

from load_env import *

# Replace with a real user_id from your Supabase auth.users table
TEST_USER_ID = "paste-a-real-user-uuid-here"
TEST_QUERY   = "What is machine learning?"    # change to match your PDF

def test_processor():
    print("\n=== Testing Processor Pipeline ===")

    if TEST_USER_ID == "paste-a-real-user-uuid-here":
        print("⚠️  Set TEST_USER_ID in this script first")
        print("   Go to Supabase → Authentication → Users → copy UUID")
        return

    # ── Step 1: Test classifier ────────────────────────────────────
    print("\n--- Step 1: Classifier ---")
    from query_lambda.classifier import (
        get_conversational_response,
        classify_query,
    )

    greetings = ["Hi!", "Hello there", "Thanks!", "Bye"]
    for g in greetings:
        response = get_conversational_response(g)
        assert response is not None, f"'{g}' should be conversational"
        print(f"✅ '{g}' → conversational ✓")

    doc_query = "What does the document say about neural networks?"
    response  = get_conversational_response(doc_query)
    assert response is None, "Document query should not be conversational"
    print(f"✅ '{doc_query[:40]}...' → not conversational ✓")

    # ── Step 2: Test needs_retrieval (real Sarvam call) ────────────
    print("\n--- Step 2: needs_retrieval (Sarvam Router) ---")
    from query_lambda.sarvam import needs_retrieval

    result = needs_retrieval("What is 2 + 2?")
    print(f"✅ 'What is 2+2?' → needs_retrieval={result} "
          f"(expected False)")

    result = needs_retrieval(TEST_QUERY)
    print(f"✅ '{TEST_QUERY[:40]}' → needs_retrieval={result}")

    # ── Step 3: Test Voyage AI embedding ──────────────────────────
    print("\n--- Step 3: Query Embedding (Voyage AI) ---")
    from query_lambda.hyde import embed_query

    embedding = embed_query(TEST_QUERY)
    assert len(embedding) == 1024
    print(f"✅ Query embedded: 1024 dims, "
          f"first value={embedding[0]:.4f}")

    # ── Step 4: Test hybrid search ─────────────────────────────────
    print("\n--- Step 4: Hybrid Search (Supabase) ---")
    from shared_lambda.supabase_client import execute_hybrid_search

    candidates = execute_hybrid_search(
        user_id=TEST_USER_ID,
        query_embedding=embedding,
        query_text=TEST_QUERY,
        match_count=10,
    )
    print(f"✅ Hybrid search returned {len(candidates)} candidates")

    if candidates:
        top = candidates[0]
        print(f"   Top result RRF score: {top.get('rrf_score', 0):.4f}")
        print(f"   Top result preview: "
              f"'{top['content'][:100]}'...")
    else:
        print("⚠️  No candidates returned — "
              "make sure documents are indexed for this user")

    # ── Step 5: Test HyDE ──────────────────────────────────────────
    print("\n--- Step 5: HyDE (Sarvam RAG) ---")
    from query_lambda.hyde import generate_hyde_embedding

    hyde_embedding, hyp_answer = generate_hyde_embedding(TEST_QUERY)
    print(f"✅ HyDE hypothetical answer: '{hyp_answer[:100]}'...")
    assert len(hyde_embedding) == 1024
    print(f"✅ HyDE embedding: 1024 dims")

    # ── Step 6: Test MMR ───────────────────────────────────────────
    print("\n--- Step 6: MMR ---")
    from query_lambda.mmr import mmr_rerank

    if candidates:
        top_chunks = mmr_rerank(
            query_embedding=embedding,
            chunks=candidates,
            top_k=3,
            lambda_mult=0.7,
        )
        print(f"✅ MMR selected {len(top_chunks)} chunks")
        for i, chunk in enumerate(top_chunks):
            print(f"   Chunk {i+1}: "
                  f"page {chunk['metadata'].get('page_number')}, "
                  f"'{chunk['content'][:60]}'...")
    else:
        print("⏭  MMR skipped — no candidates to rerank")
        top_chunks = []

    # ── Step 7: Test answer generation ────────────────────────────
    print("\n--- Step 7: Answer Generation (Sarvam RAG) ---")
    from query_lambda.sarvam import generate_answer

    if top_chunks:
        answer = generate_answer(
            query=TEST_QUERY,
            context_chunks=top_chunks,
            history=[],
        )
        print(f"✅ Answer generated ({len(answer)} chars):")
        print(f"   '{answer[:200]}'...")
    else:
        from query_lambda.sarvam import direct_answer
        answer = direct_answer(TEST_QUERY, history=[])
        print(f"✅ Direct answer (no chunks): '{answer[:200]}'...")

    print("\n✅ Processor pipeline working end to end")

if __name__ == "__main__":
    test_processor()