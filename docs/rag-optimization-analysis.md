 # RAG Pipeline Optimization Analysis

The root complaint — answers are precise but not explanatory — traces to multiple interacting problems across the full pipeline. This document works through each layer with specific code references.

---

## 1. System Prompt & Generation

This is the most direct cause of terse answers, and the easiest to fix.

### The "Be concise" instruction fights explanatory answers

`sarvam.py:221` — the generation prompt ends with `"Be concise and specific"`. This is a direct instruction to be brief. Users who upload lecture notes or research papers want elaborated explanations, not one-liner summaries. The model is doing exactly what it's told.

The rule also has no context-sensitivity. "What is backpropagation?" and "What's the deadline?" are both answered with the same brevity directive, even though the first clearly warrants explanation and the second does not.

**What to change:** Replace "Be concise and specific" with guidance that rewards depth when the context supports it. Something like: "Answer thoroughly — explain concepts, provide background from the document, and give examples if the context contains them. Use bullet points or structure only when it genuinely aids clarity."

### Temperature 0.3 suppresses elaboration

`sarvam.py:61` — `temperature=0.3` is configured for factual retrieval tasks. At this temperature the model maximizes token probability, which produces safe, minimal responses. The model picks the most statistically likely next token at every step, and in RAG fine-tuning, that correlates with concise restatements of the retrieved text rather than elaborated explanations.

The `direct_answer()` path uses `temperature=0.5`, which is already more expressive. The RAG path at 0.3 is actually configured more conservatively than the no-context path.

**What to change:** Raise to `0.5–0.6` for the RAG path. The context chunks anchor the model to the document, so the risk of hallucination at higher temperature is largely neutralized — the retrieved chunks are already in the prompt.

### The prompt structure buries the question

`sarvam.py:201-222` — The prompt order is: system instruction → history → context chunks → question. This is correct per attention locality, but the instruction block (`Rules:`) lists constraints without giving the model a persona or tone. There's no instruction about *how* to answer, only what *not* to do (don't fabricate, cite the chunk). A model given only negative constraints defaults to minimal output.

Contrast with a persona-first approach: "You are a knowledgeable tutor helping a student understand the documents they uploaded. When a concept appears in the document, explain it fully — what it is, why it matters, and how it connects to the surrounding content." This frames the task as teaching rather than retrieval.

### History is injected as plain text, not as conversation structure

`sarvam.py:235-240` — History is formatted as `"User: ...\nAssistant: ..."` plain text blocks rather than proper `messages` array format. This works but loses the structural signal. More importantly: the history isn't used to *reformulate the query* before retrieval. If a user asks "How does it work?" after discussing gradient descent, the query sent to the embedding and hybrid search is still literally "How does it work?" — not "How does gradient descent work?". This is the **query compression gap** and it directly causes poor retrieval on follow-up questions.

**What to change:** Before embedding and searching, run a lightweight LLM call that rewrites the query using history context. This can reuse the existing router token budget since it's a small classification/rewriting call. The result is used for retrieval; the original query stays in the generation prompt. Only trigger this rewrite when history exists and the query contains pronouns or short follow-ups.

---

## 2. Chunking & Data Quality

### Chunk size is small for explanatory content

`chunker.py:52` — `chunk_size=400, chunk_overlap=100`. At 400 characters (roughly 80–100 words), a chunk can hold one to two paragraphs at best. For academic or technical PDFs, a complete explanation of a concept often spans 200–400 words — meaning a concept can be split across two chunks. The overlap at 100 characters (25 words) may not be enough to preserve the conceptual thread across the boundary.

The comment in the code (`"chunk_size=500 → best default"`) contradicts the actual setting of 400. This looks like a tuning regression. The semantic quality of retrieved content depends heavily on chunks being self-contained units, and at 400 chars many chunks are partial thoughts.

**What to change:** Increase to `chunk_size=600–800` with `chunk_overlap=150–200`. This trades chunk count (storage) for semantic completeness. The Titan V2 model supports up to 8192 tokens — there is no model-side reason to stay at 400 chars.

### Headers, footers, and page numbers pollute chunks

