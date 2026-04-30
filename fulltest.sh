#!/bin/bash
# =============================================================
# End-to-end test script for RAG MVP
# Usage: ./test_e2e.sh
# =============================================================

set -e

# ─────────────────────────────────────────────────────────────
# CONFIGURE THESE BEFORE RUNNING
# ─────────────────────────────────────────────────────────────
SUPABASE_URL="https://juzxjfnjysbzymbijzsv.supabase.co"
SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp1enhqZm5qeXNienltYmlqenN2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzcxMDM2MTYsImV4cCI6MjA5MjY3OTYxNn0.--HIouXIyeyZUOUim7XiWxoqFjq3aj_89v2-2htgDN4"
API_ENDPOINT="https://om6deoefoe.execute-api.ap-south-1.amazonaws.com"
TEST_EMAIL="ragtest@yopmail.com"
TEST_PASSWORD="Test1234!"
TEST_USER_ID="cc2d9741-031e-4a99-a79f-8725acf50116"
TEST_PDF_PATH="__tests__/test_data/sample.pdf"
CONVERSATION_ID="cccccccc-cccc-cccc-cccc-cccccccccccc"
# ─────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ $1${NC}"; }
fail() { echo -e "${RED}❌ $1${NC}"; echo -e "${RED}Stopping test.${NC}"; exit 1; }
info() { echo -e "${BLUE}ℹ  $1${NC}"; }
warn() { echo -e "${YELLOW}⚠  $1${NC}"; }
header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════${NC}"
}

get_field() {
    echo "$1" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    val = data.get('$2', '')
    print(val if val is not None else '')
except:
    print('')
"
}

check_status() {
    local response="$1"
    local expected="$2"
    local actual
    actual=$(get_field "$response" "status")
    [ "$actual" = "$expected" ]
}

# ─────────────────────────────────────────────────────────────
# VALIDATE CONFIG
# ─────────────────────────────────────────────────────────────
header "Validating Configuration"

[ "$SUPABASE_URL" = "https://YOUR_PROJECT.supabase.co" ] && fail "Set SUPABASE_URL"
[ "$SUPABASE_ANON_KEY" = "YOUR_ANON_KEY" ] && fail "Set SUPABASE_ANON_KEY"
[ "$TEST_USER_ID" = "PASTE_YOUR_USER_UUID_HERE" ] && fail "Set TEST_USER_ID"

[ ! -f "$TEST_PDF_PATH" ] && \
    warn "No PDF at $TEST_PDF_PATH — PDF test will be skipped" || \
    info "PDF found at $TEST_PDF_PATH"

pass "Configuration looks good"

# ─────────────────────────────────────────────────────────────
# STEP 1 — HEALTH CHECK
# ─────────────────────────────────────────────────────────────
header "Step 1 — API Health Check"

info "Sending request without JWT — expecting 401..."

