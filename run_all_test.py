# scripts/run_all_tests.py

import subprocess
import sys
import os

TEST_DIR = "__tests__"

_venv_python = os.path.join(os.path.dirname(__file__), "venv", "bin", "python")
PYTHON = _venv_python if os.path.isfile(_venv_python) else sys.executable

tests = [
    "test_secrets.py",
    "test_supabase.py",
    "test_redis.py",
    "test_auth.py",
    "test_ingestion.py",
    "test_query.py",
    "test_router.py",
    "test_submit_poll.py",
]

print("=" * 50)
print("RAG MVP — Local Test Suite")
print("=" * 50)

failed = []

for test in tests:
    print(f"\nRunning {test}...")
    result = subprocess.run(
        [PYTHON, f"{TEST_DIR}/{test}"],
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