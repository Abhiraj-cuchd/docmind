# scripts/run_all_tests.py

import subprocess
import sys

tests = [
    "test_secrets.py",
    "test_supabase.py",
    "test_redis.py",
    "test_auth.py",
    "test_indexer.py",
    "test_processor.py",
    "test_submit_poll.py",
]

print("=" * 50)
print("RAG MVP — Local Test Suite")
print("=" * 50)

failed = []

for test in tests:
    print(f"\nRunning {test}...")
    result = subprocess.run(
        [sys.executable, test],
        capture_output=False,
    )
    if result.returncode != 0:
        failed.append(test)

print("\n" + "=" * 50)
if failed:
    print(f"❌ {len(failed)} test(s) failed: {failed}")
else:
    print("✅ All tests passed — ready to deploy")
print("=" * 50)