`extractor.py:161` — `page.get_text("text")` extracts everything in reading order with no filtering. Academic PDFs consistently include page headers ("Chapter 3: Neural Networks"), footers ("Confidential — Do Not Distribute"), running page numbers, and section dividers. These get embedded into the same chunks as content.

When a chunk contains `"3.2 Activation Functions\n\n14\n\nSigmoid saturates at..."`, the heading and page number occupy significant character space and bias the embedding toward document structure rather than semantic content. A search for "sigmoid function" may retrieve a chunk that is mostly heading and page number with only partial conceptual content.

**What to change:** Add a cleaning pass in `chunker.py` before the splitter runs. Strip standalone page numbers (`^\d+$`), repeated header/footer text, and excessive whitespace. PyMuPDF provides `page.get_text("blocks")` which returns text with block-level coordinates — headers and footers have characteristic y-positions that can be filtered before passing to the chunker.

### Tables are extracted as whitespace-delimited text

`extractor.py:175` — Tables are detected heuristically via `\t` characters or repeated spaces, but their content is extracted as raw text. A 3-column table like:

```
Algorithm  Complexity  Use Case
K-Means    O(nkt)      Clustering
SVM        O(n²)       Classification
```

gets extracted as a single text block that is nearly incomprehensible when chunked mid-table or embedded as text. Queries like "what's the complexity of K-Means?" may fail to retrieve this because the text form doesn't align well with the query embedding.

**What to change:** When `has_tables=True`, consider using PyMuPDF's `page.get_text("html")` or `page.find_tables()` (available in PyMuPDF 1.23+) to extract tables as structured Markdown before chunking. A Markdown table embeds much better than whitespace-delimited columns because the column semantics are preserved.

### Chunks have no section context

`chunker.py:146` — Chunk metadata includes page number, filename, and position, but not section title. When the retrieval surfaces "...the algorithm converges when the loss function reaches a local minimum...", neither the model nor the user knows if this is from the "Gradient Descent" section or the "Convergence Proofs" section. This reduces the model's ability to correctly contextualize the chunk in its answer.

**What to change:** During extraction, detect headings (PyMuPDF can identify them via font size / boldness from `page.get_text("dict")`). Store the current section heading in chunk metadata. Prepend it to the chunk content during ingestion: `"[Section: Gradient Descent]\n\n{chunk_text}"`. This enriches the embedding vector with topical context and gives the generation model explicit provenance information.

---

## 3. Embedding Quality

### Titan V2 doesn't support asymmetric query/document embeddings

`embedder.py:104` and `hyde.py:79` — Both document ingestion and query embedding call `_embed_single` with the same parameters. Amazon Titan V2 is a symmetric model: queries and documents are embedded the same way, in the same space. The core problem this creates is that "explain the intuition behind backprop" and "backpropagation computes gradients via the chain rule" land in different regions of that space — one is a question, one is an answer — but Titan treats both as plain text with no instruction about their role.

Asymmetric embedding models solve this by training separate representations for queries and documents, so a query vector is specifically optimized to point toward answer text rather than toward other questions. This is the single most impactful embedding-level change available, and it is a largely mechanical swap in `embedder.py` and `hyde.py`.

Voyage AI was previously evaluated but hit character rate limits on the free tier. The alternatives below support proper asymmetric embeddings and are viable on AWS Lambda.

**Cohere Embed v3 (`embed-english-v3.0`)**

Supports `input_type="search_query"` vs `input_type="search_document"` — purpose-built for RAG asymmetry. Quality is on par with Voyage on MTEB retrieval benchmarks. Pricing is $0.10/1M tokens which at typical RAG document volumes (1-5M tokens/month) is effectively negligible. Rate limits: 10,000 API calls/minute on the production tier, which is high enough that ingestion would never hit it. The API is a standard REST call — the change to `embedder.py` is under 20 lines.

**OpenAI `text-embedding-3-large`**

3072 dimensions natively (can be truncated to 1024 to match the existing schema without re-ingesting). Does not have explicit `input_type` differentiation, but the model scores highest on MTEB retrieval benchmarks among API-available models and the representation quality compensates for the lack of explicit asymmetry. `text-embedding-3-small` is significantly cheaper ($0.02/1M tokens) and still outperforms Titan V2 on retrieval tasks. If embedding quality is the bottleneck and you want the simplest swap, this is the lowest-friction option — it has no meaningful rate limits on paid tiers.

