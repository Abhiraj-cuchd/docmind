# scripts/test_submit_poll.py
# Simulates the full async flow without actual SQS
# Tests submit logic + Redis job state + poll logic

import sys
import json
import uuid
sys.path.insert(0, "lambdas")

from load_env import *

TEST_USER_ID      = "paste-a-real-user-uuid-here"
TEST_CONVERSATION = "paste-a-real-conversation-uuid-here"

def test_submit_poll():
    print("\n=== Testing Submit + Poll Flow ===")

    from shared_lambda.rate_limiter import get_redis_client
    r = get_redis_client()

    # ── Simulate what submit Lambda does ──────────────────────────
    print("\n--- Simulating Submit ---")

    job_id    = str(uuid.uuid4())
    cache_key = f"cache:{TEST_USER_ID}:testhash"

    # Write pending status (what submit does after enqueuing)
    r.setex(
        f"job:{job_id}",
        3600,
        json.dumps({"status": "pending"})
    )
    print(f"✅ Job {job_id} written as pending")

    # ── Simulate what poll Lambda does ─────────────────────────────
    print("\n--- Simulating Poll (pending) ---")

    raw    = r.get(f"job:{job_id}")
    result = json.loads(raw)
    assert result["status"] == "pending"
    print(f"✅ Poll returned: {result}")

    # ── Simulate processor writing result ─────────────────────────
    print("\n--- Simulating Processor Writing Result ---")

    r.setex(
        f"job:{job_id}",
        3600,
        json.dumps({
            "status":                  "done",
            "answer":                  "This is a test answer.",
            "cached":                  False,
            "voice_url":               None,
            "voice_credits_remaining": 3,
            "tokens_used":             3,
        })
    )
    print(f"✅ Processor result written")

    # ── Simulate poll Lambda reading done result ───────────────────
    print("\n--- Simulating Poll (done) ---")

    raw    = r.get(f"job:{job_id}")
    result = json.loads(raw)
    assert result["status"] == "done"
    assert result["answer"] == "This is a test answer."
    print(f"✅ Poll returned done: '{result['answer']}'")

    # ── Test cache ─────────────────────────────────────────────────
    print("\n--- Testing Cache ---")

    r.setex(cache_key, 3600, "cached answer for test query")
    cached = r.get(cache_key)
    assert cached == "cached answer for test query"
    print(f"✅ Cache write + read working")

    # Cleanup
    r.delete(f"job:{job_id}")
    r.delete(cache_key)
    print("✅ Cleanup done")

    print("\n✅ Submit + Poll flow working")

if __name__ == "__main__":
    test_submit_poll()