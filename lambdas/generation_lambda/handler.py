import json
from shared_lambda.rate_limiter    import get_redis_client
from generation_lambda.tasks.summarize   import summarize_conversation, summarize_document
from generation_lambda.tasks.flashcards  import generate_flashcards


RESULT_TTL = 3600


def handler(event, context):
    print(f"[Generation] Received {len(event['Records'])} SQS record(s)")
    for record in event["Records"]:
        _process_record(record)


def _process_record(record: dict) -> None:
    r    = get_redis_client()
    body = json.loads(record["body"])

    job_id          = body["job_id"]
    user_id         = body["user_id"]
    task_type       = body["task_type"]
    conversation_id = body.get("conversation_id")
    document_id     = body.get("document_id")

    print(f"[Generation] Job {job_id}: task_type={task_type} "
          f"user={user_id} conversation={conversation_id} document={document_id}")

    try:
        if task_type == "summarize_conversation":
            summarize_conversation(job_id, user_id, conversation_id, r)

        elif task_type == "summarize_document":
            summarize_document(job_id, user_id, document_id, r)

        elif task_type == "generate_flashcards":
            generate_flashcards(job_id, user_id, conversation_id, document_id, r)

        else:
            _write_result(r, job_id, {
                "status":  "error",
                "message": f"Unknown task_type: {task_type}",
            })

    except Exception as e:
        if "RATE_LIMIT_WAIT" in str(e):
            # Deliberate requeue — do NOT write to Redis.
            # SQS will redeliver the message when visibility timeout expires.
            print(f"[Generation] Job {job_id}: rate limit wait — requeuing")
            raise

        print(f"[Generation] Job {job_id}: failed — {e}")
        _write_result(r, job_id, {
            "status":  "error",
            "message": str(e),
        })
        raise


def _write_result(r, job_id: str, result: dict) -> None:
    r.setex(f"job:{job_id}", RESULT_TTL, json.dumps(result))
    print(f"[Generation] Redis result written: job={job_id} status={result.get('status')}")
