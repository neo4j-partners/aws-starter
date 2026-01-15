"""
Cognito Authentication Construct

Creates Cognito User Pool, Domain, Resource Server, and Machine Client
for OAuth2 M2M authentication with AgentCore Gateway.
"""

from aws_cdk import (
    RemovalPolicy,
    aws_cognito as cognito,
)
from constructs import Construct


class CognitoAuth(Construct):
    """
    Cognito authentication resources for OAuth2 M2M flow.

    Creates:
        - User Pool with simple password policy
        - User Pool Domain for token endpoint
        - Resource Server with invoke scope
        - Machine Client for client credentials flow
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        stack_name: str,
        account_id: str,
        region: str,
        resource_server_id: str = "neo4j-mcp",
        oauth_scope: str = "neo4j-mcp/invoke",
    ) -> None:
        super().__init__(scope, construct_id)

        self._stack_name = stack_name
        self._region = region
        self._oauth_scope = oauth_scope

        # User Pool
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"{stack_name}-user-pool",
            removal_policy=RemovalPolicy.DESTROY,
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=False,
                require_lowercase=False,
                require_digits=False,
                require_symbols=False,
            ),
        )

        # User Pool Domain
        self.user_pool_domain = cognito.UserPoolDomain(
            self,
            "UserPoolDomain",
            user_pool=self.user_pool,
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"{stack_name.lower()}-{account_id}"
            ),
        )

        # Resource Server
        self.resource_server = cognito.CfnUserPoolResourceServer(
            self,
            "ResourceServer",
            user_pool_id=self.user_pool.user_pool_id,
            identifier=resource_server_id,
            name="Neo4j MCP Resource Server",
            scopes=[
                cognito.CfnUserPoolResourceServer.ResourceServerScopeTypeProperty(
                    scope_name="invoke",
                    scope_description="Invoke Neo4j MCP tools through Gateway",
                )
            ],
        )

        # Machine Client (single client for all M2M auth)
        self.machine_client = cognito.CfnUserPoolClient(
            self,
            "MachineClient",
            client_name=f"{stack_name}-machine-client",
            user_pool_id=self.user_pool.user_pool_id,
            generate_secret=True,
            allowed_o_auth_flows=["client_credentials"],
            allowed_o_auth_flows_user_pool_client=True,
            allowed_o_auth_scopes=[oauth_scope],
            supported_identity_providers=["COGNITO"],
        )
        self.machine_client.add_dependency(self.resource_server)

    @property
    def cognito_domain_url(self) -> str:
        """Full Cognito domain URL for OAuth endpoints."""
        return f"https://{self._stack_name.lower()}-{self.user_pool.stack.account}.auth.{self._region}.amazoncognito.com"

    @property
    def discovery_url(self) -> str:
        """OIDC discovery URL for JWT validation."""
        return f"https://cognito-idp.{self._region}.amazonaws.com/{self.user_pool.user_pool_id}/.well-known/openid-configuration"

    @property
    def token_url(self) -> str:
        """Token endpoint URL."""
        return f"{self.cognito_domain_url}/oauth2/token"

    @property
    def oauth_scope(self) -> str:
        """OAuth scope for the resource server."""
        return self._oauth_scope
