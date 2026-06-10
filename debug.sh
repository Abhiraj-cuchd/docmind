#!/bin/bash
# =============================================================
# Lambda Debug Commands
# Usage: ./debug.sh [lambda_name] [minutes_ago]
# Example: ./debug.sh processor 10
#          ./debug.sh all 5
# =============================================================

REGION="ap-south-1"

# ─────────────────────────────────────────────────────────────
# INDIVIDUAL LAMBDA LOG COMMANDS
# ─────────────────────────────────────────────────────────────

# ── Processor (RAG pipeline) ───────────────────────────────────
alias logs-processor='aws logs tail /aws/lambda/rag-processor \
  --region ap-south-1 --since 10m --follow'

# ── Submit (POST /query, POST /upload, GET /document-url) ──────
alias logs-submit='aws logs tail /aws/lambda/rag-submit \
  --region ap-south-1 --since 10m --follow'

# ── Poll (GET /result/:jobId) ───────────────────────────────────
alias logs-poll='aws logs tail /aws/lambda/rag-poll \
  --region ap-south-1 --since 10m --follow'

# ── Indexer (PDF → chunks → store) ─────────────────────────────
alias logs-indexer='aws logs tail /aws/lambda/rag-indexer \
  --region ap-south-1 --since 10m --follow'

# ── Embed Worker (Titan embedding) ─────────────────────────────
alias logs-embed='aws logs tail /aws/lambda/rag-embed-worker \
  --region ap-south-1 --since 10m --follow'

# ── Generation (summarize / flashcards via NVIDIA Nemotron) ────
alias logs-generation='aws logs tail /aws/lambda/rag-generation \
  --region ap-south-1 --since 10m --follow'


# =============================================================
# COPY-PASTE VERSIONS (no alias needed)
# =============================================================

# ── Last 10 minutes ────────────────────────────────────────────

# Processor
aws logs tail /aws/lambda/rag-processor \
  --region ap-south-1 --since 10m

# Submit
aws logs tail /aws/lambda/rag-submit \
  --region ap-south-1 --since 10m

# Poll
aws logs tail /aws/lambda/rag-poll \
  --region ap-south-1 --since 10m

# Indexer
aws logs tail /aws/lambda/rag-indexer \
  --region ap-south-1 --since 10m

# Embed Worker
aws logs tail /aws/lambda/rag-embed-worker \
  --region ap-south-1 --since 10m


# =============================================================
# FILTERED LOG COMMANDS
# =============================================================

# ── Processor — errors only ────────────────────────────────────
aws logs tail /aws/lambda/rag-processor \
  --region ap-south-1 --since 10m \
  | grep -i "error\|failed\|exception\|traceback"

# ── Processor — voice only ─────────────────────────────────────
aws logs tail /aws/lambda/rag-processor \
  --region ap-south-1 --since 10m \
  | grep -i "voice\|tts\|credit\|audio"

# ── Processor — routing decisions ──────────────────────────────
aws logs tail /aws/lambda/rag-processor \
  --region ap-south-1 --since 10m \
  | grep -i "router\|retrieval\|rrf\|hyde\|path\|token"

# ── Processor — specific job ID ────────────────────────────────
aws logs tail /aws/lambda/rag-processor \
  --region ap-south-1 --since 30m \
  | grep "YOUR_JOB_ID_HERE"

# ── Submit — errors only ───────────────────────────────────────
aws logs tail /aws/lambda/rag-submit \
  --region ap-south-1 --since 10m \
  | grep -i "error\|failed\|exception"

# ── Submit — upload requests ───────────────────────────────────
aws logs tail /aws/lambda/rag-submit \
  --region ap-south-1 --since 10m \
  | grep -i "upload\|presign\|document-url\|s3"

# ── Indexer — errors only ──────────────────────────────────────
aws logs tail /aws/lambda/rag-indexer \
  --region ap-south-1 --since 10m \
  | grep -i "error\|failed\|exception"

# ── Indexer — progress tracking ────────────────────────────────
aws logs tail /aws/lambda/rag-indexer \
  --region ap-south-1 --since 10m \
  | grep -i "chunk\|extract\|step\|enqueue\|status"

# ── Embed Worker — errors only ─────────────────────────────────
aws logs tail /aws/lambda/rag-embed-worker \
  --region ap-south-1 --since 10m \
  | grep -i "error\|failed\|rate.limit\|throttl"

# ── Embed Worker — batch progress ──────────────────────────────
aws logs tail /aws/lambda/rag-embed-worker \
  --region ap-south-1 --since 10m \
  | grep -i "batch\|embed\|chunk\|ready"

# ── Generation — all ────────────────────────────────────────────
aws logs tail /aws/lambda/rag-generation \
  --region ap-south-1 --since 10m

