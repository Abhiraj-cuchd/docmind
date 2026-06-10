import json
import re
import time
import requests
from shared_lambda.secrets import get_secret

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL   = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

MAX_RETRIES  = 3
RETRY_DELAY  = 2


def generate(messages: list[dict], max_tokens: int = 4096, temperature: float = 0.6) -> str:
    """
    Single Nemotron call with retry/backoff. Returns raw text.
    No <think> stripping — Nemotron does not emit reasoning tags.
    """
    api_key     = get_secret("NVIDIA_API_KEY")
    retry_delay = RETRY_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                NVIDIA_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                    "Accept":        "application/json",
                },
                json={
                    "model":               NVIDIA_MODEL,
                    "messages":            messages,
                    "max_tokens":          max_tokens,
                    "temperature":         temperature,
                    "top_p":               0.95,
                    "frequency_penalty":   0,
                    "presence_penalty":    0,
                    "stream":              False,
                },
                timeout=90,
            )

            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"] or ""

            elif response.status_code == 429:
                wait = retry_delay * attempt * 2
                print(f"[SummarizerLLM] Rate limited. Waiting {wait}s (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)

            elif response.status_code >= 500:
                print(f"[SummarizerLLM] Server error {response.status_code}. "
                      f"Waiting {retry_delay}s (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(retry_delay)
                retry_delay *= 2

            else:
                raise ValueError(
                    f"[SummarizerLLM] API error {response.status_code}: {response.text}"
                )

        except requests.exceptions.Timeout:
            print(f"[SummarizerLLM] Timeout. Waiting {retry_delay}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(retry_delay)
            retry_delay *= 2

        except requests.exceptions.ConnectionError:
            print(f"[SummarizerLLM] Connection error. Waiting {retry_delay}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(retry_delay)
            retry_delay *= 2

    raise Exception(f"[SummarizerLLM] API failed after {MAX_RETRIES} attempts. SQS will retry.")


def generate_json(messages: list[dict]) -> list[dict]:
    """
    Calls Nemotron expecting a JSON array of {question, answer} objects.
    Falls back to extracting the first balanced [...] block if the model
    wraps the array in prose. Raises ValueError if still unparseable
    (deterministic failure — goes to DLQ after 3 SQS attempts).
    """
    raw = generate(messages, max_tokens=2048, temperature=0.3)

    # Fast path — response is already a bare JSON array
    stripped = raw.strip()
    if stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Fallback — extract first balanced [...] from prose-wrapped output
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"[SummarizerLLM] generate_json: could not parse JSON array from response. "
        f"Raw (first 200 chars): {raw[:200]}"
    )
