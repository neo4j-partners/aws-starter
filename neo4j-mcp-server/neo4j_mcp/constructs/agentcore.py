"""
AgentCore Resources Construct

Creates AgentCore Runtime, Gateway, and GatewayTarget for the MCP server.

This construct deploys the official Neo4j MCP server with zero code changes
using a REQUEST interceptor for header transformation. The interceptor
transforms X-Neo4j-Authorization to Authorization, enabling the official
server to receive per-request Basic auth credentials.

References:
- AWS Samples: amazon-bedrock-agentcore-samples/02-use-cases/site-reliability-agent-workshop/
- Interceptor docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html
"""

from aws_cdk import (
    CustomResource,
    Duration,
    Fn,
    aws_bedrockagentcore as bedrockagentcore,
    aws_iam as iam,
    aws_lambda as lambda_,
)
from constructs import Construct
import os


# MCP Protocol versions supported by AgentCore
# Supported by AgentCore: 2025-11-25, 2025-03-26, 2025-06-18
MCP_PROTOCOL_VERSIONS = ["2025-11-25", "2025-03-26", "2025-06-18"]


class AgentCoreResources(Construct):
    """
    AgentCore Runtime and Gateway resources.

    Creates:
        - Auth Interceptor Lambda (transforms X-Neo4j-Authorization to Authorization)
        - MCP Runtime with official Neo4j MCP server container
        - OAuth2 Credential Provider (via custom resource)
        - Runtime Ready custom resource (waits for READY state)
        - Gateway with REQUEST interceptor for public HTTPS access
        - GatewayTarget linking Gateway to Runtime
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        stack_name: str,
        stack_name_normalized: str,
        region: str,
        account_id: str,
        ecr_repository_uri: str,
        runtime_role_arn: str,
        gateway_role_arn: str,
        custom_resource_role,
        machine_client_ref: str,
        discovery_url: str,
        oauth_scope: str,
        user_pool_id: str,
        lambdas_path: str,
        neo4j_uri: str,
    ) -> None:
        super().__init__(scope, construct_id)

        # =====================================================================
        # LAMBDA FUNCTIONS
        # =====================================================================

        # OAuth Provider Lambda (Custom Resource)
        oauth_provider_lambda = lambda_.Function(
            self,
            "OAuthProviderLambda",
            function_name=f"{stack_name}-oauth-provider",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="oauth_provider.handler",
            code=lambda_.Code.from_asset(lambdas_path),
            timeout=Duration.minutes(5),
            role=custom_resource_role,
            description="Creates OAuth2 Credential Provider for Gateway",
        )

        # Runtime Wait Lambda (Custom Resource)
        runtime_wait_lambda = lambda_.Function(
            self,
            "RuntimeWaitLambda",
            function_name=f"{stack_name}-runtime-wait",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="runtime_wait.handler",
            code=lambda_.Code.from_asset(lambdas_path),
            timeout=Duration.minutes(10),
            role=custom_resource_role,
            description="Waits for AgentCore Runtime to be READY",
        )

        # =====================================================================
        # AUTH INTERCEPTOR LAMBDA (REQUEST interceptor for header transformation)
        # =====================================================================
        # Reference: amazon-bedrock-agentcore-samples/02-use-cases/
        #            site-reliability-agent-workshop/lab_helpers/lab_03/interceptor-request.py

        auth_interceptor_lambda = lambda_.Function(
            self,
            "AuthInterceptorLambda",
            function_name=f"{stack_name}-auth-interceptor",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="auth_interceptor.handler",
            code=lambda_.Code.from_asset(lambdas_path),
            timeout=Duration.seconds(30),
            memory_size=128,
            description="Transforms X-Neo4j-Authorization to Authorization header",
        )

        # Grant Gateway permission to invoke the interceptor Lambda
        # Reference: amazon-bedrock-agentcore-samples interceptor_deployer.py
        auth_interceptor_lambda.add_permission(
            "GatewayInvokePermission",
            principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_arn=f"arn:aws:bedrock-agentcore:{region}:{account_id}:gateway/*",
        )

        # =====================================================================
        # OAUTH PROVIDER CUSTOM RESOURCE
        # =====================================================================

        oauth_provider = CustomResource(
            self,
            "OAuthProvider",
            service_token=oauth_provider_lambda.function_arn,
            properties={
                "ProviderName": f"{stack_name_normalized}_oauth_provider",
                "UserPoolId": user_pool_id,
                "ClientId": machine_client_ref,
                "DiscoveryUrl": discovery_url,
                "Region": region,
            },
        )

        oauth_provider_arn = oauth_provider.get_att_string("ProviderArn")

        # =====================================================================
        # AGENTCORE RUNTIME
        # =====================================================================

        # Official Neo4j MCP Server Environment Variables
        # Reference: /Users/ryanknight/projects/mcp/internal/config/config.go
        # The official server receives Neo4j credentials via Authorization header
        # (transformed from X-Neo4j-Authorization by the interceptor)
        self.runtime = bedrockagentcore.CfnRuntime(
            self,
            "MCPRuntime",
            agent_runtime_name=f"{stack_name_normalized}_mcp_server",
            agent_runtime_artifact=bedrockagentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=bedrockagentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=f"{ecr_repository_uri}:latest"
                )
            ),
            role_arn=runtime_role_arn,
            network_configuration=bedrockagentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="MCP",
            authorizer_configuration=bedrockagentcore.CfnRuntime.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=bedrockagentcore.CfnRuntime.CustomJWTAuthorizerConfigurationProperty(
                    allowed_clients=[machine_client_ref],
                    discovery_url=discovery_url,
                )
            ),
            environment_variables={
                # Neo4j database URI (from .env via stack parameter)
                "NEO4J_URI": neo4j_uri,
                # Transport mode for HTTP (required for AgentCore)
                "NEO4J_MCP_TRANSPORT": "http",
                # Use header-based auth for per-request credentials
                "NEO4J_MCP_HTTP_AUTH_MODE": "header",
                # Use custom header for Neo4j credentials (not standard Authorization)
                # This is required because Gateway's OAuth provider sets Authorization
                # header for Runtime auth, which would overwrite Neo4j credentials.
                "NEO4J_MCP_HTTP_AUTH_HEADER": "X-Neo4j-Authorization",
                # HTTP port must match AgentCore Runtime expectations
                "NEO4J_MCP_HTTP_PORT": "8000",
                # CRITICAL: Listen on all interfaces for container access (default is 127.0.0.1)
                "NEO4J_MCP_HTTP_HOST": "0.0.0.0",
                # Enable debug logging to troubleshoot request handling
                "NEO4J_LOG_LEVEL": "debug",
            },
            description="Official Neo4j MCP Server Runtime (unmodified)",
        )

        # Wait for Runtime to be READY
        runtime_ready = CustomResource(
            self,
            "RuntimeReady",
            service_token=runtime_wait_lambda.function_arn,
            properties={
                "RuntimeArn": self.runtime.attr_agent_runtime_arn,
                "Region": region,
                "MaxWaitSeconds": "300",
            },
        )
        runtime_ready.node.add_dependency(self.runtime)

        # =====================================================================
        # AGENTCORE GATEWAY
        # =====================================================================

        # Gateway with REQUEST interceptor for header transformation
        # Reference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-configuration.html
        self.gateway = bedrockagentcore.CfnGateway(
            self,
            "Gateway",
            name=f"{stack_name.lower()}-gateway",
            role_arn=gateway_role_arn,
            protocol_type="MCP",
            protocol_configuration=bedrockagentcore.CfnGateway.GatewayProtocolConfigurationProperty(
                mcp=bedrockagentcore.CfnGateway.MCPGatewayConfigurationProperty(
                    supported_versions=MCP_PROTOCOL_VERSIONS
                )
            ),
            authorizer_type="CUSTOM_JWT",
            authorizer_configuration=bedrockagentcore.CfnGateway.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=bedrockagentcore.CfnGateway.CustomJWTAuthorizerConfigurationProperty(
                    allowed_clients=[machine_client_ref],
                    discovery_url=discovery_url,
                )
            ),
            # REQUEST Interceptor for header transformation
            # NOTE: Gateway role must have lambda:InvokeFunction permission for this to work!
            # Reference: simple-oauth-gateway simple_oauth_stack.py lines 458-470
            interceptor_configurations=[
                bedrockagentcore.CfnGateway.GatewayInterceptorConfigurationProperty(
                    interception_points=["REQUEST"],
                    interceptor=bedrockagentcore.CfnGateway.InterceptorConfigurationProperty(
                        lambda_=bedrockagentcore.CfnGateway.LambdaInterceptorConfigurationProperty(
                            arn=auth_interceptor_lambda.function_arn,
                        ),
                    ),
                    # Pass headers to interceptor so it can read X-Neo4j-Authorization
                    input_configuration=bedrockagentcore.CfnGateway.InterceptorInputConfigurationProperty(
                        pass_request_headers=True,
                    ),
                )
            ],
            description="Neo4j MCP Gateway with Auth Header Transformation",
        )

        # Expose auth interceptor Lambda ARN for stack outputs
        self.auth_interceptor_lambda = auth_interceptor_lambda

        # =====================================================================
        # GATEWAY TARGET
        # =====================================================================

        # Construct Runtime URL (URL-encoded ARN)
        encoded_arn = Fn.join(
            "%2F",
            Fn.split("/", Fn.join("%3A", Fn.split(":", self.runtime.attr_agent_runtime_arn))),
        )
        runtime_invocation_url = Fn.join(
            "",
            [
                f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/",
                encoded_arn,
                "/invocations",
            ],
        )

        gateway_target = bedrockagentcore.CfnGatewayTarget(
            self,
            "GatewayTarget",
            gateway_identifier=self.gateway.attr_gateway_identifier,
            name="mcp-server-target",
            description="Target for Neo4j MCP Server",
            target_configuration=bedrockagentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=bedrockagentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    mcp_server=bedrockagentcore.CfnGatewayTarget.McpServerTargetConfigurationProperty(
                        endpoint=runtime_invocation_url
                    )
                )
            ),
            credential_provider_configurations=[
                bedrockagentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                    credential_provider_type="OAUTH",
                    credential_provider=bedrockagentcore.CfnGatewayTarget.CredentialProviderProperty(
                        oauth_credential_provider=bedrockagentcore.CfnGatewayTarget.OAuthCredentialProviderProperty(
                            provider_arn=oauth_provider_arn,
                            scopes=[oauth_scope],
                        )
                    ),
                )
            ],
        )
        gateway_target.add_dependency(self.gateway)
        gateway_target.node.add_dependency(runtime_ready)
        gateway_target.node.add_dependency(oauth_provider)

    @property
    def runtime_arn(self) -> str:
        """ARN of the MCP Runtime."""
        return self.runtime.attr_agent_runtime_arn

    @property
    def gateway_url(self) -> str:
        """URL of the MCP Gateway."""
        return self.gateway.attr_gateway_url

    @property
    def gateway_id(self) -> str:
        """ID of the MCP Gateway."""
        return self.gateway.attr_gateway_identifier

    @property
    def auth_interceptor_arn(self) -> str:
        """ARN of the Auth Interceptor Lambda."""
        return self.auth_interceptor_lambda.function_arn
