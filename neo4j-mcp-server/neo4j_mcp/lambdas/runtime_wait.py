"""
Runtime Wait Lambda Handler

This Lambda waits for an AgentCore Runtime to reach READY state before
allowing dependent resources (like GatewayTarget) to be created.

It is used as a CloudFormation Custom Resource to ensure proper
resource ordering and Runtime availability.
"""

import json
import logging
import time
from typing import Any

import boto3
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuration
MAX_WAIT_SECONDS = 300
POLL_INTERVAL_SECONDS = 10
READY_STATES = {"READY", "ACTIVE"}
TERMINAL_STATES = {"FAILED", "DELETING", "DELETED"}


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
        "PhysicalResourceId": physical_resource_id or event.get("PhysicalResourceId", "runtime-wait"),
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


def extract_runtime_id(runtime_arn: str) -> str:
    """
    Extract runtime ID from ARN.

    Args:
        runtime_arn: Full ARN of the runtime

    Returns:
        Runtime ID extracted from the ARN

    Example:
        arn:aws:bedrock-agentcore:us-west-2:123456789:runtime/my-runtime-id
        -> my-runtime-id
    """
    return runtime_arn.split("/")[-1]


def get_runtime_status(client: Any, runtime_id: str) -> str:
    """
    Get the current status of a Runtime.

    Args:
        client: Boto3 AgentCore client
        runtime_id: Runtime ID to check

    Returns:
        Current status string
    """
    response = client.get_agent_runtime(agentRuntimeId=runtime_id)
    return response.get("status", "UNKNOWN")


def wait_for_runtime_ready(
    client: Any,
    runtime_id: str,
    max_wait_seconds: int = MAX_WAIT_SECONDS
) -> tuple[bool, str]:
    """
    Poll the Runtime until it reaches READY state.

    Args:
        client: Boto3 AgentCore client
        runtime_id: Runtime ID to wait for
        max_wait_seconds: Maximum time to wait

    Returns:
        Tuple of (success: bool, message: str)
    """
    elapsed = 0

    while elapsed < max_wait_seconds:
        try:
            status = get_runtime_status(client, runtime_id)
            logger.info(f"Runtime status after {elapsed}s: {status}")

            if status in READY_STATES:
                return True, f"Runtime ready with status: {status}"

            if status in TERMINAL_STATES:
                return False, f"Runtime in terminal state: {status}"

        except Exception as e:
            logger.warning(f"Error getting runtime status: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

    return False, f"Timeout after {max_wait_seconds}s waiting for Runtime"


def handler(event: dict, context: Any) -> dict:
    """
    CloudFormation Custom Resource handler for Runtime health check.

    Required ResourceProperties:
        - RuntimeArn: ARN of the Runtime to check
        - Region: AWS region

    Optional ResourceProperties:
        - MaxWaitSeconds: Maximum wait time (default: 300)
    """
    logger.info(f"Received {event['RequestType']} request")
    logger.info(f"Event: {json.dumps(event)}")

    try:
        # Handle Delete - nothing to clean up
        if event["RequestType"] == "Delete":
            return send_cfn_response(event, "SUCCESS")

        props = event["ResourceProperties"]
        runtime_arn = props["RuntimeArn"]
        region = props["Region"]
        max_wait = int(props.get("MaxWaitSeconds", MAX_WAIT_SECONDS))

        runtime_id = extract_runtime_id(runtime_arn)
        logger.info(f"Waiting for runtime {runtime_id} to be ready...")

        client = boto3.client("bedrock-agentcore-control", region_name=region)

        success, message = wait_for_runtime_ready(client, runtime_id, max_wait)

        if success:
            return send_cfn_response(
                event,
                "SUCCESS",
                data={"RuntimeArn": runtime_arn, "Status": "READY"}
            )
        else:
            return send_cfn_response(event, "FAILED", reason=message)

    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return send_cfn_response(event, "FAILED", reason=str(e))
