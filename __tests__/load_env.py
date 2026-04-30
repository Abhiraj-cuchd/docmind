# scripts/load_env.py
# Run this before any test script to load .env into os.environ

from dotenv import load_dotenv
import os

load_dotenv()

# Verify critical vars are present
required = [
    "AWS_REGION",
    "SECRET_NAME",
]

missing = [v for v in required if not os.getenv(v)]
if missing:
    raise EnvironmentError(f"Missing env vars: {missing}")

print("✅ Environment loaded")