# ── Generation — errors only ────────────────────────────────────
aws logs tail /aws/lambda/rag-generation \
  --region ap-south-1 --since 10m \
  | grep -i "error\|failed\|exception\|traceback"

# ── Generation — task progress ──────────────────────────────────
aws logs tail /aws/lambda/rag-generation \
  --region ap-south-1 --since 10m \
  | grep -i "task_type\|job_id\|summarize\|flashcard\|done\|rate_limit"

# ── Generation — NVIDIA rate limit hits ────────────────────────
aws logs tail /aws/lambda/rag-generation \
  --region ap-south-1 --since 30m \
  | grep -i "nvidia\|rate_limit\|RATE_LIMIT_WAIT\|requeue"


# =============================================================
# ALL LAMBDAS AT ONCE
# =============================================================

echo "=== PROCESSOR ===" && \
aws logs tail /aws/lambda/rag-processor \
  --region ap-south-1 --since 5m && \
echo "=== SUBMIT ===" && \
aws logs tail /aws/lambda/rag-submit \
  --region ap-south-1 --since 5m && \
echo "=== POLL ===" && \
aws logs tail /aws/lambda/rag-poll \
  --region ap-south-1 --since 5m && \
echo "=== INDEXER ===" && \
aws logs tail /aws/lambda/rag-indexer \
  --region ap-south-1 --since 5m && \
echo "=== EMBED WORKER ===" && \
aws logs tail /aws/lambda/rag-embed-worker \
  --region ap-south-1 --since 5m && \
echo "=== GENERATION ===" && \
aws logs tail /aws/lambda/rag-generation \
  --region ap-south-1 --since 5m


# =============================================================
# CLOUDWATCH INSIGHTS QUERIES (for deeper debugging)
# Run these in AWS Console → CloudWatch → Logs Insights
# =============================================================

# ── All errors across all lambdas in last 1 hour ───────────────
# Log groups to select:
#   /aws/lambda/rag-processor
#   /aws/lambda/rag-submit
#   /aws/lambda/rag-poll
#   /aws/lambda/rag-indexer
#   /aws/lambda/rag-embed-worker
#
# Query:
# fields @timestamp, @logStream, @message
# | filter @message like /ERROR|error|Exception|failed/
# | sort @timestamp desc
# | limit 50

# ── Processor — slow queries (>10s) ───────────────────────────
# Log group: /aws/lambda/rag-processor
#
# Query:
# fields @timestamp, @duration, @message
# | filter @type = "REPORT"
# | filter @duration > 10000
# | sort @duration desc
# | limit 20

# ── Job success rate ───────────────────────────────────────────
# Log group: /aws/lambda/rag-processor
#
# Query:
# fields @timestamp, @message
# | filter @message like /Job.*done|Job.*failed/
# | stats count() by bin(5m)

# ── Generation task outcomes ───────────────────────────────────
# Log group: /aws/lambda/rag-generation
#
# Query:
# fields @timestamp, @message
# | filter @message like /task_type|done|error|RATE_LIMIT_WAIT/
# | sort @timestamp desc
# | limit 50

# ── Generation slow tasks (>60s) ──────────────────────────────
# Log group: /aws/lambda/rag-generation
#
# Query:
# fields @timestamp, @duration, @message
# | filter @type = "REPORT"
# | filter @duration > 60000
# | sort @duration desc
# | limit 20

# ── NVIDIA rate limit wait events ─────────────────────────────
# Log groups:
#   /aws/lambda/rag-generation
#
# Query:
# fields @timestamp, @message
# | filter @message like /RATE_LIMIT_WAIT|nvidia|requeue/
# | sort @timestamp desc
# | limit 30


# =============================================================
# SQS QUEUE STATUS
# =============================================================