**Google `text-embedding-004` via Vertex AI**

Supports explicit `task_type="RETRIEVAL_QUERY"` vs `task_type="RETRIEVAL_DOCUMENT"` asymmetry — the most explicit API-level support for this distinction. 768 dimensions (would require schema change: `VECTOR(768)` and re-ingestion of all documents). The model ranks highly on retrieval benchmarks. Vertex AI is not AWS-native, so it adds a cross-cloud dependency to Lambda, which complicates IAM and cold start slightly. Not the first choice given the existing AWS setup, but worth noting as the cleanest API design for this use case.

**Jina Embeddings v3 (`jina-embeddings-v3`)**

Supports `task="retrieval.query"` vs `task="retrieval.passage"`. 1024 dimensions natively — a zero-schema-change swap. Free tier is 1M tokens/month; paid tiers have no documented rate limit ceiling that would cause the same issue as Voyage. Quality is slightly below Cohere and OpenAI on MTEB but well above Titan V2.

**Staying on Titan V2: instruction prefix workaround**

If a model swap is not feasible right now, a partial mitigation exists: prepend instruction text to queries before embedding them. Models trained on diverse instruction data (which Titan V2 partially is) respond to this. For documents at ingestion: no prefix needed. For queries at retrieval: prepend `"Represent this question for searching relevant passages: "` before calling `_embed_text`. This is borrowed from the E5 and Instructor embedding literature and provides a lightweight asymmetric signal without changing the model. It won't close the gap with a purpose-trained asymmetric model, but it measurably improves retrieval on conceptual queries.

**Recommendation given the existing setup:** Cohere Embed v3 is the most practical swap. Same 1024 dimensions (no re-ingestion needed beyond a one-time re-index), proper asymmetric training, REST API from Lambda, and rate limits are not a practical concern at any reasonable document scale on the paid tier.

### Short query truncation in HyDE

`hyde.py:105-110` — The HyDE prompt asks for a "2-3 sentence passage." For broad queries like "explain neural networks," this works. For narrow factual queries ("what is the F1 score formula?"), 2-3 sentences of HyDE output will be generic knowledge rather than domain-specific content calibrated to the user's actual document. The HyDE approach works best when the hypothetical answer closely resembles text that would appear in the document — which requires the prompt to ask for content in the same style as the document.

**What to change:** Thread the document's title or topic into the HyDE prompt if available in metadata. "Write a passage from a machine learning textbook that answers: {query}" produces better HyDE embeddings than a generic "write a passage that answers this."

---

## 4. Retrieval Strategy

### `plainto_tsquery` doesn't support phrase or proximity matching

`006_functions.sql:42` — The keyword side of hybrid search uses `plainto_tsquery('english', query_text)`, which tokenizes and stems the input but treats all terms as `AND` with no proximity awareness. `websearch_to_tsquery` supports quoted phrases, OR, and negation, which would allow queries like "gradient descent" (as a phrase) to correctly prioritize chunks where those words are adjacent rather than scattered. For technical terms that are multi-word concepts, this is a meaningful difference.

Additionally, `ts_rank` (used at line 42) doesn't account for positional density — `ts_rank_cd` (cover density) adds position-awareness, ranking chunks where query terms are clustered over chunks where they're spread across a page. For concept explanations where the key terms appear in a tight passage, `ts_rank_cd` would surface them more reliably.

### match_count=10 may under-sample when documents are large

`handler.py:228` — The hybrid search fetches 10 candidates before MMR selects 3. The pipeline retrieves 10 candidates from potentially hundreds of chunks, then applies MMR diversity selection on those 10. If the most relevant chunk is at rank 11 (just outside the window), it's permanently excluded. For large documents (50+ pages → 150+ chunks), 10 candidates is a narrow window.

**What to change:** Increase `match_count` to 15-20. The hybrid search SQL already applies a per-CTE LIMIT 20 before the RRF merge, so increasing match_count to 20 would align the retrieval and return windows. The MMR computation is pure Python and fast at these scales.

### MMR uses pure Python cosine similarity over 1024-dim vectors

`mmr.py:196-204` — The cosine similarity function iterates over 1024 floats in Python:

