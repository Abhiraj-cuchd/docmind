# run_tests.sh — place at project root
#!/bin/bash

echo "================================"
echo "RAG MVP — Local Test Suite"
echo "================================"

FAILED=0

run_test() {
    echo ""
    echo "Running $1..."
    python __tests__/$1
    if [ $? -ne 0 ]; then
        echo "❌ $1 FAILED"
        FAILED=$((FAILED + 1))
    else
        echo "✅ $1 PASSED"
    fi
}

run_test "test_secrets.py"
run_test "test_supabase.py"
run_test "test_redis.py"
run_test "test_auth.py"
run_test "test_indexer.py"
run_test "test_processor.py"
run_test "test_submit_poll.py"

echo ""
echo "================================"
if [ $FAILED -eq 0 ]; then
    echo "✅ All tests passed"
else
    echo "❌ $FAILED test(s) failed"
fi
echo "================================"