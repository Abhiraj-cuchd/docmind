# infrastructure/app.py
# CDK app entry point — instantiates all three stacks in order.
#
# CONCEPT: Stacks are deployed in dependency order.
# StorageStack has no dependencies — create first.
# ComputeStack depends on StorageStack (needs bucket + queue names).
# ApiStack depends on ComputeStack (needs Lambda ARNs).
# CDK resolves these automatically via cross-stack references.

import aws_cdk as cdk
from stacks.storage_stack  import StorageStack
from stacks.compute_stack  import ComputeStack
from stacks.api_stack      import ApiStack

app = cdk.App()

# ── Environment ────────────────────────────────────────────────────────
# CONCEPT: env pins the stack to a specific AWS account and region.
# Without this CDK deploys to "environment-agnostic" mode which
# can't resolve some cross-stack references. Always pin for production.
env = cdk.Environment(
    account="354140340421",   # replace with your account ID
    region="ap-south-1",             # Mumbai — closest to India
)

# ── Stack 1: Storage ───────────────────────────────────────────────────
storage = StorageStack(
    app,
    "RagStorageStack",
    env=env,
    description="RAG MVP — S3 buckets and SQS queues",
)

# ── Stack 2: Compute ───────────────────────────────────────────────────
compute = ComputeStack(
    app,
    "RagComputeStack",
    env=env,
    description="RAG MVP — Lambda functions and IAM roles",
    # Pass storage resources as constructor params
    # CONCEPT: Cross-stack references — ComputeStack receives
    # actual CDK objects from StorageStack, not string names.
    # CDK automatically creates CloudFormation exports/imports.
    pdf_bucket=storage.pdf_bucket,
    audio_bucket=storage.audio_bucket,
    ingestion_queue=storage.ingestion_queue,
    query_queue=storage.query_queue,
    tasks_queue=storage.tasks_queue,
)

# ── Stack 3: API ───────────────────────────────────────────────────────
api = ApiStack(
    app,
    "RagApiStack",
    env=env,
    description="RAG MVP — API Gateway routes and CORS",
    submit_function=compute.submit_function,
    poll_function=compute.poll_function,
    delete_function=compute.delete_function,
)

app.synth()