# ── Check ingestion queue depth ────────────────────────────────
aws sqs get-queue-attributes \
  --region ap-south-1 \
  --queue-url $(aws sqs get-queue-url \
    --region ap-south-1 \
    --queue-name rag-ingestion-queue \
    --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessages \
    ApproximateNumberOfMessagesNotVisible \
    ApproximateNumberOfMessagesDelayed

# ── Check query queue depth ────────────────────────────────────
aws sqs get-queue-attributes \
  --region ap-south-1 \
  --queue-url $(aws sqs get-queue-url \
    --region ap-south-1 \
    --queue-name rag-query-queue \
    --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessages \
    ApproximateNumberOfMessagesNotVisible

# ── Check embed queue depth ────────────────────────────────────
aws sqs get-queue-attributes \
  --region ap-south-1 \
  --queue-url $(aws sqs get-queue-url \
    --region ap-south-1 \
    --queue-name rag-embed-queue \
    --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessages \
    ApproximateNumberOfMessagesNotVisible

# ── Check tasks queue depth (generation jobs) ──────────────────
aws sqs get-queue-attributes \
  --region ap-south-1 \
  --queue-url $(aws sqs get-queue-url \
    --region ap-south-1 \
    --queue-name rag-tasks-queue \
    --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessages \
    ApproximateNumberOfMessagesNotVisible \
    ApproximateNumberOfMessagesDelayed

# ── Check DLQ message counts ───────────────────────────────────
for queue in rag-ingestion-dlq rag-query-dlq rag-embed-dlq rag-tasks-dlq; do
  echo "=== $queue ==="
  aws sqs get-queue-attributes \
    --region ap-south-1 \
    --queue-url $(aws sqs get-queue-url \
      --region ap-south-1 \
      --queue-name $queue \
      --query QueueUrl --output text 2>/dev/null) \
    --attribute-names ApproximateNumberOfMessages \
    2>/dev/null || echo "Queue not found"
done


# =============================================================
# LAMBDA FUNCTION STATUS
# =============================================================

# ── Check all lambda last modified + runtime ───────────────────
for fn in rag-processor rag-submit rag-poll rag-indexer rag-embed-worker rag-generation; do
  echo "=== $fn ==="
  aws lambda get-function-configuration \
    --region ap-south-1 \
    --function-name $fn \
    --query '{
      State: State,
      LastModified: LastModified,
      Runtime: Runtime,
      MemorySize: MemorySize,
      Timeout: Timeout,
      CodeSize: CodeSize
    }' \
    --output table
done

# ── Check lambda environment variables ─────────────────────────
aws lambda get-function-configuration \
  --region ap-south-1 \
  --function-name rag-processor \
  --query 'Environment.Variables' \
  --output table

# ── Invoke lambda directly for testing ─────────────────────────
# Test processor with a fake SQS message
aws lambda invoke \
  --region ap-south-1 \
  --function-name rag-processor \
  --payload '{"Records":[{"body":"{\"job_id\":\"test-123\",\"query\":\"what is ml?\",\"user_id\":\"cc2d9741-031e-4a99-a79f-8725acf50116\",\"conversation_id\":\"cccccccc-cccc-cccc-cccc-cccccccccccc\",\"voice_mode\":false}"}]}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/lambda_response.json && cat /tmp/lambda_response.json


# =============================================================
# SUPABASE QUICK CHECKS
# =============================================================

# Run these in Supabase SQL Editor:

# ── Check document status ──────────────────────────────────────
# SELECT id, filename, status, chunk_count, created_at
# FROM rag.documents
# WHERE user_id = 'cc2d9741-031e-4a99-a79f-8725acf50116'
# ORDER BY created_at DESC;

# ── Check chunk embeddings filled ──────────────────────────────
# SELECT
#   COUNT(*) as total,
#   COUNT(embedding) as with_embedding,
#   COUNT(*) - COUNT(embedding) as missing_embedding
# FROM rag.chunks
# WHERE user_id = 'cc2d9741-031e-4a99-a79f-8725acf50116';

# ── Check voice credits ─────────────────────────────────────────
# SELECT id, display_name, voice_credits
# FROM rag.user_profiles
# WHERE id = 'cc2d9741-031e-4a99-a79f-8725acf50116';

# ── Reset voice credits ─────────────────────────────────────────
# UPDATE rag.user_profiles
# SET voice_credits = 3
# WHERE id = 'cc2d9741-031e-4a99-a79f-8725acf50116';

# ── Check recent messages ───────────────────────────────────────
# SELECT role, content, voice_used, created_at
# FROM rag.messages
# WHERE conversation_id = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
# ORDER BY created_at DESC
# LIMIT 10;

# ── Check all rag functions exist ───────────────────────────────
# SELECT routine_name, routine_type
# FROM information_schema.routines
# WHERE routine_schema = 'rag'
# ORDER BY routine_name;


# =============================================================
# REDIS QUICK CHECKS
# =============================================================

# ── Flush all cache (Upstash console CLI or REST) ──────────────
# curl -X POST "YOUR_UPSTASH_REDIS_REST_URL/flushdb" \
#   -H "Authorization: Bearer YOUR_UPSTASH_REDIS_REST_TOKEN"

# # ── Check specific job result ──────────────────────────────────
# curl "YOUR_UPSTASH_REDIS_REST_URL/get/job:YOUR_JOB_ID" \
#   -H "Authorization: Bearer YOUR_UPSTASH_REDIS_REST_TOKEN"

# # ── Check rate limit bucket status ─────────────────────────────
# curl "YOUR_UPSTASH_REDIS_REST_URL/zcard/rate_limit:sarvam:router" \
#   -H "Authorization: Bearer YOUR_UPSTASH_REDIS_REST_TOKEN"

# curl "YOUR_UPSTASH_REDIS_REST_URL/zcard/rate_limit:sarvam:rag" \
#   -H "Authorization: Bearer YOUR_UPSTASH_REDIS_REST_TOKEN"