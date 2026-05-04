# lambdas/shared/supabase_client.py
# Provides Supabase client instances for all Lambda functions.
# Two clients — one for user-scoped operations, one for admin operations.

from supabase import create_client, Client
from shared_lambda.secrets import get_secret

# CONCEPT: Module-level variables in Lambda persist across warm invocations.
# The first time this module is imported, _service_client is None.
# The first call to get_service_client() creates the connection and
# stores it here. Every subsequent call on a warm Lambda reuses it.
# This is called the "singleton pattern" — one instance, reused forever.
# Without this, every request would create a new Supabase connection,
# adding ~200ms latency and exhausting your connection pool.
_service_client: Client | None = None


def get_service_client() -> Client:
    """
    Returns a Supabase client authenticated with the service role key.
    This client BYPASSES Row Level Security.
    Use for:
      - Lambda indexer writing chunks (backend operation)
      - Lambda processor reading chunks (manually filtered by user_id)
      - Any admin operation that needs to act across users

    CONCEPT: The service role key is like a master key to your database.
    It bypasses all RLS policies. Guard it carefully:
      - Never expose it to the frontend
      - Never log it
      - Only use it in Lambda (server-side), never in client-side code
    """
    global _service_client

    if _service_client is None:
        # Fetch credentials from Secrets Manager
        # These are stored as a single JSON secret:
        # {
        #   "SUPABASE_URL": "https://xxxx.supabase.co",
        #   "SUPABASE_SERVICE_KEY": "eyJhbGc..."
        # }
        supabase_url = get_secret("SUPABASE_URL")
        service_key  = get_secret("SUPABASE_SERVICE_KEY")

        # CONCEPT: The URL here uses port 6543 (PgBouncer) not 5432.
        # Supabase automatically routes API calls through PgBouncer
        # when you use the standard supabase-py client — you don't
        # need to specify the port manually for the REST API.
        # PgBouncer is only relevant for direct psycopg2/asyncpg connections.
        # The supabase-py client uses the REST API (PostgREST) by default
        # which is already pooled on Supabase's side.
        _service_client = create_client(supabase_url, service_key)
        print("Supabase service client initialised")  # visible in CloudWatch logs

    return _service_client


def get_user_client(user_jwt: str) -> Client:
    """
    Returns a Supabase client authenticated as a specific user.
    This client RESPECTS Row Level Security.
    Use for:
      - Any operation where you want RLS to automatically filter by user
      - Reading user-specific data without manually adding WHERE user_id =

    CONCEPT: By passing the user's JWT to the Supabase client,
    every query this client makes is automatically scoped to that user.
    auth.uid() inside RLS policies resolves to the user in the JWT.
    This is an alternative to manually filtering by user_id everywhere.

    In practice we use the service client + manual user_id filter
    in most Lambdas because we've already verified the JWT in auth.py
    and we want explicit control over the filter. But this client
    is useful for simpler read operations.
    """
    supabase_url = get_secret("SUPABASE_URL")
    anon_key     = get_secret("SUPABASE_ANON_KEY")

    # CONCEPT: We create a new client per request here (no caching)
    # because each user has a different JWT. Caching would mean
    # user A's client bleeds into user B's request — a security bug.
    # The anon_key is the public key (safe to use client-side too).
    # The JWT is what scopes it to a specific user.
    client = create_client(supabase_url, anon_key)

    # Inject the user's JWT so RLS policies see the correct auth.uid()
    client.auth.set_session(
        access_token=user_jwt,
        refresh_token=""   # not needed in Lambda — we don't refresh tokens
    )

    return client


def execute_hybrid_search(
    user_id:         str,
    query_embedding: list[float],
    query_text:      str,
    match_count:     int = 10,
    document_id:     str | None = None,
) -> list[dict]:
    """
    Calls the hybrid_search SQL function we wrote in 006_functions.sql.
    Returns a list of chunk dicts ordered by RRF score descending.

    CONCEPT: supabase-py's .rpc() method calls a PostgreSQL function
    by name and passes arguments as a dict. It maps directly to:
        SELECT * FROM rag.hybrid_search(...)
    The result comes back as a list of dicts, one per returned row.
    """
    client = get_service_client()

    if document_id:
        result = client.schema("rag").rpc(
            "hybrid_search_in_document",
            {
                "query_embedding":    query_embedding,
                "query_text":         query_text,
                "target_user_id":     user_id,
                "target_document_id": document_id,
                "match_count":        match_count,
            }
        ).execute()
    else:
        result = client.schema("rag").rpc(
            "hybrid_search",
            {
                "query_embedding": query_embedding,
                "query_text":      query_text,
                "target_user_id":  user_id,
                "match_count":     match_count,
            }
        ).execute()

    # result.data is a list of dicts like:
    # [
    #   {"id": "uuid", "content": "...", "metadata": {...}, "rrf_score": 0.032},
    #   {"id": "uuid", "content": "...", "metadata": {...}, "rrf_score": 0.028},
    #   ...
    # ]
    return result.data


def consume_voice_credit(user_id: str) -> bool:
    """
    Calls the consume_voice_credit SQL function from 006_functions.sql.
    Returns True if a credit was consumed, False if none remained.

    CONCEPT: We wrap the RPC call here so Lambda handler code stays clean.
    The actual atomic decrement logic lives in the SQL function —
    this is just the Python bridge to call it.
    """
    client = get_service_client()

    result = client.schema("rag").rpc(
        "consume_voice_credit",
        {"target_user_id": user_id}
    ).execute()

    # result.data is True or False — returned directly from the SQL function
    return result.data


def refund_voice_credit(user_id: str) -> None:
    """Atomically increments voice_credits for a user. Call on TTS failure."""
    client = get_service_client()
    client.schema("rag").rpc(
        "refund_voice_credit",
        {"target_user_id": user_id}
    ).execute()