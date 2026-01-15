"""
Neo4j MCP Server Stack

CDK stack for deploying the OFFICIAL Neo4j MCP server to AWS Bedrock AgentCore
with zero code changes using:
- OAuth2 M2M authentication (single client pattern)
- AgentCore Gateway with REQUEST interceptor for header transformation
- Per-request Neo4j credentials via X-Neo4j-Authorization header

The Gateway REQUEST interceptor transforms X-Neo4j-Authorization to Authorization,
enabling the official Neo4j MCP server to work with AgentCore without modification.

References:
- OFFICIAL_FTW.md: Proposal for zero-change deployment
- AWS Samples: amazon-bedrock-agentcore-samples/02-use-cases/site-reliability-agent-workshop/
"""

import os

from aws_cdk import (
    CfnOutput,
    Stack,
    aws_ecr as ecr,
)
from constructs import Construct

from neo4j_mcp.constructs.cognito import CognitoAuth
from neo4j_mcp.constructs.iam_roles import IamRoles
from neo4j_mcp.constructs.agentcore import AgentCoreResources


# Configuration constants
OAUTH_SCOPE = "neo4j-mcp/invoke"
RESOURCE_SERVER_ID = "neo4j-mcp"


class Neo4jMcpStack(Stack):
    """
    CDK Stack for Official Neo4j MCP Server on AWS Bedrock AgentCore.

    This stack deploys the OFFICIAL Neo4j MCP server with ZERO code changes
    using a Gateway REQUEST interceptor for header transformation.

    Creates:
        - ECR repository reference (created by deploy.sh)
        - Cognito User Pool with OAuth2 M2M client
        - IAM roles for Runtime, Gateway, and Custom Resources
        - Auth Interceptor Lambda (X-Neo4j-Authorization -> Authorization)
        - AgentCore Runtime with official Neo4j MCP server container
        - AgentCore Gateway with REQUEST interceptor
        - Gateway Target linking Gateway to Runtime
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stack_name_normalized = self.stack_name.lower().replace("-", "_")

        # =====================================================================
        # ECR REPOSITORY (created by deploy.sh, referenced here)
        # =====================================================================

        ecr_repo_name = f"{self.stack_name.lower()}-mcp-server"
        ecr_repository = ecr.Repository.from_repository_name(
            self, "ECRRepository", ecr_repo_name
        )

        # =====================================================================
        # COGNITO AUTHENTICATION
        # =====================================================================

        cognito_auth = CognitoAuth(
            self,
            "CognitoAuth",
            stack_name=self.stack_name,
            account_id=self.account,
            region=self.region,
            resource_server_id=RESOURCE_SERVER_ID,
            oauth_scope=OAUTH_SCOPE,
        )

        # =====================================================================
        # IAM ROLES
        # =====================================================================

        iam_roles = IamRoles(
            self,
            "IamRoles",
            stack_name=self.stack_name,
            region=self.region,
            account_id=self.account,
            ecr_repository_arn=ecr_repository.repository_arn,
            user_pool_arn=cognito_auth.user_pool.user_pool_arn,
        )

        # =====================================================================
        # AGENTCORE RESOURCES (with REQUEST interceptor for header transformation)
        # =====================================================================

        # Path to Lambda handlers (includes auth_interceptor.py)
        lambdas_path = os.path.join(os.path.dirname(__file__), "lambdas")

        # Neo4j URI from environment (set in .env, loaded by deploy.sh)
        neo4j_uri = os.environ.get("NEO4J_URI", "")
        if not neo4j_uri:
            raise ValueError(
                "NEO4J_URI environment variable is required. "
                "Set it in .env file: NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io"
            )

        agentcore = AgentCoreResources(
            self,
            "AgentCore",
            stack_name=self.stack_name,
            stack_name_normalized=stack_name_normalized,
            region=self.region,
            account_id=self.account,
            ecr_repository_uri=ecr_repository.repository_uri,
            runtime_role_arn=iam_roles.runtime_role.role_arn,
            gateway_role_arn=iam_roles.gateway_role.role_arn,
            custom_resource_role=iam_roles.custom_resource_role,
            machine_client_ref=cognito_auth.machine_client.ref,
            discovery_url=cognito_auth.discovery_url,
            oauth_scope=OAUTH_SCOPE,
            user_pool_id=cognito_auth.user_pool.user_pool_id,
            lambdas_path=lambdas_path,
            neo4j_uri=neo4j_uri,
        )

        # =====================================================================
        # OUTPUTS
        # =====================================================================

        CfnOutput(
            self,
            "CognitoUserPoolId",
            description="Cognito User Pool ID",
            value=cognito_auth.user_pool.user_pool_id,
            export_name=f"{self.stack_name}-UserPoolId",
        )

        CfnOutput(
            self,
            "CognitoMachineClientId",
            description="Cognito Machine Client ID",
            value=cognito_auth.machine_client.ref,
            export_name=f"{self.stack_name}-MachineClientId",
        )

        CfnOutput(
            self,
            "CognitoTokenUrl",
            description="Cognito Token URL",
            value=cognito_auth.token_url,
            export_name=f"{self.stack_name}-TokenUrl",
        )

        CfnOutput(
            self,
            "CognitoScope",
            description="OAuth2 Scope",
            value=OAUTH_SCOPE,
        )

        CfnOutput(
            self,
            "GatewayUrl",
            description="AgentCore Gateway URL",
            value=agentcore.gateway_url,
            export_name=f"{self.stack_name}-GatewayUrl",
        )

        CfnOutput(
            self,
            "GatewayId",
            description="AgentCore Gateway ID",
            value=agentcore.gateway_id,
            export_name=f"{self.stack_name}-GatewayId",
        )

        CfnOutput(
            self,
            "RuntimeArn",
            description="MCP Server Runtime ARN",
            value=agentcore.runtime_arn,
            export_name=f"{self.stack_name}-RuntimeArn",
        )

        CfnOutput(
            self,
            "AuthInterceptorLambdaArn",
            description="Auth Interceptor Lambda ARN",
            value=agentcore.auth_interceptor_arn,
            export_name=f"{self.stack_name}-AuthInterceptorArn",
        )

        CfnOutput(
            self,
            "DemoCommand",
            description="Command to test (requires Neo4j credentials in .env)",
            value="uv run python client/demo.py",
        )

        CfnOutput(
            self,
            "CredentialNote",
            description="How to provide Neo4j credentials",
            value="Set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in .env file",
        )
