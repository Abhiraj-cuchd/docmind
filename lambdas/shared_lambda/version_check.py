# Add this to shared_lambda/version_check.py
import importlib.metadata
import json

PACKAGES_TO_CHECK = [
    "supabase", "gotrue", "httpx", "httpcore",
    "postgrest", "realtime", "storage3",
    "upstash-redis", "PyJWT", "cryptography",
]

def get_installed_versions() -> dict:
    versions = {}
    for pkg in PACKAGES_TO_CHECK:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = "NOT INSTALLED"
    return versions