# __tests__/test_secrets.py

import os
import sys
from pathlib import Path

# ── Step 1: Fix paths ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lambdas"))

# ── Step 2: Load .env BEFORE any shared imports ────────────────────
# CONCEPT: load_dotenv must run before importing shared.secrets
# because secrets.py reads AWS_REGION at module level when
# creating the boto3 client. If .env isn't loaded yet,
# AWS_REGION is None and boto3 uses the wrong region.
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── Step 3: Now safe to import shared modules ──────────────────────
from shared_lambda.secrets import get_secret


def test_secrets():
    print("\n=== Testing Secrets Manager ===")
    print(f"SECRET_NAME = {os.getenv('SECRET_NAME')}")
    print(f"AWS_REGION  = {os.getenv('AWS_REGION')}")

    try:
        url = get_secret("SUPABASE_URL")
        print(f"✅ SUPABASE_URL: {url[:40]}...")

        voyage = get_secret("VOYAGE_API_KEY")
        print(f"✅ VOYAGE_API_KEY: {voyage[:8]}...")

        router = get_secret("SARVAM_API_KEY_ROUTER")
        print(f"✅ SARVAM_API_KEY_ROUTER: {router[:8]}...")

        rag = get_secret("SARVAM_API_KEY_RAG")
        print(f"✅ SARVAM_API_KEY_RAG: {rag[:8]}...")

        redis_url = get_secret("UPSTASH_REDIS_REST_URL")
        print(f"✅ UPSTASH_REDIS_REST_URL: {redis_url[:20]}...")

        print("\n✅ All secrets accessible")

    except Exception as e:
        print(f"\n❌ Failed: {e}")


if __name__ == "__main__":
    test_secrets()