# lambdas/query_lambda/handler.py
#
# Full query pipeline with two-key Sarvam strategy + LLM routing:
#
# Step 0: Conversational check   (free — regex, no LLM)
# Step 1: Cache check            (free — Redis)
# Step 2: Router token acquire   (router bucket — 1 token)
# Step 3: needs_retrieval YES/NO (SARVAM_API_KEY_ROUTER)
#
#   NO path:
#     Step 4: RAG tokens acquire  (rag bucket — 2 tokens)
#     Step 5: direct_answer()     (SARVAM_API_KEY_RAG)
#
#   YES path:
#     Step 4: embed query         (free — Voyage AI)
#     Step 5: hybrid search       (free — Supabase HNSW + BM25)
#     Step 6: conditional HyDE    (rag bucket — 1 token, optional)
#     Step 7: MMR                 (free — Python)
#     Step 8: RAG tokens acquire  (rag bucket — 2 tokens)
#     Step 9: generate_answer()   (SARVAM_API_KEY_RAG)

import json
import os
import hashlib
from shared_lambda.supabase_client import get_service_client, execute_hybrid_search
from shared_lambda.rate_limiter    import (
    get_redis_client,
    acquire_router_token,
    acquire_hyde_token,
    acquire_generate_tokens,
    get_rate_limit_snapshot,
    GENERATE_COST,
    HYDE_COST,
)
from shared_lambda.classifier import get_conversational_response
from hyde    import generate_hyde_embedding, embed_query
from mmr     import mmr_rerank
from sarvam  import needs_retrieval, generate_answer, direct_answer
from history import (
    fetch_conversation_history,
    save_user_message,
    save_assistant_message,
    update_conversation_timestamp,
)
from shared_lambda.secrets import get_secret

# ── Constants ──────────────────────────────────────────────────────────
RESULT_TTL                = 3600
CACHE_TTL                 = 3600
HYDE_CONFIDENCE_THRESHOLD = 0.02
MMR_TOP_K                 = 3
MMR_LAMBDA                = 0.7

supabase = get_service_client()


# ─────────────────────────────────────────────────────────────────────
# LAMBDA ENTRY POINT
# ─────────────────────────────────────────────────────────────────────

def handler(event, context):
    print(f"[Handler] Received {len(event['Records'])} SQS record(s)")
    for record in event["Records"]:
        _process_record(record)