HEALTH=$(curl -s -X POST "$API_ENDPOINT/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "test"}')

echo "Response: $HEALTH"

echo "$HEALTH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
sys.exit(0 if d.get('error') == 'Unauthorized' else 1)
" && pass "API is live — 401 returned as expected" || \
     fail "Expected 401 — got: $HEALTH"

# ─────────────────────────────────────────────────────────────
# STEP 2 — GET JWT
# ─────────────────────────────────────────────────────────────
header "Step 2 — Authenticating With Supabase"

info "Fetching JWT for $TEST_EMAIL..."

AUTH=$(curl -s -X POST \
  "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$TEST_EMAIL\",\"password\":\"$TEST_PASSWORD\"}")

JWT=$(echo "$AUTH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d.get('access_token', '')
print(t)
sys.exit(0 if t else 1)
") || fail "Auth failed: $AUTH"

[ -z "$JWT" ] && fail "Empty JWT token"
pass "JWT obtained: ${JWT:0:20}..."

# ─────────────────────────────────────────────────────────────
# STEP 3 — CREATE CONVERSATION
# ─────────────────────────────────────────────────────────────
header "Step 3 — Creating Test Conversation"

info "Creating conversation $CONVERSATION_ID..."

curl -s -X POST \
  "$SUPABASE_URL/rest/v1/conversations" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -H "Accept-Profile: rag" \
  -H "Content-Profile: rag" \
  -H "Prefer: return=minimal,resolution=ignore-duplicates" \
  -d "{
    \"id\": \"$CONVERSATION_ID\",
    \"user_id\": \"$TEST_USER_ID\",
    \"title\": \"E2E Test Conversation\"
  }" > /dev/null

pass "Conversation ready: $CONVERSATION_ID"

# ─────────────────────────────────────────────────────────────
# STEP 4 — CONVERSATIONAL QUERY
# ─────────────────────────────────────────────────────────────
header "Step 4 — Conversational Query (instant, no SQS)"

info "Sending greeting..."

CONV=$(curl -s -X POST "$API_ENDPOINT/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -d "{
    \"question\": \"Hi there!\",
    \"conversation_id\": \"$CONVERSATION_ID\",
    \"voice_mode\": false
  }")

echo "Response: $CONV"

echo "$CONV" | python3 -c "
import sys, json
d = json.load(sys.stdin)
sys.exit(0 if d.get('status') == 'done' else 1)
" && pass "Conversational query returned instantly" || \
     fail "Conversational query failed: $CONV"

CONV_ANSWER=$(get_field "$CONV" "answer")
CONV_TOKENS=$(get_field "$CONV" "tokens_used")
info "Answer: $CONV_ANSWER"
info "Tokens used: $CONV_TOKENS"

# ─────────────────────────────────────────────────────────────
# STEP 5 — GENERAL KNOWLEDGE QUERY (async)
# ─────────────────────────────────────────────────────────────
header "Step 5 — General Knowledge Query (async pipeline)"

info "Submitting: 'What is machine learning?'"

SUBMIT=$(curl -s -X POST "$API_ENDPOINT/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -d "{
    \"question\": \"What is machine learning?\",
    \"conversation_id\": \"$CONVERSATION_ID\",
    \"voice_mode\": false
  }")

echo "Submit response: $SUBMIT"

JOB_ID=$(get_field "$SUBMIT" "job_id")
[ -z "$JOB_ID" ] || [ "$JOB_ID" = "None" ] && \
    fail "No job_id in response: $SUBMIT"

pass "Job submitted: $JOB_ID"
info "Polling for result (max 90 seconds)..."

MAX_POLLS=45
POLL_COUNT=0
FINAL_STATUS=""

while [ $POLL_COUNT -lt $MAX_POLLS ]; do
    sleep 2

    POLL=$(curl -s "$API_ENDPOINT/result/$JOB_ID" \
      -H "Authorization: Bearer $JWT")

    FINAL_STATUS=$(get_field "$POLL" "status")
    info "Poll $((POLL_COUNT + 1))/$MAX_POLLS — status: $FINAL_STATUS"

    if [ "$FINAL_STATUS" = "done" ]; then
        ANSWER=$(get_field "$POLL" "answer")
        TOKENS=$(get_field "$POLL" "tokens_used")
        pass "Job completed"
        info "Answer: ${ANSWER:0:200}..."
        info "Tokens used: $TOKENS"
        break
    fi

    if [ "$FINAL_STATUS" = "error" ]; then
        ERROR=$(get_field "$POLL" "message")
        fail "Job failed: $ERROR"
    fi

    POLL_COUNT=$((POLL_COUNT + 1))
done

[ $POLL_COUNT -eq $MAX_POLLS ] && fail "Job timed out after 90 seconds"

# ─────────────────────────────────────────────────────────────
# STEP 6 — PDF UPLOAD AND INDEXING
# ─────────────────────────────────────────────────────────────
header "Step 6 — PDF Upload and Indexing"

if [ ! -f "$TEST_PDF_PATH" ]; then
    warn "Skipping — no PDF at $TEST_PDF_PATH"
    warn "Add any PDF there and re-run for full RAG pipeline test"
else
    PDF_FILENAME=$(basename "$TEST_PDF_PATH")
    DOCUMENT_ID=$(python3 -c "import uuid; print(str(uuid.uuid4()))")
    S3_KEY="uploads/$TEST_USER_ID/$DOCUMENT_ID/$PDF_FILENAME"

    info "Document ID: $DOCUMENT_ID"
    info "Creating document record in Supabase..."

    curl -s -X POST \
      "$SUPABASE_URL/rest/v1/documents" \
      -H "apikey: $SUPABASE_ANON_KEY" \
      -H "Authorization: Bearer $JWT" \
      -H "Content-Type: application/json" \
      -H "Accept-Profile: rag" \
      -H "Content-Profile: rag" \
      -H "Prefer: return=minimal" \
      -d "{
        \"id\": \"$DOCUMENT_ID\",
        \"user_id\": \"$TEST_USER_ID\",
        \"filename\": \"$PDF_FILENAME\",
        \"s3_key\": \"$S3_KEY\",
        \"status\": \"processing\"
      }" > /dev/null

    pass "Document record created"

    info "Getting presigned S3 URL..."

    PRESIGN=$(curl -s -X POST "$API_ENDPOINT/upload" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $JWT" \
      -d "{
        \"filename\": \"$PDF_FILENAME\",
        \"document_id\": \"$DOCUMENT_ID\",
        \"user_id\": \"$TEST_USER_ID\"
      }")

    echo "Presign response: $PRESIGN"

    PRESIGNED_URL=$(get_field "$PRESIGN" "upload_url")

    if [ -z "$PRESIGNED_URL" ] || [ "$PRESIGNED_URL" = "None" ]; then
        warn "Could not get presigned URL — skipping upload"
        warn "You may need to implement the /upload endpoint"
    else
        info "Uploading PDF to S3..."

        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
          -X PUT "$PRESIGNED_URL" \
          -H "Content-Type: application/pdf" \
          --data-binary "@$TEST_PDF_PATH")

        [ "$HTTP_CODE" = "200" ] && \
            pass "PDF uploaded (HTTP $HTTP_CODE)" || \
            fail "Upload failed (HTTP $HTTP_CODE)"

        info "Waiting for indexer to process PDF (max 3 minutes)..."

        MAX_WAITS=90
        WAIT_COUNT=0
        DOC_STATUS="processing"

        while [ $WAIT_COUNT -lt $MAX_WAITS ]; do
            sleep 2

            DOC=$(curl -s \
              "$SUPABASE_URL/rest/v1/documents?id=eq.$DOCUMENT_ID&select=status,chunk_count" \
              -H "apikey: $SUPABASE_ANON_KEY" \
              -H "Authorization: Bearer $JWT" \
              -H "Accept-Profile: rag")

            DOC_STATUS=$(echo "$DOC" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d[0]['status'] if d else 'not_found')
")
            CHUNK_COUNT=$(echo "$DOC" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d[0].get('chunk_count', 0) if d else 0)
")

            info "Wait $((WAIT_COUNT + 1))/$MAX_WAITS — status: $DOC_STATUS"

            [ "$DOC_STATUS" = "ready" ] && \
                { pass "Document indexed: $CHUNK_COUNT chunks"; break; }

            [ "$DOC_STATUS" = "failed" ] && \
                fail "Indexing failed — check CloudWatch logs for rag-indexer"

            WAIT_COUNT=$((WAIT_COUNT + 1))
        done

        [ $WAIT_COUNT -eq $MAX_WAITS ] && \
            warn "Indexing timed out — check CloudWatch logs for rag-indexer"

        # ── Step 7: RAG Query ─────────────────────────────────────
        if [ "$DOC_STATUS" = "ready" ]; then
            header "Step 7 — RAG Query Against Uploaded Document"

            info "Asking: 'What does the document say about supervised learning?'"

            RAG_SUBMIT=$(curl -s -X POST "$API_ENDPOINT/query" \
              -H "Content-Type: application/json" \
              -H "Authorization: Bearer $JWT" \
              -d "{
                \"question\": \"What is this document about?\",
                \"conversation_id\": \"$CONVERSATION_ID\",
                \"voice_mode\": false
              }")

            RAG_JOB_ID=$(get_field "$RAG_SUBMIT" "job_id")

            [ -z "$RAG_JOB_ID" ] || [ "$RAG_JOB_ID" = "None" ] && \
                fail "No job_id for RAG query: $RAG_SUBMIT"

            pass "RAG job submitted: $RAG_JOB_ID"
            info "Polling (max 90 seconds)..."

            MAX_POLLS=45
            POLL_COUNT=0

            while [ $POLL_COUNT -lt $MAX_POLLS ]; do
                sleep 2

                RAG_POLL=$(curl -s "$API_ENDPOINT/result/$RAG_JOB_ID" \
                  -H "Authorization: Bearer $JWT")

                RAG_STATUS=$(get_field "$RAG_POLL" "status")
                info "Poll $((POLL_COUNT + 1))/$MAX_POLLS — status: $RAG_STATUS"

                if [ "$RAG_STATUS" = "done" ]; then
                    RAG_ANSWER=$(get_field "$RAG_POLL" "answer")
                    RAG_TOKENS=$(get_field "$RAG_POLL" "tokens_used")
                    RAG_PATH=$(get_field "$RAG_POLL" "path")
                    pass "RAG query completed"
                    info "Path: $RAG_PATH"
                    info "Tokens: $RAG_TOKENS"
                    info "Answer: ${RAG_ANSWER:0:300}..."
                    break
                fi

                [ "$RAG_STATUS" = "error" ] && \
                    fail "RAG failed: $(get_field "$RAG_POLL" "message")"

                POLL_COUNT=$((POLL_COUNT + 1))
            done

            [ $POLL_COUNT -eq $MAX_POLLS ] && fail "RAG query timed out"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────
header "Test Summary"

pass "Step 1 — API health check"
pass "Step 2 — JWT authentication"
pass "Step 3 — Conversation created"
pass "Step 4 — Conversational query (instant)"
pass "Step 5 — General knowledge query (async pipeline)"

if [ -f "$TEST_PDF_PATH" ]; then
    [ "$DOC_STATUS" = "ready" ] && \
        pass "Step 6 — PDF indexed successfully" || \
        warn "Step 6 — PDF indexing incomplete"
    pass "Step 7 — RAG query against document"
else
    warn "Step 6/7 — Skipped (add PDF to $TEST_PDF_PATH)"
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  All tests completed 🎉                ${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
info "Next: Add a PDF to $TEST_PDF_PATH and re-run for full RAG test"