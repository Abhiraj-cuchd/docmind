# infrastructure/stacks/api_stack.py

import aws_cdk as cdk
from aws_cdk import (
    aws_apigatewayv2        as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_lambda              as lambda_,
    aws_logs                as logs,
)
from constructs import Construct


class ApiStack(cdk.Stack):

    def __init__(
        self,
        scope:           Construct,
        construct_id:    str,
        submit_function: lambda_.Function,
        poll_function:   lambda_.Function,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── CloudWatch Log Group ───────────────────────────────────
        log_group = logs.LogGroup(
            self,
            "ApiLogs",
            log_group_name="/rag-mvp/api-gateway",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ── HTTP API ───────────────────────────────────────────────
        # CONCEPT: default_stage_options does not exist on HttpApi.
        # Throttling is configured on the default stage separately
        # after the API is created using CfnStage (L1 construct).
        self.api = apigw.HttpApi(
            self,
            "RagApi",
            api_name="rag-mvp-api",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                ],
                max_age=cdk.Duration.hours(1),
            ),
        )

        # ── Lambda Integrations ────────────────────────────────────
        submit_integration = integrations.HttpLambdaIntegration(
            "SubmitIntegration",
            submit_function,
            payload_format_version=apigw.PayloadFormatVersion.VERSION_2_0,
        )

        poll_integration = integrations.HttpLambdaIntegration(
            "PollIntegration",
            poll_function,
            payload_format_version=apigw.PayloadFormatVersion.VERSION_2_0,
        )

        # ── Routes ─────────────────────────────────────────────────
        self.api.add_routes(
            path="/query",
            methods=[apigw.HttpMethod.POST],
            integration=submit_integration,
        )

        self.api.add_routes(
            path="/result/{jobId}",
            methods=[apigw.HttpMethod.GET],
            integration=poll_integration,
        )

        self.api.add_routes(
            path="/upload",
            methods=[apigw.HttpMethod.POST],
            integration=submit_integration,
        )

        # ── Throttling via L1 CfnStage ────────────────────────────
        # CONCEPT: HttpApi (L2) doesn't expose throttling directly.
        # We reach down to the underlying CloudFormation resource
        # (L1 = CfnStage) to set throttle settings.
        # escape_id finds the auto-created default stage.
        cfn_stage = self.api.default_stage.node.default_child
        cfn_stage.default_route_settings = apigw.CfnStage.RouteSettingsProperty(
            throttling_burst_limit=50,
            throttling_rate_limit=20,
        )

        # ── Output ─────────────────────────────────────────────────
        cdk.CfnOutput(
            self,
            "ApiEndpoint",
            value=self.api.api_endpoint,
            description="API Gateway endpoint — use this in your frontend",
        )