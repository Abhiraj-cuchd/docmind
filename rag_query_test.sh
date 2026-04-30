#!/bin/bash
# =============================================================
# RAG Query Test Script
# Tests a specific RAG query against an already-indexed document
# Usage: ./query_test.sh
# =============================================================

# ─────────────────────────────────────────────────────────────
# CONFIGURE THESE
# ─────────────────────────────────────────────────────────────
SUPABASE_URL="https://juzxjfnjysbzymbijzsv.supabase.co"
SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp1enhqZm5qeXNienltYmlqenN2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzcxMDM2MTYsImV4cCI6MjA5MjY3OTYxNn0.--HIouXIyeyZUOUim7XiWxoqFjq3aj_89v2-2htgDN4"
API_ENDPOINT="https://om6deoefoe.execute-api.ap-south-1.amazonaws.com"
TEST_EMAIL="ragtest@yopmail.com"
TEST_PASSWORD="Test1234!"
CONVERSATION_ID="cccccccc-cccc-cccc-cccc-cccccccccccc"

# Questions to test — add or change as needed
QUESTIONS=(
    "What does the document say about supervised learning?"
    "Explain neural networks based on my uploaded document"
    "What machine learning algorithms are mentioned in my document?"
    "Summarise the key concepts from my uploaded PDF"
    "What does my document say about gradient descent?"
)
# ─────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

pass()   { echo -e "${GREEN}✅ $1${NC}"; }
fail()   { echo -e "${RED}❌ $1${NC}"; }
info()   { echo -e "${BLUE}ℹ  $1${NC}"; }
warn()   { echo -e "${YELLOW}⚠  $1${NC}"; }
query()  { echo -e "${CYAN}❓ $1${NC}"; }
answer() { echo -e "${GREEN}💬 $1${NC}"; }
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
" 2>/dev/null
}

poll_job() {
    local job_id="$1"
    local max_polls=45
    local poll_count=0

    # Wait a moment before first poll — job may not be written yet
    sleep 2

    while [ $poll_count -lt $max_polls ]; do

        POLL=$(curl -s "$API_ENDPOINT/result/$job_id" \
          -H "Authorization: Bearer $JWT")

        STATUS=$(get_field "$POLL" "status")

        # Handle empty or missing status
        if [ -z "$STATUS" ] || [ "$STATUS" = "None" ]; then
            info "  Polling $((poll_count + 1))/$max_polls — waiting..."
            sleep 2
            poll_count=$((poll_count + 1))
            continue
        fi

        if [ "$STATUS" = "done" ]; then
            echo "$POLL"
            return 0
        fi

        if [ "$STATUS" = "error" ]; then
            echo "$POLL"
            return 1
        fi

        if [ "$STATUS" = "not_found" ]; then
            # Job expired or doesn't exist
            echo '{"status":"error","message":"job not found in Redis"}'
            return 1
        fi

        info "  Polling $((poll_count + 1))/$max_polls — $STATUS..."
        sleep 2
        poll_count=$((poll_count + 1))
    done

    echo '{"status":"timeout","message":"job timed out after 90 seconds"}'
    return 1
}

# ─────────────────────────────────────────────────────────────
# STEP 1 — GET JWT
# ─────────────────────────────────────────────────────────────
header "Authenticating"

