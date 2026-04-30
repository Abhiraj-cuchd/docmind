# scripts/test_redis.py
# Verifies Upstash Redis REST connection + basic operations

import sys
sys.path.insert(0, "lambdas")

from load_env import *
from shared_lambda.rate_limiter import (
    get_redis_client,
    get_available_tokens,
    get_rate_limit_snapshot,
    ROUTER_REDIS_KEY,
    RAG_REDIS_KEY,
)

def test_redis():
    print("\n=== Testing Upstash Redis ===")

    try:
        r = get_redis_client()
        print("✅ Redis client created")

        # Test 1: Basic set/get
        r.set("rag:test:ping", "pong")
        value = r.get("rag:test:ping")
        assert value == "pong", f"Expected 'pong', got '{value}'"
        print("✅ Basic SET/GET working")

        # Test 2: setex (TTL)
        r.setex("rag:test:ttl", 10, "expires-soon")
        value = r.get("rag:test:ttl")
        assert value == "expires-soon"
        print("✅ SETEX (TTL) working")

        # Test 3: Token bucket operations
        snapshot = get_rate_limit_snapshot(r)
        print(f"✅ Token bucket snapshot: {snapshot}")

        router_tokens = get_available_tokens(r, ROUTER_REDIS_KEY)
        rag_tokens    = get_available_tokens(r, RAG_REDIS_KEY)
        print(f"✅ Router bucket: {router_tokens}/60 tokens available")
        print(f"✅ RAG bucket: {rag_tokens}/60 tokens available")

        # Test 4: JSON round trip (how results are stored)
        import json
        test_result = {
            "status": "done",
            "answer": "test answer",
            "cached": False,
        }
        r.setex("rag:test:job", 60, json.dumps(test_result))
        raw = r.get("rag:test:job")
        parsed = json.loads(raw)
        assert parsed["status"] == "done"
        print("✅ JSON result storage working")

        # Cleanup test keys
        r.delete("rag:test:ping")
        r.delete("rag:test:ttl")
        r.delete("rag:test:job")
        print("✅ Cleanup done")

        print("\n✅ Redis fully operational")

    except Exception as e:
        print(f"❌ Redis test failed: {e}")
        print("\nCheck:")
        print("  1. UPSTASH_REDIS_REST_URL correct?")
        print("  2. UPSTASH_REDIS_REST_TOKEN correct?")
        print("  3. upstash-redis package installed?")

if __name__ == "__main__":
    test_redis()