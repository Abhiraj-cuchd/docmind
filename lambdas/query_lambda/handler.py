# lambdas/query_lambda/handler.py
#
# Full query pipeline — smart routing + rate limit management.
#
# Routing logic:
#   Step 0: Conversational check   (free — regex)
#   Step 1: Cache check            (free — Redis)
#   Step 2: User has ready docs?   (free — Supabase)
#
#   NO docs:
#     Router token → needs_retrieval YES/NO
#       NO  → direct_answer()
#       YES → retrieval pipeline
#
#   HAS docs — always retrieve:
#     RRF < MIN_USEFUL_RRF  → doc irrelevant → direct_fallback
#     RRF >= MIN_USEFUL_RRF → full RAG pipeline
#
# CONCEPT: Users with documents almost always want answers from
# their material. "What is X?" means "what does my doc say about X?"
# We skip the router when docs exist and let RRF confidence decide
# whether to use RAG or fall back to direct answer.
# Only "What is 2+2?" style queries against an ML doc will score
# near zero RRF and fall through to direct_fallback.

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
RESULT_TTL  = 3600
CACHE_TTL   = 3600
TTS_MAX_CHARS = 500

# CONCEPT: If top RRF score is below this, the direct embedding
# found weak candidates — worth spending one HyDE token to try
# to improve retrieval quality.
# Derived: rank 1 in both lists = 0.0328, rank 1 in one = 0.0164
# 0.02 sits between these.
HYDE_CONFIDENCE_THRESHOLD = 0.02

# CONCEPT: If top RRF score is below this, the document simply
# does not contain relevant content for this query.
# "What is 2+2?" against an ML document scores ~0.0001.
# Fall back to direct LLM answer instead of forcing irrelevant
# document chunks into the generation prompt.
# 0.005 is deliberately low — only filters truly irrelevant queries.
MIN_USEFUL_RRF_SCORE = 0.005

