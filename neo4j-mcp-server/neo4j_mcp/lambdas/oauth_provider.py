"""
OAuth2 Credential Provider Lambda Handler

Custom resource handler that creates/deletes OAuth2 credential providers
in Amazon Bedrock AgentCore for Gateway authentication.

This Lambda handles the lifecycle of OAuth2 providers that enable
the Gateway to authenticate with the Runtime using machine-to-machine
(M2M) credentials from Cognito.
"""

import json
import logging
from typing import Any

import boto3
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def send_cfn_response(
    event: dict,
    status: str,
    reason: str = None,
    data: dict = None,
    physical_resource_id: str = None
) -> dict:
    """
    Send response back to CloudFormation.

    Args:
        event: CloudFormation event
        status: SUCCESS or FAILED
        reason: Reason message for the response
        data: Optional data to include in response
        physical_resource_id: Resource ID for CloudFormation

    Returns:
        The response body sent to CloudFormation
    """
    response_body = {
        "Status": status,
        "Reason": reason or f"{status}: See CloudWatch logs",
        "PhysicalResourceId": physical_resource_id or event.get("PhysicalResourceId", "oauth-provider"),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {}
    }

    logger.info(f"Sending CFN response: Status={status}")

    http = urllib3.PoolManager()
    http.request(
        "PUT",
        event["ResponseURL"],
        body=json.dumps(response_body).encode("utf-8"),
        headers={"Content-Type": ""}
    )
    return response_body


def get_client_secret(cognito_client: Any, user_pool_id: str, client_id: str) -> str:
    """
    Get client secret from Cognito User Pool Client.

    Args:
        cognito_client: Boto3 Cognito client
        user_pool_id: User Pool ID
        client_id: Client ID

    Returns:
        Client secret string
    """
    response = cognito_client.describe_user_pool_client(
        UserPoolId=user_pool_id,
        ClientId=client_id
    )
    return response["UserPoolClient"]["ClientSecret"]


def delete_existing_provider(agentcore_client: Any, provider_name: str) -> None:
    """
    Delete an existing OAuth2 provider if it exists.

    This is necessary because providers may have stale credentials
    from deleted user pools, so we always recreate them.

    Args:
        agentcore_client: Boto3 AgentCore client
        provider_name: Name of the provider to delete
    """
    try:
        providers = agentcore_client.list_oauth2_credential_providers()
        for provider in providers.get("credentialProviders", []):
            if provider.get("name") == provider_name:
                logger.info(f"Found existing provider, deleting: {provider_name}")
                agentcore_client.delete_oauth2_credential_provider(name=provider_name)
                logger.info(f"Deleted existing provider: {provider_name}")
                break
    except Exception as e:
        logger.warning(f"Error checking/deleting existing provider: {e}")


def create_oauth2_provider(
    agentcore_client: Any,
    provider_name: str,
    discovery_url: str,
    client_id: str,
    client_secret: str
) -> str:
    """
    Create an OAuth2 Credential Provider.

    Args:
        agentcore_client: Boto3 AgentCore client
        provider_name: Name for the new provider
        discovery_url: OIDC discovery URL
        client_id: Cognito client ID
        client_secret: Cognito client secret

    Returns:
        ARN of the created provider
    """
    response = agentcore_client.create_oauth2_credential_provider(
        name=provider_name,
        credentialProviderVendor="CustomOauth2",
        oauth2ProviderConfigInput={
            "customOauth2ProviderConfig": {
                "oauthDiscovery": {"discoveryUrl": discovery_url},
                "clientId": client_id,
                "clientSecret": client_secret
            }
        }
    )
    return response["credentialProviderArn"]


def handle_delete(agentcore_client: Any, provider_name: str) -> None:
    """
    Handle Delete request for the custom resource.

    Args:
        agentcore_client: Boto3 AgentCore client
        provider_name: Name of the provider to delete
    """
    try:
        agentcore_client.delete_oauth2_credential_provider(name=provider_name)
        logger.info(f"Deleted OAuth provider: {provider_name}")
    except agentcore_client.exceptions.ResourceNotFoundException:
        logger.info(f"Provider already deleted: {provider_name}")
    except Exception as e:
        logger.warning(f"Could not delete provider: {e}")


def handler(event: dict, context: Any) -> dict:
    """
    CloudFormation Custom Resource handler.

    Creates or deletes an OAuth2 credential provider for AgentCore Gateway.

    Required ResourceProperties:
        - ProviderName: Name for the OAuth2 provider
        - UserPoolId: Cognito User Pool ID
        - ClientId: Cognito Client ID
        - DiscoveryUrl: OIDC discovery URL
        - Region: AWS region
    """
    logger.info(f"Received {event['RequestType']} request")
    logger.info(f"Event: {json.dumps(event)}")

    try:
        props = event["ResourceProperties"]
        provider_name = props["ProviderName"]
        user_pool_id = props["UserPoolId"]
        client_id = props["ClientId"]
        discovery_url = props["DiscoveryUrl"]
        region = props["Region"]

        agentcore = boto3.client("bedrock-agentcore-control", region_name=region)
        cognito = boto3.client("cognito-idp", region_name=region)

        # Handle Delete
        if event["RequestType"] == "Delete":
            handle_delete(agentcore, provider_name)
            return send_cfn_response(event, "SUCCESS", physical_resource_id=provider_name)

        # Get client secret from Cognito
        client_secret = get_client_secret(cognito, user_pool_id, client_id)

        # Delete existing provider if present (for idempotency)
        delete_existing_provider(agentcore, provider_name)

        # Create new provider
        provider_arn = create_oauth2_provider(
            agentcore,
            provider_name,
            discovery_url,
            client_id,
            client_secret
        )
        logger.info(f"Created OAuth provider: {provider_arn}")

        return send_cfn_response(
            event,
            "SUCCESS",
            data={"ProviderArn": provider_arn},
            physical_resource_id=provider_name
        )

    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return send_cfn_response(event, "FAILED", reason=str(e))