```python
dot_product = sum(float(a) * float(b) for a, b in zip(vec_a, vec_b))
magnitude_a = math.sqrt(sum(float(a) * float(a) for a in vec_a))
```

With 10 candidates and 3 selection rounds, this is 30 cosine computations × 1024 dimensions each, all in pure Python. numpy would execute this as a single vectorized C operation. At current scale this adds measurable latency (~50-100ms) that is entirely avoidable.

**What to change:** `numpy.dot` and `numpy.linalg.norm` replace the inner loops. Since vectors are already normalized by Titan (`normalize=True`), the cosine similarity simplifies to just the dot product, removing the magnitude computation entirely.

### RRF k=60 is a sane default but it's not tuned

`006_functions.sql:54` — The RRF formula uses a constant k=60 in both COALESCE terms. The k parameter controls how steeply rank 1 is preferred over rank 2. At k=60, rank 1 scores 1/61 ≈ 0.0164 and rank 2 scores 1/62 ≈ 0.0161 — very close. This means the fusion doesn't heavily penalize being rank 2 vs rank 1 in either retrieval list. For short-tail queries where the correct answer is clearly rank 1 in one list, lowering k (e.g., k=30) would more strongly reward that signal. This is a micro-tuning but worth noting.

---

## 5. Latency

The query pipeline is entirely sequential. Every step waits for the previous one before starting. Several of these dependencies are artificial.

### Three Supabase calls before work starts

At the start of `_process_record`:
1. `_get_conversation_document_id` — fetches `document_id` from conversations table
2. Cache check in Redis (fast, acceptable)
3. `_user_has_documents` — fetches whether user has ready documents

These two Supabase calls happen sequentially, but neither depends on the other. They can be parallelized using `concurrent.futures.ThreadPoolExecutor`. Combined they add ~100-150ms that could be reduced to the time of the slower one.

### `save_user_message` and `fetch_conversation_history` are sequential

`handler.py:159-162` — Save user message, then fetch history. Both are Supabase writes/reads. Neither needs the other's result. Running them concurrently would save ~50-80ms on every non-cached query.

### MMR cosine loops (already noted above)

~50-100ms removed by switching to numpy.

### HyDE adds a full serial LLM round-trip

When triggered, HyDE adds one Sarvam AI call (~1-2s) plus one Bedrock embedding call (~150ms) in series before the second hybrid search. The current threshold (`HYDE_CONFIDENCE_THRESHOLD = 0.02`) fires on any query where the top RRF score is between 0.005 and 0.02. This is a significant latency spike on ~20-30% of queries (depending on document and query mix).

The HyDE benefit is real but calibrating the threshold more conservatively (raising it slightly to avoid triggering on marginally weak signals) reduces the latency spike frequency without meaningfully sacrificing retrieval quality.

### Ingestion embedder is fully serial

`embedder.py:46-49` — `embed_chunks` embeds one chunk at a time sequentially. 600 chunks × ~100ms/chunk = 60 seconds. ThreadPoolExecutor with 10-20 workers would cut this to 6-10 seconds. Bedrock has no rate limits, so the only bottleneck is network I/O, which parallelizes well.

### TTS S3 uploads are serial

`handler.py:519-532` — Voice audio chunks are uploaded to S3 one at a time. Multiple WAV files could be uploaded in parallel with ThreadPoolExecutor since each upload is independent.

---

## 6. Serving Local Embedding Models Without EC2

The core constraint is that Lambda can't run a 1.3GB model. Two SageMaker options let you deploy models without managing EC2 instances.

### SageMaker Serverless Inference

Truly serverless — you define a memory allocation and maximum concurrency, SageMaker provisions containers on demand and scales to zero when idle. No instances to manage or pay for when unused.

**Deploying bge-large-en-v1.5 to a serverless endpoint:**

```python
# run once, from a local script or CI — not from Lambda
from sagemaker.huggingface import HuggingFaceModel
from sagemaker.serverless import ServerlessInferenceConfig
import sagemaker

role = "arn:aws:iam::YOUR_ACCOUNT:role/SageMakerExecutionRole"

huggingface_model = HuggingFaceModel(
    env={
        "HF_MODEL_ID": "BAAI/bge-large-en-v1.5",
        "HF_TASK":     "feature-extraction",
    },
    role=role,
    transformers_version="4.37",
    pytorch_version="2.1",
    py_version="py310",
)

predictor = huggingface_model.deploy(
    serverless_inference_config=ServerlessInferenceConfig(
        memory_size_in_mb=3072,   # 3GB — model is 1.3GB, needs headroom
        max_concurrency=10,
    ),
    endpoint_name="bge-large-embedding",
)
```

