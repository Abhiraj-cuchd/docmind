# lambdas/shared_lambda/secrets.py
# Fetches secrets from AWS Secrets Manager.
# Every Lambda imports this instead of hardcoding credentials.

import boto3
import json
import os

# CONCEPT: Initialise boto3 client once at module level.
# Reused across warm Lambda invocations — avoids reconnecting
# on every request.
secrets_client = boto3.client(
    "secretsmanager",
    region_name=os.getenv("AWS_REGION", "ap-south-1")
)

# CONCEPT: In-memory cache for secrets.
# Secrets Manager charges per API call.
# Caching means we pay the fetch cost once per warm instance,
# not once per request.
_cache = {}


def get_secret(key: str) -> str:
    """
    Fetches a specific key from the secret JSON stored in
    Secrets Manager under the SECRET_NAME environment variable.

    CONCEPT: The parameter is a KEY inside the secret JSON,
    not the secret name itself. The secret name comes from
    the SECRET_NAME environment variable set by CDK.

    Example:
        Secret name:    prod/serverless-rag-secrets
        Secret value:   {"SUPABASE_URL": "https://...", "VOYAGE_API_KEY": "..."}

        get_secret("SUPABASE_URL")   → "https://..."
        get_secret("VOYAGE_API_KEY") → "..."
    """

    # Return from cache if already fetched
    if key in _cache:
        return _cache[key]

    # Get the secret NAME from environment variable
    # This is set by CDK as SECRET_NAME=prod/serverless-rag-secrets
    secret_name = os.getenv("SECRET_NAME")

    if not secret_name:
        raise ValueError(
            "SECRET_NAME environment variable is not set. "
            "This should be set by CDK to 'prod/serverless-rag-secrets'."
        )

    print(f"[Secrets] Fetching secret: {secret_name}")

    # Fetch the entire secret JSON from Secrets Manager
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret_dict = json.loads(response["SecretString"])

    # Cache all key-value pairs at once so subsequent calls
    # to get_secret() for any key hit the cache, not Secrets Manager
    for k, v in secret_dict.items():
        _cache[k] = v

    print(f"[Secrets] Cached {len(secret_dict)} keys from {secret_name}")

    if key not in _cache:
        raise KeyError(
            f"Key '{key}' not found in secret '{secret_name}'. "
            f"Available keys: {list(_cache.keys())}"
        )

    return _cache[key]