JWT=$(curl -s -X POST \
  "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$TEST_EMAIL\",\"password\":\"$TEST_PASSWORD\"}" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d.get('access_token', '')
print(t)
" 2>/dev/null)

if [ -z "$JWT" ]; then
    fail "Authentication failed — check credentials"
    exit 1
fi

pass "Authenticated as $TEST_EMAIL"

# ─────────────────────────────────────────────────────────────
# STEP 2 — API HEALTH CHECK
# ─────────────────────────────────────────────────────────────
header "API Health Check"

HEALTH=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$API_ENDPOINT/query" \
  -H "Content-Type: application/json" \
  -d '{"question":"test"}')

if [ "$HEALTH" = "401" ] || [ "$HEALTH" = "200" ]; then
    pass "API is responding (HTTP $HEALTH)"
else
    fail "API returned unexpected status: $HEALTH"
    exit 1
fi

# ─────────────────────────────────────────────────────────────
# STEP 3 — RUN EACH QUESTION
# ─────────────────────────────────────────────────────────────
header "Running RAG Queries"

PASSED=0
FAILED=0
TOTAL=${#QUESTIONS[@]}

for i in "${!QUESTIONS[@]}"; do
    Q="${QUESTIONS[$i]}"
    Q_NUM=$((i + 1))

    echo ""
    echo -e "${CYAN}─────────────────────────────────────────${NC}"
    query "Question $Q_NUM/$TOTAL: $Q"
    echo -e "${CYAN}─────────────────────────────────────────${NC}"

    # Submit query
    SUBMIT=$(curl -s -X POST "$API_ENDPOINT/query" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $JWT" \
      -d "{
        \"question\": \"$Q\",
        \"conversation_id\": \"$CONVERSATION_ID\",
        \"voice_mode\": false
      }")

    STATUS=$(get_field "$SUBMIT" "status")
    JOB_ID=$(get_field "$SUBMIT" "job_id")
    CACHED=$(get_field "$SUBMIT" "cached")

    # ── Cache hit — instant response ──────────────────────────
    if [ "$STATUS" = "done" ] && [ "$CACHED" = "True" ]; then
        ANSWER=$(get_field "$SUBMIT" "answer")
        pass "Cache hit — instant response"
        answer "Answer: ${ANSWER:0:300}"
        [ ${#ANSWER} -gt 300 ] && info "  ... (truncated, full answer is ${#ANSWER} chars)"
        PASSED=$((PASSED + 1))
        continue
    fi

    # ── Conversational — instant response ─────────────────────
    if [ "$STATUS" = "done" ] && [ -z "$JOB_ID" ] || [ "$JOB_ID" = "None" ]; then
        ANSWER=$(get_field "$SUBMIT" "answer")
        TOKENS=$(get_field "$SUBMIT" "tokens_used")
        pass "Instant response (tokens: $TOKENS)"
        answer "Answer: ${ANSWER:0:300}"
        [ ${#ANSWER} -gt 300 ] && info "  ... (truncated)"
        PASSED=$((PASSED + 1))
        continue
    fi

    # ── Async job — poll for result ────────────────────────────
    if [ -n "$JOB_ID" ] && [ "$JOB_ID" != "None" ]; then
        info "Job submitted: $JOB_ID — polling..."

        RESULT=$(poll_job "$JOB_ID")
        RESULT_STATUS=$(get_field "$RESULT" "status")

        if [ "$RESULT_STATUS" = "done" ]; then
            ANSWER=$(get_field "$RESULT" "answer")
            TOKENS=$(get_field "$RESULT" "tokens_used")
            PATH_USED=$(get_field "$RESULT" "path")
            CACHED_RESULT=$(get_field "$RESULT" "cached")

            pass "Answered (path: $PATH_USED, tokens: $TOKENS, cached: $CACHED_RESULT)"
            answer "Answer: ${ANSWER:0:400}"
            [ ${#ANSWER} -gt 400 ] && info "  ... (truncated, full answer is ${#ANSWER} chars)"
            PASSED=$((PASSED + 1))

        elif [ "$RESULT_STATUS" = "timeout" ]; then
            fail "Question $Q_NUM timed out after 90 seconds"
            warn "Check CloudWatch: aws logs tail /aws/lambda/rag-processor --region ap-south-1 --since 5m"
            FAILED=$((FAILED + 1))

        else
            ERROR=$(get_field "$RESULT" "message")
            fail "Question $Q_NUM failed: $ERROR"
            FAILED=$((FAILED + 1))
        fi
    else
        fail "No job_id returned: $SUBMIT"
        FAILED=$((FAILED + 1))
    fi

    # Small delay between questions to avoid rate limits
    if [ $Q_NUM -lt $TOTAL ]; then
        info "  Waiting 3 seconds before next question..."
        sleep 3
    fi
done

# ─────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────
header "Query Test Summary"

echo ""
echo -e "  Total questions:  $TOTAL"
echo -e "  ${GREEN}Passed: $PASSED${NC}"
echo -e "  ${RED}Failed: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}  All queries answered successfully 🎉   ${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}"
else
    echo -e "${YELLOW}════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  $FAILED/$TOTAL queries failed ⚠️           ${NC}"
    echo -e "${YELLOW}════════════════════════════════════════${NC}"
    echo ""
    warn "Debug with:"
    warn "  aws logs tail /aws/lambda/rag-processor --region ap-south-1 --since 10m"
fi

echo ""