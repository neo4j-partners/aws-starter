"""
Simple OAuth2 Demo Stack with RBAC

This CDK stack demonstrates OAuth2 authentication with role-based access control
(RBAC) using AgentCore Gateway, Lambda Interceptor, and Cognito. It creates:

1. Cognito User Pool with domain, groups (users/admin), and clients
2. Lambda Interceptor for JWT claim extraction and RBAC enforcement
3. MCP Server Runtime with auth-aware tools
4. AgentCore Gateway with JWT authorizer and request interceptor
5. OAuth2 Credential Provider for outbound authentication

Authentication Modes:
- M2M (client_credentials): Machine-to-machine, no user groups
- User (password): User authentication with cognito:groups for RBAC

The Lambda interceptor extracts groups from JWT and injects identity headers
(X-User-Id, X-User-Groups) for downstream tools. Admin tools are blocked
for non-admin users at the interceptor level.

Note: The Docker image is built locally using deploy.sh, not via CodeBuild.
"""

from pathlib import Path

from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    RemovalPolicy,
    CustomResource,
    Fn,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_cognito as cognito,
    aws_bedrockagentcore as bedrockagentcore,
)
from constructs import Construct

# Path to Lambda code directory
LAMBDA_DIR = str(Path(__file__).parent / "infra_utils")