**Calling it from Lambda (replaces `_embed_single` in `embedder.py`):**

```python
import boto3, json

_sm_runtime = boto3.client("sagemaker-runtime", region_name="ap-south-1")

def embed_text_bge(text: str) -> list[float]:
    response = _sm_runtime.invoke_endpoint(
        EndpointName="bge-large-embedding",
        ContentType="application/json",
        Body=json.dumps({"inputs": text[:8000]}),
    )
    result = json.loads(response["Body"].read())
    # feature-extraction returns [[[token_embeddings...]]] — mean pool across tokens
    token_vecs = result[0]  # shape: [seq_len, 1024]
    pooled = [sum(v[i] for v in token_vecs) / len(token_vecs) for i in range(1024)]
    return pooled
```

Note: for production you'd use numpy for the mean pool. The above is illustrative.

For query embeddings, prepend the instruction prefix to get asymmetric behaviour:

```python
def embed_query_bge(query: str) -> list[float]:
    prefixed = f"Represent this sentence for searching relevant passages: {query}"
    return embed_text_bge(prefixed)

def embed_document_bge(text: str) -> list[float]:
    return embed_text_bge(text)   # no prefix for documents
```

### The Cold Start Problem

SageMaker Serverless has a cold start of **5–15 seconds** after a period of inactivity. This is acceptable for the ingestion pipeline (async, latency-tolerant) but will cause visible delay on the first user query after an idle period.

**Mitigation:** An EventBridge rule running every 5 minutes that invokes a Lambda to send a dummy embedding request keeps the container warm at negligible cost (~8,640 pings/month × $0.000015/call = $0.13/month in compute, plus free-tier Lambda invocations).

### SageMaker Asynchronous Inference — better fit for ingestion

For the ingestion pipeline specifically, SageMaker Async Inference is a better match than Serverless:

- Requests go into an S3 input queue; results write to S3 output — fits the existing async pattern
- Auto-scales to **zero instances** when no requests are pending (unlike real-time endpoints that stay up)
- Supports larger payloads and longer timeouts (up to 1 hour) — useful for bulk chunk embedding
- No cold-start penalty since ingestion already happens asynchronously

The ingestion Lambda sends a batch of chunks to the async endpoint; a completion SNS notification writes results back. This is architecturally cleaner than per-chunk synchronous calls.

**Split serving strategy:** Because bge-large on SageMaker and bge-large on Together AI load the same model weights, vectors produced by both are identical and interchangeable in the same VECTOR(1024) column. This means:

- **Ingestion** → SageMaker Async Endpoint (no cold start concern, batches well)
- **Query path** → Together AI API (synchronous, no cold start, ~30ms latency)

Both use bge-large-en-v1.5, same weights, fully compatible vectors.

---

## 7. Multi-Model Setup Cost Analysis

**Assumed workload per user:**
- 25 documents × 100 pages = 2,500 pages
- ~7 chunks/page × 100 tokens/chunk = 1.75M ingestion tokens
- 1,000 queries × 25 tokens = 25K query tokens
- 300 HyDE triggers × 200 tokens = 60K HyDE embedding tokens
- Total embedding tokens: ~1.835M

### Option A — Current Setup (baseline)

| Component | Model | Cost |
|---|---|---|
| All embeddings | Amazon Titan V2 (Bedrock, IAM auth) | $0 |
| HyDE generation | Sarvam AI (rate-limited bucket) | included in Sarvam plan |
| Answer generation | Sarvam AI | included in Sarvam plan |
| **Per-user embedding cost** | | **$0** |

No embedding cost, but Sarvam rate limits cause SQS requeue latency and HyDE competes for the same token bucket as answer generation.

### Option B — bge-large on Together AI + Nova Micro HyDE

