# infrastructure/stacks/compute_stack.py

import aws_cdk as cdk
from aws_cdk import (
    aws_lambda      as lambda_,
    aws_lambda_event_sources as lambda_events,
    aws_iam         as iam,
    aws_s3          as s3,
    aws_sqs         as sqs,
)
from constructs import Construct


class ComputeStack(cdk.Stack):

    def __init__(
        self,
        scope:           Construct,
        construct_id:    str,
        pdf_bucket:      s3.Bucket,
        audio_bucket:    s3.Bucket,
        ingestion_queue: sqs.Queue,
        query_queue:     sqs.Queue,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Secrets Manager IAM Policy ─────────────────────────────
        # Wildcard suffix covers AWS-appended 6-char secret suffix
        secrets_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                f"arn:aws:secretsmanager:{self.region}:{self.account}"
                f":secret:prod/serverless-rag-secrets-*"
            ],
        )

        # ── Bedrock IAM Policy ─────────────────────────────────────
        # CONCEPT: All Lambdas that call Titan (embedder, embed worker,
        # hyde) need this policy. bedrock:InvokeModel grants permission
        # to call the specific Titan model. No API key needed —
        # IAM handles auth for all Bedrock calls automatically.
        bedrock_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/"
                f"amazon.titan-embed-text-v2:0"
            ],
        )

        # ── Shared Layer ───────────────────────────────────────────
        deps_layer = lambda_.LayerVersion(
            self,
            "DepsLayer",
            code=lambda_.Code.from_asset(
                "../lambdas",
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install --no-cache-dir "
                        "-r shared_lambda/requirements.txt "
                        "-t /asset-output/python/lib/python3.11/site-packages/ "
                        "&& cp -r shared_lambda /asset-output/python/"
                    ],
                ),
            ),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_11],
            description="Shared deps + shared_lambda code layer",
        )

        common_env = {
            "SECRET_NAME": "prod/serverless-rag-secrets",
            "AWS_ACCOUNT":  self.account,
        }

        common_layers = [deps_layer]

        # ── Embed Queue + DLQ ──────────────────────────────────────
        embed_dlq = sqs.Queue(
            self,
            "EmbedDLQ",
            queue_name="rag-embed-dlq",
            retention_period=cdk.Duration.days(7),
        )

        self.embed_queue = sqs.Queue(
            self,
            "EmbedQueue",
            queue_name="rag-embed-queue",
            visibility_timeout=cdk.Duration.seconds(120),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=embed_dlq,
            ),
        )

        # ── Lambda 1 — Indexer (Container Image) ───────────────────
        # Handles: download → extract → chunk → store → enqueue embed jobs
        self.indexer_function = lambda_.DockerImageFunction(
            self,
            "IndexerFunction",
            function_name="rag-indexer",
            code=lambda_.DockerImageCode.from_image_asset(
                "../lambdas",
                file="ingestion_lambda/Dockerfile",
            ),
            timeout=cdk.Duration.minutes(5),
            memory_size=512,
            environment={
                **common_env,
                "PDF_BUCKET_NAME": pdf_bucket.bucket_name,
                "EMBED_QUEUE_URL": self.embed_queue.queue_url,
            },
        )

        pdf_bucket.grant_read(self.indexer_function)
        self.embed_queue.grant_send_messages(self.indexer_function)
        self.indexer_function.add_to_role_policy(secrets_policy)

        self.indexer_function.add_event_source(
            lambda_events.SqsEventSource(
                ingestion_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        # ── Lambda 2 — Embed Worker (Container Image) ──────────────
        # CONCEPT: Same Docker image as indexer — zero extra build cost.
        # CMD overridden to point to embed_worker.handler.
        # No concurrency limit — Titan has no rate limits.
        # Multiple workers can run simultaneously without throttling.
        self.embed_worker_function = lambda_.DockerImageFunction(
            self,
            "EmbedWorkerFunction",
            function_name="rag-embed-worker",
            code=lambda_.DockerImageCode.from_image_asset(
                "../lambdas",
                file="ingestion_lambda/Dockerfile",
                cmd=["embed_worker.handler"],
            ),
            timeout=cdk.Duration.seconds(90),
            memory_size=256,
            environment={
                **common_env,
            },
        )

        self.embed_queue.grant_consume_messages(self.embed_worker_function)
        self.embed_worker_function.add_to_role_policy(secrets_policy)
        self.embed_worker_function.add_to_role_policy(bedrock_policy)

        self.embed_worker_function.add_event_source(
            lambda_events.SqsEventSource(
                self.embed_queue,
                batch_size=1,
                report_batch_item_failures=True,
                # CONCEPT: No max_concurrency — Titan has no rate limits.
                # Workers process batches in parallel as fast as possible.
                # 19 batches with 5 parallel workers = ~4 parallel rounds
                # = ~12-15 seconds total vs 3+ minutes with Voyage AI.
            )
        )

        # ── Lambda 3 — Submit ──────────────────────────────────────
        self.submit_function = lambda_.Function(
            self,
            "SubmitFunction",
            function_name="rag-submit",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                "../lambdas/submit",
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c",
                        "cp -r . /asset-output/"
                    ],
                ),
            ),
            layers=common_layers,
            timeout=cdk.Duration.seconds(10),
            memory_size=256,
            environment={
                **common_env,
                "QUERY_QUEUE_URL": query_queue.queue_url,
                "PDF_BUCKET_NAME": pdf_bucket.bucket_name,
            },
        )

        query_queue.grant_send_messages(self.submit_function)
        self.submit_function.add_to_role_policy(secrets_policy)
        self.submit_function.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:PutObject",  # already there for upload
                    "s3:GetObject",  # new — for presigned GET URLs
                ],
                resources=[f"{pdf_bucket.bucket_arn}/uploads/*"],
            )
        )

        # ── Lambda 4 — Query Processor ─────────────────────────────
        self.processor_function = lambda_.Function(
            self,
            "ProcessorFunction",
            function_name="rag-processor",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                "../lambdas/query_lambda",
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c",
                        "cp -r . /asset-output/"
                    ],
                ),
            ),
            layers=common_layers,
            timeout=cdk.Duration.minutes(5),
            memory_size=512,
            environment={
                **common_env,
                "VOICE_BUCKET_NAME": audio_bucket.bucket_name,
            },
        )

        audio_bucket.grant_put(self.processor_function)
        audio_bucket.grant_read(self.processor_function)
        self.processor_function.add_to_role_policy(secrets_policy)
        self.processor_function.add_to_role_policy(bedrock_policy)
        self.processor_function.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[f"{audio_bucket.bucket_arn}/*"],
            )
        )

        self.processor_function.add_event_source(
            lambda_events.SqsEventSource(
                query_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        # ── Lambda 5 — Delete Document ─────────────────────────────
        self.delete_function = lambda_.Function(
            self,
            "DeleteFunction",
            function_name="rag-delete",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                "../lambdas/delete_lambda",
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=["bash", "-c", "cp -r . /asset-output/"],
                ),
            ),
            layers=common_layers,
            timeout=cdk.Duration.seconds(15),
            memory_size=128,
            environment={
                **common_env,
                "PDF_BUCKET_NAME":   pdf_bucket.bucket_name,
                "VOICE_BUCKET_NAME": audio_bucket.bucket_name,
            },
        )

        self.delete_function.add_to_role_policy(secrets_policy)
        self.delete_function.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:DeleteObject"],
                resources=[f"{pdf_bucket.bucket_arn}/uploads/*"],
            )
        )
        self.delete_function.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:DeleteObject"],
                resources=[f"{audio_bucket.bucket_arn}/audio/*"],
            )
        )

        # ── Lambda 6 — Poll ────────────────────────────────────────
        self.poll_function = lambda_.Function(
            self,
            "PollFunction",
            function_name="rag-poll",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                "../lambdas/poll",
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c",
                        "cp -r . /asset-output/"
                    ],
                ),
            ),
            layers=common_layers,
            timeout=cdk.Duration.seconds(10),
            memory_size=128,
            environment=common_env,
        )

        self.poll_function.add_to_role_policy(secrets_policy)

        # ── Outputs ────────────────────────────────────────────────
        cdk.CfnOutput(self, "IndexerFunctionArn",
                      value=self.indexer_function.function_arn)
        cdk.CfnOutput(self, "EmbedWorkerFunctionArn",
                      value=self.embed_worker_function.function_arn)
        cdk.CfnOutput(self, "EmbedQueueUrl",
                      value=self.embed_queue.queue_url)
        cdk.CfnOutput(self, "SubmitFunctionArn",
                      value=self.submit_function.function_arn)
        cdk.CfnOutput(self, "ProcessorFunctionArn",
                      value=self.processor_function.function_arn)
        cdk.CfnOutput(self, "DeleteFunctionArn",
                      value=self.delete_function.function_arn)
        cdk.CfnOutput(self, "PollFunctionArn",
                      value=self.poll_function.function_arn)