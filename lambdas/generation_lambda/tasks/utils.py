import json

RESULT_TTL = 3600


def write_result(r, job_id: str, result: dict) -> None:
    r.setex(f"job:{job_id}", RESULT_TTL, json.dumps(result))
    print(f"[Generation] Redis result written: job={job_id} status={result.get('status')}")