def _process_record(record: dict) -> None:

    r        = get_redis_client()
    snapshot = get_rate_limit_snapshot(r)
    print(f"[Handler] Token buckets: {snapshot}")

    # ── Parse SQS message ──────────────────────────────────────────
    body            = json.loads(record["body"])
    job_id          = body["job_id"]
    query           = body["query"]
    user_id         = body["user_id"]
    conversation_id = body["conversation_id"]
    voice_mode      = body.get("voice_mode", False)

    print(f"[Handler] Job {job_id}: '{query[:80]}'")

    try:
        # ── Step 0: Conversational check (free — regex) ────────────
        # CONCEPT: Greetings and social exchanges are handled instantly
        # here — zero tokens, zero latency. Pure Python regex matching.
        # "Hi!", "Thanks", "Bye" never touch any external service.
        conversational_response = get_conversational_response(query)

        if conversational_response:
            print(f"[Handler] Conversational — instant response (0 tokens)")
            save_user_message(conversation_id, user_id, query)
            save_assistant_message(
                conversation_id=conversation_id,
                user_id=user_id,
                content=conversational_response,
                retrieved_chunks=[],
            )
            update_conversation_timestamp(conversation_id)
            _write_result(r, job_id, {
                "status":                  "done",
                "answer":                  conversational_response,
                "cached":                  False,
                "voice_url":               None,
                "voice_credits_remaining": _get_voice_credits(user_id),
                "tokens_used":             0,
                "path":                    "conversational",
            })
            return

        # ── Step 1: Cache check (free — Redis) ─────────────────────
        # CONCEPT: User-scoped cache key — different users asking the
        # same question get answers from their own documents.
        cache_key     = _make_cache_key(user_id, query)
        cached_answer = r.get(cache_key)

        if cached_answer:
            print(f"[Handler] Cache hit — 0 tokens consumed")
            _write_result(r, job_id, {
                "status":                  "done",
                "answer":                  cached_answer,
                "cached":                  True,
                "voice_url":               None,
                "voice_credits_remaining": _get_voice_credits(user_id),
                "tokens_used":             0,
                "path":                    "cache",
            })
            return

        # ── Step 2: Save user message ──────────────────────────────
        save_user_message(conversation_id, user_id, query)

        # ── Step 3: Fetch history (free) ───────────────────────────
        history = fetch_conversation_history(conversation_id, user_id)

        # ── Step 4: Acquire router token ───────────────────────────
        # CONCEPT: Router token comes from the dedicated router bucket
        # (SARVAM_API_KEY_ROUTER). Even if the RAG bucket is exhausted,
        # the router bucket is independent — we can always classify.
        # Short timeout (15s) because routing should be near-instant.
        print(f"[Handler] Acquiring router token")
        router_acquired = acquire_router_token(r)

        if not router_acquired:
            print(f"[Handler] Router tokens unavailable — returning to SQS")
            raise Exception("RATE_LIMIT_WAIT")

        # ── Step 5: needs_retrieval() YES/NO ──────────────────────
        # CONCEPT: Uses SARVAM_API_KEY_ROUTER — dedicated quota.
        # Determines whether this query needs document retrieval or
        # can be answered directly from LLM knowledge.
        # Examples that DON'T need retrieval:
        #   "What is 2+2?", "Who invented Python?", "Define recursion"
        # Examples that DO need retrieval:
        #   "What does my PDF say about X?", "Summarise my notes"
        print(f"[Handler] Running needs_retrieval() check")
        retrieval_needed = needs_retrieval(query)
        tokens_used      = 1  # router token consumed

        # ── NO path — direct answer ────────────────────────────────
        if not retrieval_needed:
            print(f"[Handler] NO retrieval — acquiring RAG tokens for direct answer")

            rag_acquired = acquire_generate_tokens(r)
            if not rag_acquired:
                raise Exception("RATE_LIMIT_WAIT")

            answer       = direct_answer(query, history)
            tokens_used += 2

            _finish(
                r=r,
                job_id=job_id,
                query=query,
                answer=answer,
                user_id=user_id,
                conversation_id=conversation_id,
                voice_mode=voice_mode,
                retrieved_chunks=[],
                cache_key=cache_key,
                tokens_used=tokens_used,
                path="direct",
            )
            return

        # ── YES path — full RAG pipeline ───────────────────────────
        print(f"[Handler] YES retrieval — running RAG pipeline")

        # ── Step 6: Direct embed + hybrid search (free) ────────────
        # CONCEPT: Voyage AI is free (200M tokens/month). Supabase
        # hybrid search is free (SQL, HNSW + GIN indexes).
        # We do as much work as possible before spending LLM tokens.
        print(f"[Handler] Embedding query (Voyage AI — free)")
        direct_embedding = embed_query(query)

        print(f"[Handler] Running hybrid search (Supabase — free)")
        candidates = execute_hybrid_search(
            user_id=user_id,
            query_embedding=direct_embedding,
            query_text=query,
            match_count=10,
        )

        print(f"[Handler] Hybrid search: {len(candidates)} candidates")

        # ── Step 7: Handle no results ──────────────────────────────
        if not candidates:
            answer = (
                "I could not find any relevant information in your "
                "documents. Please make sure you have uploaded and "
                "processed documents before asking questions."
            )
            _finish(r, job_id, query, answer, user_id,
                    conversation_id, voice_mode, [], cache_key,
                    tokens_used, "no_results")
            return

        # ── Step 8: Evaluate retrieval confidence (free) ───────────
        top_rrf_score  = candidates[0].get("rrf_score", 0)
        hyde_triggered = False

        print(f"[Handler] Top RRF score: {top_rrf_score:.4f} "
              f"(threshold: {HYDE_CONFIDENCE_THRESHOLD})")

        # ── Step 9: Conditional HyDE (0 or 1 RAG token) ───────────
        # CONCEPT: HyDE fires only when retrieval confidence is low.
        # High RRF score → direct embedding found strong candidates → skip.
        # Low RRF score  → question phrasing far from doc language → HyDE.
        # Uses SARVAM_API_KEY_RAG (not router) — it's a generation call.
        if top_rrf_score < HYDE_CONFIDENCE_THRESHOLD:
            print(f"[Handler] Weak signal — attempting HyDE (RAG bucket)")

            hyde_acquired = acquire_hyde_token(r)

            if hyde_acquired:
                tokens_used += 1
                hyde_embedding, hyp_answer = generate_hyde_embedding(query)

                hyde_candidates = execute_hybrid_search(
                    user_id=user_id,
                    query_embedding=hyde_embedding,
                    query_text=query,    # keep original for BM25 side
                    match_count=10,
                )

                if hyde_candidates:
                    hyde_top = hyde_candidates[0].get("rrf_score", 0)
                    print(f"[Handler] HyDE RRF: {hyde_top:.4f} "
                          f"vs direct: {top_rrf_score:.4f}")

                    if hyde_top > top_rrf_score:
                        candidates     = hyde_candidates
                        hyde_triggered = True
                        print(f"[Handler] HyDE improved retrieval ✅")
                    else:
                        print(f"[Handler] HyDE no improvement — "
                              f"keeping direct results")
            else:
                print(f"[Handler] HyDE token unavailable — "
                      f"proceeding without HyDE")
        else:
            print(f"[Handler] Strong signal — HyDE skipped ✅")

        # ── Step 10: MMR (free — Python) ───────────────────────────
        print(f"[Handler] Running MMR (top_k={MMR_TOP_K})")
        top_chunks = mmr_rerank(
            query_embedding=direct_embedding,
            chunks=candidates,
            top_k=MMR_TOP_K,
            lambda_mult=MMR_LAMBDA,
        )

        print(f"[Handler] MMR selected {len(top_chunks)} chunks "
              f"from pages "
              f"{[c['metadata'].get('page_number') for c in top_chunks]}")

        # ── Step 11: Acquire RAG generation tokens ─────────────────
        # CONCEPT: Non-negotiable — waits up to 45s.
        # If unavailable after 45s → RATE_LIMIT_WAIT → SQS re-queues.
        # Full quality or wait. Never degrade.
        print(f"[Handler] Acquiring {2} RAG generation token(s)")
        generate_acquired = acquire_generate_tokens(r)

        if not generate_acquired:
            print(f"[Handler] RAG tokens unavailable — returning to SQS")
            raise Exception("RATE_LIMIT_WAIT")

        tokens_used += 2

        # ── Step 12: Generate answer (SARVAM_API_KEY_RAG) ──────────
        print(f"[Handler] Generating answer "
              f"(hyde={hyde_triggered}, "
              f"chunks={len(top_chunks)}, "
              f"history={len(history)})")

        answer = generate_answer(
            query=query,
            context_chunks=top_chunks,
            history=history,
        )

        # ── Step 13: Finish ────────────────────────────────────────
        _finish(
            r=r,
            job_id=job_id,
            query=query,
            answer=answer,
            user_id=user_id,
            conversation_id=conversation_id,
            voice_mode=voice_mode,
            retrieved_chunks=top_chunks,
            cache_key=cache_key,
            tokens_used=tokens_used,
            path="rag",
        )

    except Exception as e:
        if "RATE_LIMIT_WAIT" in str(e):
            # Deliberate re-queue — do NOT write error result
            raise

        print(f"[Handler] ❌ Job {job_id} failed: {e}")
        _write_result(r, job_id, {
            "status":  "error",
            "message": str(e),
        })
        raise