class SimpleOAuthStack(Stack):
    """CDK Stack for OAuth2 + RBAC demo with AgentCore Gateway."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # =====================================================================
        # ECR REPOSITORY (created by deploy.sh, looked up here)
        # =====================================================================

        # The ECR repository is created by deploy.sh before CDK runs
        # This ensures the image can be pushed before the Runtime is created
        ecr_repo_name = f"{self.stack_name.lower()}-mcp-server"
        ecr_repository = ecr.Repository.from_repository_name(
            self, "ECRRepository", ecr_repo_name
        )

        # =====================================================================
        # COGNITO - USER POOL, DOMAIN, RESOURCE SERVER, MACHINE CLIENT
        # =====================================================================

        # User Pool
        user_pool = cognito.UserPool(self, "UserPool",
            user_pool_name=f"{self.stack_name}-user-pool",
            removal_policy=RemovalPolicy.DESTROY,
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=False,
                require_lowercase=False,
                require_digits=False,
                require_symbols=False
            )
        )

        # User Pool Domain (required for OAuth token endpoint)
        user_pool_domain = cognito.UserPoolDomain(self, "UserPoolDomain",
            user_pool=user_pool,
            cognito_domain=cognito.CognitoDomainOptions(
                # Domain must be globally unique - include account ID
                domain_prefix=f"{self.stack_name.lower()}-{self.account}"
            )
        )

        # Resource Server with custom scope for M2M authentication
        resource_server = cognito.CfnUserPoolResourceServer(self, "ResourceServer",
            user_pool_id=user_pool.user_pool_id,
            identifier="simple-oauth",
            name="Simple OAuth Resource Server",
            scopes=[
                cognito.CfnUserPoolResourceServer.ResourceServerScopeTypeProperty(
                    scope_name="invoke",
                    scope_description="Invoke MCP tools through Gateway"
                )
            ]
        )

        # Machine Client for client credentials flow (M2M)
        machine_client = cognito.CfnUserPoolClient(self, "MachineClient",
            client_name=f"{self.stack_name}-machine-client",
            user_pool_id=user_pool.user_pool_id,
            generate_secret=True,
            allowed_o_auth_flows=["client_credentials"],
            allowed_o_auth_flows_user_pool_client=True,
            allowed_o_auth_scopes=["simple-oauth/invoke"],
            supported_identity_providers=["COGNITO"]
        )
        machine_client.add_dependency(resource_server)

        # User Client for password-based auth (includes cognito:groups in token)
        user_client = cognito.CfnUserPoolClient(self, "UserClient",
            client_name=f"{self.stack_name}-user-client",
            user_pool_id=user_pool.user_pool_id,
            generate_secret=True,
            explicit_auth_flows=[
                "ALLOW_USER_PASSWORD_AUTH",
                "ALLOW_REFRESH_TOKEN_AUTH"
            ],
            # OAuth settings for user auth
            allowed_o_auth_flows=["code"],
            allowed_o_auth_flows_user_pool_client=True,
            allowed_o_auth_scopes=["openid", "email", "simple-oauth/invoke"],
            supported_identity_providers=["COGNITO"],
            callback_ur_ls=["http://localhost:8080/callback"],
            logout_ur_ls=["http://localhost:8080/logout"],
            # Token validity
            id_token_validity=60,
            access_token_validity=60,
            refresh_token_validity=30,
            token_validity_units=cognito.CfnUserPoolClient.TokenValidityUnitsProperty(
                access_token="minutes",
                id_token="minutes",
                refresh_token="days"
            )
        )
        user_client.add_dependency(resource_server)

        # =====================================================================
        # COGNITO USER GROUPS (for RBAC)
        # =====================================================================

        # Users group - basic access
        users_group = cognito.CfnUserPoolGroup(self, "UsersGroup",
            user_pool_id=user_pool.user_pool_id,
            group_name="users",
            description="Regular users with basic tool access",
            precedence=10  # Higher number = lower precedence
        )

        # Admin group - full access including admin tools
        admin_group = cognito.CfnUserPoolGroup(self, "AdminGroup",
            user_pool_id=user_pool.user_pool_id,
            group_name="admin",
            description="Administrators with full tool access",
            precedence=5  # Lower number = higher precedence
        )

        # Construct OAuth URLs
        cognito_domain = f"https://{self.stack_name.lower()}-{self.account}.auth.{self.region}.amazoncognito.com"
        discovery_url = f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}/.well-known/openid-configuration"

        # =====================================================================
        # IAM ROLES
        # =====================================================================

        # Runtime Execution Role
        runtime_role = iam.Role(self, "RuntimeRole",
            role_name=f"{self.stack_name}-runtime-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            inline_policies={
                "RuntimePolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="ECRImageAccess",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ecr:BatchGetImage",
                                "ecr:GetDownloadUrlForLayer",
                                "ecr:BatchCheckLayerAvailability"
                            ],
                            resources=[ecr_repository.repository_arn]
                        ),
                        iam.PolicyStatement(
                            sid="ECRTokenAccess",
                            effect=iam.Effect.ALLOW,
                            actions=["ecr:GetAuthorizationToken"],
                            resources=["*"]
                        ),
                        iam.PolicyStatement(
                            sid="CloudWatchLogs",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                                "logs:DescribeLogStreams",
                                "logs:DescribeLogGroups"
                            ],
                            resources=["*"]
                        ),
                        iam.PolicyStatement(
                            sid="XRayTracing",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "xray:PutTraceSegments",
                                "xray:PutTelemetryRecords"
                            ],
                            resources=["*"]
                        )
                    ]
                )
            }
        )

        # Gateway Execution Role
        gateway_role = iam.Role(self, "GatewayRole",
            role_name=f"{self.stack_name}-gateway-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            inline_policies={
                "GatewayPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="InvokeRuntime",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock-agentcore:InvokeRuntime",
                                "bedrock-agentcore:InvokeRuntimeWithResponseStream"
                            ],
                            resources=[f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/*"]
                        ),
                        iam.PolicyStatement(
                            sid="CloudWatchLogs",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents"
                            ],
                            resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/*"]
                        ),
                        # OAuth provider access for outbound authentication
                        iam.PolicyStatement(
                            sid="OAuthProviderAccess",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock-agentcore:GetOAuth2CredentialProvider",
                                "bedrock-agentcore:GetTokenVault",
                                "bedrock-agentcore:GetWorkloadAccessToken",
                                "bedrock-agentcore:GetResourceOauth2Token",
                                "secretsmanager:GetSecretValue"
                            ],
                            resources=[
                                f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:token-vault/*",
                                f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:workload-identity-directory/*",
                                f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:*"
                            ]
                        ),
                        # Bedrock model access
                        iam.PolicyStatement(
                            sid="BedrockModelAccess",
                            effect=iam.Effect.ALLOW,
                            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                            resources=[
                                "arn:aws:bedrock:*::foundation-model/*",
                                f"arn:aws:bedrock:*:{self.account}:inference-profile/*"
                            ]
                        ),
                        # Lambda interceptor invoke permission
                        # The Gateway needs this to call the REQUEST interceptor Lambda
                        iam.PolicyStatement(
                            sid="InvokeLambdaInterceptor",
                            effect=iam.Effect.ALLOW,
                            actions=["lambda:InvokeFunction"],
                            resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:{self.stack_name}-auth-interceptor"]
                        )
                    ]
                )
            }
        )

        # Custom Resource Lambda Role
        custom_resource_role = iam.Role(self, "CustomResourceRole",
            role_name=f"{self.stack_name}-custom-resource-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ],
            inline_policies={
                "CustomResourcePolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="AgentCoreOAuthProvider",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock-agentcore:CreateOAuth2CredentialProvider",
                                "bedrock-agentcore:DeleteOAuth2CredentialProvider",
                                "bedrock-agentcore:GetOAuth2CredentialProvider",
                                "bedrock-agentcore:ListOAuth2CredentialProviders",
                                "bedrock-agentcore:CreateTokenVault",
                                "bedrock-agentcore:GetTokenVault"
                            ],
                            resources=["*"]
                        ),
                        iam.PolicyStatement(
                            sid="AgentCoreRuntimeAccess",
                            effect=iam.Effect.ALLOW,
                            actions=["bedrock-agentcore:GetAgentRuntime"],
                            resources=["*"]
                        ),
                        iam.PolicyStatement(
                            sid="SecretsManagerAccess",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "secretsmanager:CreateSecret",
                                "secretsmanager:DeleteSecret",
                                "secretsmanager:GetSecretValue",
                                "secretsmanager:PutSecretValue"
                            ],
                            resources=["*"]
                        ),
                        iam.PolicyStatement(
                            sid="CognitoAccess",
                            effect=iam.Effect.ALLOW,
                            actions=["cognito-idp:DescribeUserPoolClient"],
                            resources=[user_pool.user_pool_arn]
                        )
                    ]
                )
            }
        )

        # =====================================================================
        # LAMBDA FUNCTIONS (using external code files)
        # =====================================================================

        # OAuth Provider Lambda
        oauth_provider_lambda = lambda_.Function(self, "OAuthProviderLambda",
            function_name=f"{self.stack_name}-oauth-provider",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="oauth_provider_lambda.handler",
            timeout=Duration.minutes(5),
            role=custom_resource_role,
            description="Creates OAuth2 Credential Provider for Gateway",
            code=lambda_.Code.from_asset(LAMBDA_DIR)
        )

        # Runtime Health Check Lambda
        runtime_health_check_lambda = lambda_.Function(self, "RuntimeHealthCheckLambda",
            function_name=f"{self.stack_name}-runtime-health-check",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="runtime_health_check_lambda.handler",
            timeout=Duration.minutes(10),
            role=custom_resource_role,
            description="Waits for Runtime to be ready before creating GatewayTarget",
            code=lambda_.Code.from_asset(LAMBDA_DIR)
        )

        # Auth Interceptor Lambda (REQUEST interceptor for RBAC)
        auth_interceptor_lambda = lambda_.Function(self, "AuthInterceptorLambda",
            function_name=f"{self.stack_name}-auth-interceptor",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="auth_interceptor_lambda.handler",
            timeout=Duration.seconds(30),
            memory_size=128,
            description="Extracts JWT claims and enforces group-based access control",
            code=lambda_.Code.from_asset(LAMBDA_DIR)
        )

        # Grant Gateway permission to invoke the interceptor
        auth_interceptor_lambda.add_permission(
            "GatewayInvokePermission",
            principal=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_arn=f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:gateway/*"
        )

        # =====================================================================
        # CUSTOM RESOURCES
        # =====================================================================

        # OAuth Provider Custom Resource
        oauth_provider = CustomResource(self, "OAuthProvider",
            service_token=oauth_provider_lambda.function_arn,
            properties={
                "ProviderName": f"{self.stack_name.lower().replace('-', '_')}_oauth_provider",
                "UserPoolId": user_pool.user_pool_id,
                "ClientId": machine_client.ref,
                "DiscoveryUrl": discovery_url,
                "Region": self.region
            }
        )
        oauth_provider.node.add_dependency(machine_client)

        oauth_provider_arn = oauth_provider.get_att_string("ProviderArn")

        # =====================================================================
        # AGENTCORE RUNTIME
        # =====================================================================

        mcp_runtime = bedrockagentcore.CfnRuntime(self, "MCPRuntime",
            agent_runtime_name=f"{self.stack_name.lower().replace('-', '_')}_mcp_server",
            agent_runtime_artifact=bedrockagentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=bedrockagentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=f"{ecr_repository.repository_uri}:latest"
                )
            ),
            role_arn=runtime_role.role_arn,
            network_configuration=bedrockagentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="MCP",
            authorizer_configuration=bedrockagentcore.CfnRuntime.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=bedrockagentcore.CfnRuntime.CustomJWTAuthorizerConfigurationProperty(
                    # Allow both M2M and user clients
                    allowed_clients=[machine_client.ref, user_client.ref],
                    discovery_url=discovery_url
                )
            ),
            description="Simple OAuth Demo MCP Server with RBAC"
        )

        # Runtime Health Check Custom Resource
        runtime_health_check = CustomResource(self, "RuntimeHealthCheck",
            service_token=runtime_health_check_lambda.function_arn,
            properties={
                "RuntimeArn": mcp_runtime.attr_agent_runtime_arn,
                "Region": self.region
            }
        )
        runtime_health_check.node.add_dependency(mcp_runtime)

        # =====================================================================
        # AGENTCORE GATEWAY
        # =====================================================================

        gateway = bedrockagentcore.CfnGateway(self, "Gateway",
            name=f"{self.stack_name.lower()}-gateway",
            role_arn=gateway_role.role_arn,
            protocol_type="MCP",
            protocol_configuration=bedrockagentcore.CfnGateway.GatewayProtocolConfigurationProperty(
                mcp=bedrockagentcore.CfnGateway.MCPGatewayConfigurationProperty(
                    supported_versions=["2025-03-26"]
                )
            ),
            authorizer_type="CUSTOM_JWT",
            authorizer_configuration=bedrockagentcore.CfnGateway.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=bedrockagentcore.CfnGateway.CustomJWTAuthorizerConfigurationProperty(
                    # Allow both M2M and user clients
                    allowed_clients=[machine_client.ref, user_client.ref],
                    discovery_url=discovery_url
                )
            ),
            # REQUEST Interceptor for RBAC enforcement
            # NOTE: Gateway role must have lambda:InvokeFunction permission for this to work!
            interceptor_configurations=[
                bedrockagentcore.CfnGateway.GatewayInterceptorConfigurationProperty(
                    interception_points=["REQUEST"],
                    interceptor=bedrockagentcore.CfnGateway.InterceptorConfigurationProperty(
                        lambda_=bedrockagentcore.CfnGateway.LambdaInterceptorConfigurationProperty(
                            arn=auth_interceptor_lambda.function_arn,
                        ),
                    ),
                    input_configuration=bedrockagentcore.CfnGateway.InterceptorInputConfigurationProperty(
                        pass_request_headers=True,
                    ),
                )
            ],
            description="Simple OAuth Demo Gateway with RBAC Interceptor"
        )

        # Construct Runtime URL for Gateway Target
        encoded_arn = Fn.join('%2F', Fn.split('/', Fn.join('%3A', Fn.split(':', mcp_runtime.attr_agent_runtime_arn))))
        runtime_invocation_url = Fn.join('', [
            f"https://bedrock-agentcore.{self.region}.amazonaws.com/runtimes/",
            encoded_arn,
            "/invocations"
        ])

        # Gateway Target
        gateway_target = bedrockagentcore.CfnGatewayTarget(self, "GatewayTarget",
            gateway_identifier=gateway.attr_gateway_identifier,
            name="mcp-server-target",
            description="Target for Simple OAuth MCP Server",
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
                            scopes=["simple-oauth/invoke"]
                        )
                    )
                )
            ]
        )
        gateway_target.add_dependency(gateway)
        gateway_target.add_dependency(mcp_runtime)
        gateway_target.node.add_dependency(runtime_health_check)

        # =====================================================================
        # OUTPUTS
        # =====================================================================

        CfnOutput(self, "CognitoUserPoolId",
            description="Cognito User Pool ID",
            value=user_pool.user_pool_id,
            export_name=f"{self.stack_name}-UserPoolId"
        )

        CfnOutput(self, "CognitoMachineClientId",
            description="Cognito Machine Client ID (for client credentials flow)",
            value=machine_client.ref,
            export_name=f"{self.stack_name}-MachineClientId"
        )

        CfnOutput(self, "CognitoUserClientId",
            description="Cognito User Client ID (for password-based auth with groups)",
            value=user_client.ref,
            export_name=f"{self.stack_name}-UserClientId"
        )

        CfnOutput(self, "CognitoTokenUrl",
            description="Cognito Token URL for OAuth2",
            value=f"{cognito_domain}/oauth2/token",
            export_name=f"{self.stack_name}-TokenUrl"
        )

        CfnOutput(self, "CognitoScope",
            description="OAuth2 Scope for M2M authentication",
            value="simple-oauth/invoke"
        )

        CfnOutput(self, "GatewayUrl",
            description="AgentCore Gateway URL",
            value=gateway.attr_gateway_url,
            export_name=f"{self.stack_name}-GatewayUrl"
        )

        CfnOutput(self, "GatewayId",
            description="AgentCore Gateway ID",
            value=gateway.attr_gateway_identifier,
            export_name=f"{self.stack_name}-GatewayId"
        )

        CfnOutput(self, "RuntimeArn",
            description="MCP Server Runtime ARN",
            value=mcp_runtime.attr_agent_runtime_arn,
            export_name=f"{self.stack_name}-RuntimeArn"
        )

        CfnOutput(self, "AuthInterceptorLambdaArn",
            description="Auth Interceptor Lambda ARN (for update-gateway)",
            value=auth_interceptor_lambda.function_arn,
            export_name=f"{self.stack_name}-AuthInterceptorLambdaArn"
        )

        CfnOutput(self, "DemoCommand",
            description="Command to run the demo",
            value="python client/demo.py"
        )
