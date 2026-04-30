# scripts/test_supabase.py
# Verifies Supabase connection + rag schema is set up correctly

import sys
sys.path.insert(0, "lambdas")

from load_env import *
from shared_lambda.supabase_client import get_service_client

def test_supabase():
    print("\n=== Testing Supabase Connection ===")

    try:
        supabase = get_service_client()
        print("✅ Supabase client created")

        # Test 1: Can we reach the rag schema?
        result = supabase.schema("rag") \
            .table("user_profiles") \
            .select("id") \
            .limit(1) \
            .execute()
        print(f"✅ rag.user_profiles accessible "
              f"({len(result.data)} rows returned)")

        # Test 2: Check all tables exist
        tables = ["user_profiles", "documents", "chunks",
                  "conversations", "messages"]

        for table in tables:
            result = supabase.schema("rag") \
                .table(table) \
                .select("*") \
                .limit(1) \
                .execute()
            print(f"✅ rag.{table} accessible")

        # Test 3: Check hybrid_search function exists
        # We call it with dummy data — it will return empty results
        # but confirms the function is there and callable
        dummy_embedding = [0.0] * 1024
        result = supabase.schema("rag").rpc(
            "hybrid_search",
            {
                "query_embedding":  dummy_embedding,
                "query_text":       "test query",
                "target_user_id":   "00000000-0000-0000-0000-000000000000",
                "match_count":      5,
            }
        ).execute()
        print(f"✅ hybrid_search function callable "
              f"(returned {len(result.data)} results for dummy query)")

        # Test 4: Check consume_voice_credit function exists
        result = supabase.schema("rag").rpc(
            "consume_voice_credit",
            {"target_user_id": "00000000-0000-0000-0000-000000000000"}
        ).execute()
        print(f"✅ consume_voice_credit function callable")

        print("\n✅ Supabase fully operational")

    except Exception as e:
        print(f"❌ Supabase test failed: {e}")
        print("\nCheck:")
        print("  1. SQL files all run? → check Supabase SQL editor")
        print("  2. SUPABASE_URL correct in secret?")
        print("  3. SUPABASE_SERVICE_KEY correct?")

if __name__ == "__main__":
    test_supabase()