| Component | Model | Rate | Per-user cost |
|---|---|---|---|
| Ingestion embeddings | bge-large-en-v1.5 (Together AI) | $0.008/1M tokens | $0.014 |
| Query embeddings | bge-large-en-v1.5 (Together AI) | $0.008/1M tokens | $0.0002 |
| HyDE embeddings | bge-large-en-v1.5 (Together AI) | $0.008/1M tokens | $0.0005 |
| HyDE generation | Amazon Nova Micro (Bedrock) | $0.000035/1K in, $0.00014/1K out | $0.007 |
| **Total** | | | **~$0.022/user** |

For 100 users: **~$2.20**

HyDE no longer consumes from the Sarvam token bucket — the `HYDE_COST` from `rate_limiter.py` can be removed entirely, freeing the full bucket for answer generation. HyDE can also be triggered more aggressively (lower the threshold) since its marginal cost is now $0.007 per 1,000 calls.

### Option C — bge-large on SageMaker Serverless + Nova Micro HyDE

SageMaker Serverless: $0.00001667/GB-second. bge-large needs 3GB, takes ~300ms per call.
Cost per embedding call: 3 × 0.3 × $0.00001667 = **$0.000015/call**

| Component | Calls per user | Cost |
|---|---|---|
| Ingestion (17,500 chunks) | 17,500 | $0.26 |
| Query embeddings (1,000) | 1,000 | $0.015 |
| HyDE embeddings (300) | 300 | $0.005 |
| HyDE generation (Nova Micro) | 300 | $0.007 |
| Warm-keep pings (shared, ~8,640/mo) | — | $0.13/mo flat |
| **Total** | | **~$0.29/user** |

For 100 users: **~$29 + $0.13/mo fixed**

More expensive than Together AI but all traffic stays in your AWS VPC — relevant if your documents contain sensitive content and you want no data leaving the account.

### Option D — Split: SageMaker Async for ingestion + Together AI for queries

| Component | Model | Serving | Per-user cost |
|---|---|---|---|
| Ingestion embeddings | bge-large | SageMaker Async (scales to zero) | ~$0.26 one-time |
| Query + HyDE embeddings | bge-large | Together AI API | $0.0007 |
| HyDE generation | Nova Micro | Bedrock | $0.007 |
| **Total** | | | **~$0.27 ingestion + $0.008/1K queries** |

Same vector space (identical model weights), fully compatible. Trade-off: ingestion costs more than Together AI but avoids external data egress for document content.

### Comparison Summary

| Option | Per-user total | 100-user total | Cold start risk | Data egress |
|---|---|---|---|---|
| A — Current (Titan V2) | $0 | $0 | None | Minimal (Sarvam) |
| B — Together AI + Nova Micro | $0.022 | $2.20 | None | Embeddings leave AWS |
| C — SageMaker Serverless | $0.29 | $29 | Yes (5–15s) | None |
| D — SageMaker Async + Together AI queries | $0.27 ingestion | ~$27 + $0.008/1K queries | Ingestion only | Query text only |

At the 100-user scale, Option B is the pragmatic choice: negligible cost, no cold-start risk, and the quality improvement from bge-large's asymmetric instruction prefix over Titan V2 is immediate. Option C becomes more attractive at higher user counts where the fixed SageMaker warm-keep overhead amortizes across more embeddings, or when document confidentiality requires full AWS data residency.

---

## Summary of Highest-Leverage Changes

In rough order of impact on user-visible answer quality:

1. **Fix the generation prompt** — remove "Be concise", add a teaching persona, raise temperature to 0.5-0.6. This directly addresses the complaint and takes 10 minutes.

2. **Add contextual query rewriting** — use history to expand short follow-up queries before embedding. Fixes poor retrieval on multi-turn conversations.

3. **Increase chunk size to 600-800** — makes chunks semantically self-contained. Clean headers/footers before chunking.

4. **Raise match_count to 20** — broader candidate set before MMR selection.

5. **Use numpy in MMR** — pure latency fix, no quality tradeoff.

6. **Parallelize early Supabase calls** — save 100-150ms per query.

7. **Add section headings to chunk content** — enriches both embedding and generation context.

8. **Switch keyword side to `websearch_to_tsquery` + `ts_rank_cd`** — better phrase and proximity handling for technical queries.
