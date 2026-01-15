"""
IAM Roles Construct

Creates IAM roles required for AgentCore Runtime, Gateway, and Lambda
custom resources.

Note: The official Neo4j MCP server receives credentials via the
Authorization header (transformed from X-Neo4j-Authorization by the
Gateway interceptor), so no Secrets Manager access is needed.
"""

from aws_cdk import aws_iam as iam
from constructs import Construct


class IamRoles(Construct):
    """
    IAM roles for Official Neo4j MCP Server deployment.

    Creates:
        - Runtime Role: For AgentCore Runtime to pull ECR images and write logs
        - Gateway Role: For AgentCore Gateway to invoke Runtime and access OAuth
        - Custom Resource Role: For Lambda functions managing OAuth providers
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        stack_name: str,
        region: str,
        account_id: str,
        ecr_repository_arn: str,
        user_pool_arn: str,
    ) -> None:
        super().__init__(scope, construct_id)

        # Runtime Role
        self.runtime_role = iam.Role(
            self,
            "RuntimeRole",
            role_name=f"{stack_name}-runtime-role",
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
                                "ecr:BatchCheckLayerAvailability",
                            ],
                            resources=[ecr_repository_arn],
                        ),
                        iam.PolicyStatement(
                            sid="ECRTokenAccess",
                            effect=iam.Effect.ALLOW,
                            actions=["ecr:GetAuthorizationToken"],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            sid="CloudWatchLogs",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                                "logs:DescribeLogStreams",
                                "logs:DescribeLogGroups",
                            ],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            sid="XRayTracing",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "xray:PutTraceSegments",
                                "xray:PutTelemetryRecords",
                            ],
                            resources=["*"],
                        ),
                        # Note: No Secrets Manager access needed - credentials come
                        # via Authorization header (transformed by Gateway interceptor)
                    ]
                )
            },
        )

        # Gateway Role
        self.gateway_role = iam.Role(
            self,
            "GatewayRole",
            role_name=f"{stack_name}-gateway-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            inline_policies={
                "GatewayPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="InvokeRuntime",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock-agentcore:InvokeRuntime",
                                "bedrock-agentcore:InvokeRuntimeWithResponseStream",
                            ],
                            resources=[f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/*"],
                        ),
                        iam.PolicyStatement(
                            sid="CloudWatchLogs",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                            ],
                            resources=[f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/*"],
                        ),
                        iam.PolicyStatement(
                            sid="OAuthProviderAccess",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock-agentcore:GetOAuth2CredentialProvider",
                                "bedrock-agentcore:GetTokenVault",
                                "bedrock-agentcore:GetWorkloadAccessToken",
                                "bedrock-agentcore:GetResourceOauth2Token",
                                "secretsmanager:GetSecretValue",
                            ],
                            resources=[
                                f"arn:aws:bedrock-agentcore:{region}:{account_id}:token-vault/*",
                                f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/*",
                                f"arn:aws:secretsmanager:{region}:{account_id}:secret:*",
                            ],
                        ),
                        iam.PolicyStatement(
                            sid="BedrockModelAccess",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock:InvokeModel",
                                "bedrock:InvokeModelWithResponseStream",
                            ],
                            resources=[
                                "arn:aws:bedrock:*::foundation-model/*",
                                f"arn:aws:bedrock:*:{account_id}:inference-profile/*",
                            ],
                        ),
                        # Lambda interceptor invoke permission
                        # Gateway needs this to call the REQUEST interceptor Lambda
                        iam.PolicyStatement(
                            sid="InvokeLambdaInterceptor",
                            effect=iam.Effect.ALLOW,
                            actions=["lambda:InvokeFunction"],
                            resources=[
                                f"arn:aws:lambda:{region}:{account_id}:function:{stack_name}-auth-interceptor"
                            ],
                        ),
                    ]
                )
            },
        )

        # Custom Resource Role (for Lambda functions)
        self.custom_resource_role = iam.Role(
            self,
            "CustomResourceRole",
            role_name=f"{stack_name}-custom-resource-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
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
                                "bedrock-agentcore:GetTokenVault",
                                "bedrock-agentcore:GetAgentRuntime",
                            ],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            sid="CognitoAccess",
                            effect=iam.Effect.ALLOW,
                            actions=["cognito-idp:DescribeUserPoolClient"],
                            resources=[user_pool_arn],
                        ),
                        iam.PolicyStatement(
                            sid="SecretsManagerAccess",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "secretsmanager:CreateSecret",
                                "secretsmanager:DeleteSecret",
                            ],
                            resources=["*"],
                        ),
                    ]
                )
            },
        )