MMR_TOP_K  = 3
MMR_LAMBDA = 0.7

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
    document_id     = _get_conversation_document_id(conversation_id, user_id)

    print(f"[Handler] Job {job_id}: '{query[:80]}'")

    try:
        # ── Step 0: Conversational check (free — regex) ────────────
        # CONCEPT: Greetings and social exchanges handled instantly.
        # Zero tokens, zero latency. Pure Python regex matching.
        # "Hi!", "Thanks", "Bye" never touch any external service.
        conversational_response = get_conversational_response(query)

        if conversational_response:
            print(f"[Handler] Conversational — instant (0 tokens)")
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
        cache_key     = _make_cache_key(user_id, query, document_id)
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

        # ── Step 4: Smart routing decision ─────────────────────────
        # CONCEPT: Two paths depending on document availability.
        #
        # Path A — No ready documents:
        #   Use LLM router (SARVAM_API_KEY_ROUTER) to classify.
        #   Costs 1 router token. General knowledge → direct.
        #   Document question → retrieval (will find nothing, fallback).
        #
        # Path B — Has ready documents:
        #   Skip router entirely. Always attempt retrieval.
        #   RRF confidence score determines final path:
        #     < MIN_USEFUL_RRF → doc irrelevant → direct_fallback
        #     >= MIN_USEFUL_RRF → proceed with RAG pipeline
        #
        # Saves 1 router token on every query when docs exist.
        tokens_used   = 0
        user_has_docs = _user_has_documents(user_id)

        if not user_has_docs:
            # ── Path A: No documents — use LLM router ──────────────
            print(f"[Handler] No ready documents — using LLM router")

            router_acquired = acquire_router_token(r)
            if not router_acquired:
                print(f"[Handler] Router tokens unavailable — SQS requeue")
                raise Exception("RATE_LIMIT_WAIT")

            retrieval_needed = needs_retrieval(query)
            tokens_used      = 1

            if not retrieval_needed:
                print(f"[Handler] Router: NO retrieval — direct answer")

                rag_acquired = acquire_generate_tokens(r)
                if not rag_acquired:
                    raise Exception("RATE_LIMIT_WAIT")

                answer       = direct_answer(query, history)
                tokens_used += 2

                _finish(
                    r=r, job_id=job_id, query=query,
                    answer=answer, user_id=user_id,
                    conversation_id=conversation_id,
                    voice_mode=voice_mode,
                    retrieved_chunks=[], cache_key=cache_key,
                    tokens_used=tokens_used, path="direct",
                )
                return

            print(f"[Handler] Router: YES retrieval")

        else:
            # ── Path B: Has documents — skip router, always retrieve ─
            print(f"[Handler] User has documents — skipping router, "
                  f"always retrieving")

        # ── Step 5: Embed query (free — Amazon Titan) ──────────────
        print(f"[Handler] Embedding query (Titan — free)")
        direct_embedding = embed_query(query)

        # ── Step 6: Hybrid search (free — Supabase HNSW + BM25) ───
        print(f"[Handler] Running hybrid search (Supabase — free)")
        candidates = execute_hybrid_search(
            user_id=user_id,
            query_embedding=direct_embedding,
            query_text=query,
            match_count=10,
            document_id=document_id,
        )

        print(f"[Handler] Hybrid search: {len(candidates)} candidates")

        # ── Step 7: No candidates at all ───────────────────────────
        if not candidates:
            print(f"[Handler] No candidates — direct fallback")

            rag_acquired = acquire_generate_tokens(r)
            if not rag_acquired:
                raise Exception("RATE_LIMIT_WAIT")

            answer       = direct_answer(query, history)
            tokens_used += 2
            _finish(
                r=r, job_id=job_id, query=query,
                answer=answer, user_id=user_id,
                conversation_id=conversation_id,
                voice_mode=voice_mode,
                retrieved_chunks=[], cache_key=cache_key,
                tokens_used=tokens_used, path="direct_fallback",
            )
            return

        # ── Step 8: Check retrieval confidence (free) ──────────────
        top_rrf_score  = candidates[0].get("rrf_score", 0)
        hyde_triggered = False

        print(f"[Handler] Top RRF: {top_rrf_score:.4f} "
              f"(min_useful={MIN_USEFUL_RRF_SCORE}, "
              f"hyde_threshold={HYDE_CONFIDENCE_THRESHOLD})")

        # ── Step 9: RRF below minimum — doc irrelevant to query ────
        # CONCEPT: Score near zero means no chunk in the document
        # is remotely related to this query.
        # "What is 2+2?" against an ML doc scores ~0.0001.
        # Forcing these chunks into the prompt produces hallucinations.
        # Fall back to direct LLM knowledge instead.
        if top_rrf_score < MIN_USEFUL_RRF_SCORE:
            print(f"[Handler] RRF {top_rrf_score:.4f} < "
                  f"MIN_USEFUL {MIN_USEFUL_RRF_SCORE} — "
                  f"document not relevant — direct fallback")

            rag_acquired = acquire_generate_tokens(r)
            if not rag_acquired:
                raise Exception("RATE_LIMIT_WAIT")

            answer       = direct_answer(query, history)
            tokens_used += 2
            _finish(
                r=r, job_id=job_id, query=query,
                answer=answer, user_id=user_id,
                conversation_id=conversation_id,
                voice_mode=voice_mode,
                retrieved_chunks=[], cache_key=cache_key,
                tokens_used=tokens_used, path="direct_fallback",
            )
            return

        # ── Step 10: Conditional HyDE (0 or 1 RAG token) ──────────
        # CONCEPT: RRF is above minimum (doc is relevant) but below
        # HyDE threshold (weak signal). Worth spending one HyDE token
        # to generate a better query vector via hypothetical answer.
        # Uses SARVAM_API_KEY_RAG — it's a generation call.
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
                    document_id=document_id,
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
                print(f"[Handler] HyDE token unavailable — proceeding")
        else:
            print(f"[Handler] Strong signal — HyDE skipped ✅")

        # ── Step 11: MMR diversification (free — Python) ───────────
        print(f"[Handler] Running MMR (top_k={MMR_TOP_K})")
        top_chunks = mmr_rerank(
            query_embedding=direct_embedding,
            chunks=candidates,
            top_k=MMR_TOP_K,
            lambda_mult=MMR_LAMBDA,
        )

        print(f"[Handler] MMR selected {len(top_chunks)} chunks "
              f"pages={[c['metadata'].get('page_number') for c in top_chunks]}")

        # ── Step 12: Acquire generation tokens ─────────────────────
        # CONCEPT: Non-negotiable — waits up to 45s.
        # If unavailable after 45s → RATE_LIMIT_WAIT → SQS requeues.
        # Full quality or wait. Never degrade.
        print(f"[Handler] Acquiring {GENERATE_COST} generation token(s)")
        generate_acquired = acquire_generate_tokens(r)

        if not generate_acquired:
            print(f"[Handler] Generation tokens unavailable — SQS requeue")
            raise Exception("RATE_LIMIT_WAIT")

        tokens_used += 2

        # ── Step 13: Generate answer (SARVAM_API_KEY_RAG) ──────────
        print(f"[Handler] Generating RAG answer "
              f"(hyde={hyde_triggered}, "
              f"chunks={len(top_chunks)}, "
              f"history={len(history)})")

        answer = generate_answer(
            query=query,
            context_chunks=top_chunks,
            history=history,
        )

        # ── Step 14: Finish ────────────────────────────────────────
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
            # Deliberate requeue — do NOT write error result
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