# ─────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _finish(
    r:                object,
    job_id:           str,
    query:            str,
    answer:           str,
    user_id:          str,
    conversation_id:  str,
    voice_mode:       bool,
    retrieved_chunks: list[dict],
    cache_key:        str,
    tokens_used:      int = 0,
    path:             str = "rag",
) -> None:
    """
    Post-generation steps — always runs on success.
    Voice, history, cache, result.
    """

    # Voice mode
    voice_url = None
    if voice_mode:
        voice_url = _handle_voice(user_id, answer)

    # Save assistant message to history
    save_assistant_message(
        conversation_id=conversation_id,
        user_id=user_id,
        content=answer,
        retrieved_chunks=retrieved_chunks,
        voice_url=voice_url,
        voice_used=voice_url is not None,
    )

    update_conversation_timestamp(conversation_id)

    # Cache full quality answers only
    r.setex(cache_key, CACHE_TTL, answer)
    print(f"[Handler] Answer cached (TTL={CACHE_TTL}s)")

    _write_result(r, job_id, {
        "status":                  "done",
        "answer":                  answer,
        "cached":                  False,
        "voice_url":               voice_url,
        "voice_credits_remaining": _get_voice_credits(user_id),
        "tokens_used":             tokens_used,
        "path":                    path,
    })

    print(f"[Handler] ✅ Job {job_id} done "
          f"(path={path}, tokens={tokens_used})")


def _handle_voice(user_id: str, answer: str) -> str | None:
    from shared_lambda.supabase_client import consume_voice_credit
    import boto3, base64, uuid
    import requests as req

    credit_consumed = consume_voice_credit(user_id)
    if not credit_consumed:
        print(f"[Handler] Voice: no credits for user {user_id}")
        return None

    try:
        api_key = get_secret("SARVAM_API_KEY_RAG")
        resp    = req.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type":  "application/json"},
            json={"inputs":               [answer[:2500]],
                  "target_language_code": "en-IN",
                  "speaker":             "meera",
                  "model":               "bulbul:v3",
                  "pace":                1.0,
                  "enable_preprocessing": True},
            timeout=30,
        )
        if resp.status_code != 200:
            raise Exception(f"TTS error {resp.status_code}")

        audio  = base64.b64decode(resp.json()["audios"][0])
        s3     = boto3.client("s3")
        key    = f"audio/{user_id}/{uuid.uuid4()}.wav"
        bucket = os.getenv("VOICE_BUCKET_NAME")

        s3.put_object(Bucket=bucket, Key=key,
                      Body=audio, ContentType="audio/wav")

        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=86400,
        )

    except Exception as e:
        print(f"[Handler] Voice TTS failed — refunding credit: {e}")
        from shared_lambda.supabase_client import refund_voice_credit
        refund_voice_credit(user_id)
        return None


def _make_cache_key(user_id: str, query: str) -> str:
    h = hashlib.sha256(query.lower().strip().encode()).hexdigest()
    return f"cache:{user_id}:{h}"


def _write_result(r, job_id: str, result: dict) -> None:
    r.setex(f"job:{job_id}", RESULT_TTL, json.dumps(result))
    print(f"[Handler] Redis result written: "
          f"status={result.get('status')}")


def _get_voice_credits(user_id: str) -> int:
    try:
        result = supabase \
            .schema("rag").table("user_profiles") \
            .select("voice_credits") \
            .eq("id", user_id) \
            .single() \
            .execute()
        return result.data.get("voice_credits", 0) if result.data else 0
    except Exception:
        return 0