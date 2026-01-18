"""CDK Stack for Sample One: AgentCore Runtime Quick Start.

This stack deploys a Strands Agent to Amazon Bedrock AgentCore Runtime using:
- Local Docker build (fast iteration)
- ECR for image storage
- AgentCore Runtime with the built container
"""
from aws_cdk import (
    Stack,
    aws_ecr_assets as ecr_assets,
    aws_bedrockagentcore as bedrockagentcore,
    CfnParameter,
    CfnOutput,
)
from constructs import Construct
from infra_utils.agentcore_role import AgentCoreRole


class SampleOneStack(Stack):
    """CDK Stack for deploying Sample One agent to AgentCore Runtime."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Parameters
        agent_name = CfnParameter(
            self,
            "AgentName",
            type="String",
            default="QuickStartAgent",
            description="Name for the agent runtime",
        )

        network_mode = CfnParameter(
            self,
            "NetworkMode",
            type="String",
            default="PUBLIC",
            description="Network mode for AgentCore resources",
            allowed_values=["PUBLIC", "PRIVATE"],
        )

        # Build Docker image locally and push to ECR
        # This is much faster than CodeBuild for local development
        agent_image = ecr_assets.DockerImageAsset(
            self,
            "AgentImage",
            directory="./agent-code",
            platform=ecr_assets.Platform.LINUX_ARM64,
        )

        # AgentCore execution role
        agent_role = AgentCoreRole(self, "AgentCoreRole")

        # AgentCore Runtime
        agent_runtime = bedrockagentcore.CfnRuntime(
            self,
            "AgentRuntime",
            agent_runtime_name=f"{self.stack_name.replace('-', '_')}_{agent_name.value_as_string}",
            agent_runtime_artifact=bedrockagentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=bedrockagentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=agent_image.image_uri
                )
            ),
            network_configuration=bedrockagentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode=network_mode.value_as_string
            ),
            protocol_configuration="HTTP",
            role_arn=agent_role.role_arn,
            description=f"Quick start agent runtime for {self.stack_name}",
            environment_variables={"AWS_DEFAULT_REGION": self.region},
        )

        # Stack Outputs
        CfnOutput(
            self,
            "AgentRuntimeId",
            description="ID of the created agent runtime",
            value=agent_runtime.attr_agent_runtime_id,
        )

        CfnOutput(
            self,
            "AgentRuntimeArn",
            description="ARN of the created agent runtime",
            value=agent_runtime.attr_agent_runtime_arn,
        )

        CfnOutput(
            self,
            "AgentRoleArn",
            description="ARN of the agent execution role",
            value=agent_role.role_arn,
        )

        CfnOutput(
            self,
            "ImageUri",
            description="URI of the Docker image",
            value=agent_image.image_uri,
        )
