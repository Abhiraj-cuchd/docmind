# lambdas/shared_lambda/rate_limiter.py
# Fix the acquire_tokens function — replace pipeline with individual calls

import time
import uuid
from upstash_redis import Redis
from shared_lambda.secrets import get_secret

BUCKET_CAPACITY   = 60
WINDOW_SECONDS    = 60

ROUTER_COST       = 1
HYDE_COST         = 1
GENERATE_COST     = 2

ROUTER_REDIS_KEY  = "rate_limit:sarvam:router"
RAG_REDIS_KEY     = "rate_limit:sarvam:rag"

ROUTER_TIMEOUT_S  = 15
RAG_TIMEOUT_S     = 45

NVIDIA_REDIS_KEY  = "rate_limit:nvidia:tasks"
NVIDIA_CAPACITY   = 40
NVIDIA_COST       = 1
NVIDIA_TIMEOUT_S  = 45


def get_redis_client() -> Redis:
    return Redis(
        url=get_secret("UPSTASH_REDIS_REST_URL"),
        token=get_secret("UPSTASH_REDIS_REST_TOKEN"),
    )


def get_available_tokens(r: Redis, bucket_key: str, capacity: int = BUCKET_CAPACITY) -> int:
    now_ms       = int(time.time() * 1000)
    window_start = now_ms - (WINDOW_SECONDS * 1000)

    r.zremrangebyscore(bucket_key, 0, window_start)
    used      = r.zcard(bucket_key)
    available = max(0, capacity - used)

    return available


def acquire_tokens(
    r:          Redis,
    bucket_key: str,
    cost:       int,
    timeout_s:  int,
    capacity:   int = BUCKET_CAPACITY,
) -> bool:
    start     = time.time()
    wait_time = 1.0

    while time.time() - start < timeout_s:
        available = get_available_tokens(r, bucket_key, capacity)

        if available >= cost:
            now_ms = int(time.time() * 1000)

            # CONCEPT: upstash-redis REST client does not support
            # pipeline.execute() the same way redis-py does.
            # We use individual zadd calls instead.
            # Each call is a separate HTTP request to Upstash REST API.
            # At cost=1 or cost=2 this is 1-2 HTTP calls — acceptable.
            for _ in range(cost):
                r.zadd(bucket_key, {f"token:{uuid.uuid4()}": now_ms})

            elapsed = time.time() - start
            print(f"[RateLimiter] Bucket '{bucket_key}': "
                  f"acquired {cost} token(s), "
                  f"waited {elapsed:.1f}s, "
                  f"{available - cost} remaining")
            return True

        elapsed = time.time() - start
        print(f"[RateLimiter] Bucket '{bucket_key}': "
              f"need {cost}, have {available}. "
              f"Waiting {wait_time:.1f}s "
              f"({elapsed:.1f}s of {timeout_s}s)")

        time.sleep(wait_time)
        wait_time = min(wait_time * 1.5, 10.0)

    print(f"[RateLimiter] Bucket '{bucket_key}': "
          f"timed out after {timeout_s}s")
    return False


def acquire_router_token(r: Redis) -> bool:
    return acquire_tokens(r, ROUTER_REDIS_KEY, ROUTER_COST, ROUTER_TIMEOUT_S)


def acquire_hyde_token(r: Redis) -> bool:
    return acquire_tokens(r, RAG_REDIS_KEY, HYDE_COST, timeout_s=15)


def acquire_generate_tokens(r: Redis) -> bool:
    return acquire_tokens(r, RAG_REDIS_KEY, GENERATE_COST, RAG_TIMEOUT_S)


def acquire_nvidia_token(r: Redis) -> bool:
    return acquire_tokens(r, NVIDIA_REDIS_KEY, NVIDIA_COST, NVIDIA_TIMEOUT_S, capacity=NVIDIA_CAPACITY)


def get_rate_limit_snapshot(r: Redis) -> dict:
    router_available = get_available_tokens(r, ROUTER_REDIS_KEY, capacity=BUCKET_CAPACITY)
    rag_available    = get_available_tokens(r, RAG_REDIS_KEY, capacity=BUCKET_CAPACITY)

    return {
        "router_bucket": {
            "available": router_available,
            "used":      BUCKET_CAPACITY - router_available,
            "capacity":  BUCKET_CAPACITY,
        },
        "rag_bucket": {
            "available": rag_available,
            "used":      BUCKET_CAPACITY - rag_available,
            "capacity":  BUCKET_CAPACITY,
        },
    }