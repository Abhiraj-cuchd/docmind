# infrastructure/stacks/storage_stack.py
#
# Creates:
#   S3 bucket  — PDF storage (rag-mvp-pdfs)
#   S3 bucket  — Audio storage (rag-mvp-audio) with 24hr lifecycle
#   SQS queue  — Ingestion queue + DLQ
#   SQS queue  — Query queue + DLQ
#   S3 → SQS   — Event notification wiring PDF uploads to ingestion queue

import aws_cdk as cdk
from aws_cdk import (
    aws_s3            as s3,
    aws_sqs           as sqs,
    aws_s3_notifications as s3n,
)
from constructs import Construct


class StorageStack(cdk.Stack):

    def __init__(
        self,
        scope:     Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Dead Letter Queues ─────────────────────────────────────
        # CONCEPT: A DLQ receives messages that failed processing
        # after max_receive_count attempts. Without a DLQ, failed
        # messages are silently deleted after retries. With a DLQ,
        # they accumulate so you can inspect what went wrong,
        # replay them after fixing the bug, or trigger an alarm.

        self.ingestion_dlq = sqs.Queue(
            self,
            "IngestionDLQ",
            queue_name="rag-ingestion-dlq",
            # CONCEPT: Messages in DLQ kept for 14 days.
            # Long enough to investigate failures and replay.
            retention_period=cdk.Duration.days(14),
        )

        self.query_dlq = sqs.Queue(
            self,
            "QueryDLQ",
            queue_name="rag-query-dlq",
            retention_period=cdk.Duration.days(14),
        )

        # ── Ingestion Queue ────────────────────────────────────────
        # CONCEPT: visibility_timeout must be >= Lambda timeout.
        # While a Lambda is processing a message, SQS hides it
        # (makes it invisible) for visibility_timeout seconds.
        # If Lambda finishes before timeout → deletes message.
        # If Lambda crashes → message reappears after timeout → retry.
        # Our indexer Lambda timeout is 5 minutes → set to 6 minutes
        # to give a comfortable buffer.

        self.ingestion_queue = sqs.Queue(
            self,
            "IngestionQueue",
            queue_name="rag-ingestion-queue",
            visibility_timeout=cdk.Duration.seconds(360),  # 6 minutes
            # CONCEPT: retention_period is how long unprocessed
            # messages stay in the queue. 4 days gives plenty of
            # time to fix a bug and replay messages.
            retention_period=cdk.Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,   # retry 3 times before DLQ
                queue=self.ingestion_dlq,
            ),
        )

        # ── Query Queue ────────────────────────────────────────────
        # Processor Lambda timeout is 5 minutes → 6 minute visibility.
        # max_receive_count=3 before DLQ — same as ingestion.

        self.query_queue = sqs.Queue(
            self,
            "QueryQueue",
            queue_name="rag-query-queue",
            visibility_timeout=cdk.Duration.seconds(360),  # 6 minutes
            retention_period=cdk.Duration.days(1),
            # CONCEPT: Query queue retention is 1 day (shorter than
            # ingestion). If a query isn't processed in 24 hours
            # something is seriously wrong. User has moved on anyway.
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.query_dlq,
            ),
        )

        # ── Tasks Queue ────────────────────────────────────────────
        # Generation Lambda timeout is 5 minutes → 6 minute visibility.
        # max_receive_count=3 before DLQ — same as query queue.

        self.tasks_dlq = sqs.Queue(
            self,
            "TasksDLQ",
            queue_name="rag-tasks-dlq",
            retention_period=cdk.Duration.days(7),
        )

        self.tasks_queue = sqs.Queue(
            self,
            "TasksQueue",
            queue_name="rag-tasks-queue",
            visibility_timeout=cdk.Duration.seconds(360),
            retention_period=cdk.Duration.days(1),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.tasks_dlq,
            ),
        )

        # ── PDF Bucket ─────────────────────────────────────────────
        self.pdf_bucket = s3.Bucket(
            self,
            "PdfBucket",
            # CONCEPT: bucket_name with account ID suffix ensures
            # global uniqueness — S3 bucket names are global across
            # all AWS accounts worldwide.
            bucket_name=f"rag-mvp-pdfs-{self.account}",

            # CONCEPT: PRIVATE means no public access — ever.
            # PDFs contain user data. Only Lambda IAM roles can access.
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,

            # Encrypt at rest using AWS managed keys — free, automatic
            encryption=s3.BucketEncryption.S3_MANAGED,

            # CONCEPT: versioning keeps old versions of PDFs if
            # a user re-uploads the same filename. Useful for debugging.
            versioned=False,   # keep simple for now

            # CONCEPT: CORS allows the frontend to PUT files directly
            # to S3 using presigned URLs — bypassing Lambda's 6MB limit.
            # Update pdf_bucket CORS to also allow GET
            cors=[
                s3.CorsRule(
                    allowed_methods=[
                        s3.HttpMethods.PUT,  # for upload
                        s3.HttpMethods.GET,  # for preview
                    ],
                    allowed_origins=["*"],  # tighten to your domain in prod
                    allowed_headers=["*"],
                    exposed_headers=[
                        "Content-Type",
                        "Content-Length",
                    ],
                    max_age=3000,
                )
            ],

            # Remove bucket when stack is deleted — ok for dev
            # Change to RETAIN for production
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── Audio Bucket ───────────────────────────────────────────
        self.audio_bucket = s3.Bucket(
            self,
            "AudioBucket",
            bucket_name=f"rag-mvp-audio-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,

            # CONCEPT: Lifecycle rule automatically deletes audio files
            # after 24 hours. Voice files are ephemeral — listened to
            # once, then worthless. Auto-deletion keeps storage clean
            # and costs near zero (tiny files, deleted quickly).
            lifecycle_rules=[
                s3.LifecycleRule(
                    expiration=cdk.Duration.days(1),
                    enabled=True,
                )
            ],

            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── S3 → SQS Event Notification ───────────────────────────
        # CONCEPT: When a PDF lands in the pdf_bucket under the
        # "uploads/" prefix, S3 automatically sends a notification
        # to the ingestion queue. This triggers the indexer Lambda
        # without any polling or manual triggering.
        # The Lambda wakes up, reads the S3 key from the SQS message,
        # downloads the PDF, and starts processing.
        self.pdf_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED_PUT,
            s3n.SqsDestination(self.ingestion_queue),
            # Only trigger for objects under uploads/ prefix
            # CONCEPT: prefix filter prevents triggering on any other
            # S3 operations in this bucket (e.g. CDK deployment artifacts)
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        # ── CloudFormation Outputs ─────────────────────────────────
        # CONCEPT: Outputs appear in the AWS Console after deploy
        # and can be queried with: aws cloudformation describe-stacks
        # Useful for debugging and for passing values to other tools.
        cdk.CfnOutput(
            self, "PdfBucketName",
            value=self.pdf_bucket.bucket_name,
            description="S3 bucket for uploaded PDFs",
        )
        cdk.CfnOutput(
            self, "AudioBucketName",
            value=self.audio_bucket.bucket_name,
            description="S3 bucket for voice audio files",
        )
        cdk.CfnOutput(
            self, "IngestionQueueUrl",
            value=self.ingestion_queue.queue_url,
            description="SQS queue for PDF ingestion jobs",
        )
        cdk.CfnOutput(
            self, "QueryQueueUrl",
            value=self.query_queue.queue_url,
            description="SQS queue for user queries",
        )