def _user_has_documents(user_id: str) -> bool:
    """
    Returns True if user has at least one ready document.

    CONCEPT: Only 'ready' documents can be searched — processing
    or indexing docs have no embeddings yet. If a user only has
    documents still being embedded, fall through to router-based
    routing until they finish indexing.
    """
    try:
        result = supabase.schema("rag").table("documents") \
            .select("id") \
            .eq("user_id", user_id) \
            .eq("status", "ready") \
            .limit(1) \
            .execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"[Handler] _user_has_documents error: {e} — defaulting False")
        return False


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
    """Post-generation steps — voice, history, cache, result."""

    # Voice mode
    voice_url = None
    voice_urls = None
    if voice_mode:
        voice_urls = _handle_voice(user_id, answer)
        if voice_urls:
            voice_url = voice_urls[0]

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

    # Cache all answers including fallbacks
    # If doc doesn't have 2+2 now, it never will — safe to cache
    r.setex(cache_key, CACHE_TTL, answer)
    print(f"[Handler] Answer cached (TTL={CACHE_TTL}s)")

    _write_result(r, job_id, {
        "status":                  "done",
        "answer":                  answer,
        "cached":                  False,
        "voice_url":               voice_url,
        "voice_urls":              voice_urls,
        "voice_credits_remaining": _get_voice_credits(user_id),
        "tokens_used":             tokens_used,
        "path":                    path,
    })

    print(f"[Handler] ✅ Job {job_id} done "
          f"(path={path}, tokens={tokens_used})")


def _handle_voice(user_id: str, answer: str) -> list[str] | None:
    from shared_lambda.supabase_client import consume_voice_credit
    import boto3, base64, uuid
    import requests as req

    credit_consumed = consume_voice_credit(user_id)
    if not credit_consumed:
        print(f"[Handler] Voice: no credits for user {user_id}")
        return None

    try:
        api_key = get_secret("SARVAM_API_KEY_RAG")
        chunks = _split_tts_chunks(answer, TTS_MAX_CHARS)
        resp    = req.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json={
                "inputs":               chunks,
                "target_language_code": "en-IN",
                "speaker":              "shruti",
                "model":                "bulbul:v3",
                "pace":                 1.15,
                "enable_preprocessing": True,
            },
            timeout=30,
        )

        if resp.status_code != 200:
            raise Exception(f"TTS error {resp.status_code}: {resp.text}")

        audios = resp.json().get("audios", [])
        s3     = boto3.client("s3")
        bucket = os.getenv("VOICE_BUCKET_NAME")
        voice_urls = []

        for index, audio_b64 in enumerate(audios):
            audio  = base64.b64decode(audio_b64)
            key    = f"audio/{user_id}/{uuid.uuid4()}_{index}.wav"

            s3.put_object(
                Bucket=bucket, Key=key,
                Body=audio, ContentType="audio/wav",
            )

            voice_urls.append(
                s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=86400,
                )
            )

        return voice_urls

    except Exception as e:
        print(f"[Handler] Voice TTS failed — refunding credit: {e}")
        from shared_lambda.supabase_client import refund_voice_credit
        refund_voice_credit(user_id)
        return None


def _make_cache_key(user_id: str, query: str, document_id: str | None) -> str:
    h = hashlib.sha256(query.lower().strip().encode()).hexdigest()
    doc_part = document_id or "none"
    return f"cache:{user_id}:{doc_part}:{h}"


def _get_conversation_document_id(conversation_id: str, user_id: str) -> str | None:
    try:
        result = supabase.schema("rag").table("conversations") \
            .select("document_id") \
            .eq("id", conversation_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()
        if not result.data:
            return None
        return result.data.get("document_id")
    except Exception as e:
        print(f"[Handler] _get_conversation_document_id error: {e}")
        return None


def _write_result(r, job_id: str, result: dict) -> None:
    r.setex(f"job:{job_id}", RESULT_TTL, json.dumps(result))
    print(f"[Handler] Redis result written: status={result.get('status')}")


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


def _split_tts_chunks(text: str, max_chars: int) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []

    if len(cleaned) <= max_chars:
        return [cleaned]

    sentences = []
    current = []
    start = 0
    for i, char in enumerate(cleaned):
        if char in ".!?" and i + 1 < len(cleaned) and cleaned[i + 1] == " ":
            sentences.append(cleaned[start:i + 1])
            start = i + 2
    if start < len(cleaned):
        sentences.append(cleaned[start:])

    chunks = []
    buffer = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            while sentence:
                chunks.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            buffer = ""
            continue

        if not buffer:
            buffer = sentence
            continue

        if len(buffer) + 1 + len(sentence) <= max_chars:
            buffer = f"{buffer} {sentence}"
        else:
            chunks.append(buffer)
            buffer = sentence

    if buffer:
        chunks.append(buffer)

    return chunks