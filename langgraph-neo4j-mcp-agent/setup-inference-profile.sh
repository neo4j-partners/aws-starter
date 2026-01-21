#!/bin/bash
# setup-inference-profile.sh
# Creates an application inference profile for use in labs
#
# Usage:
#   ./setup-inference-profile.sh                    # Uses defaults (Claude 3.5 Haiku)
#   ./setup-inference-profile.sh sonnet             # Creates profile for Claude Sonnet 4
#   ./setup-inference-profile.sh --delete           # Deletes the profile
#   ./setup-inference-profile.sh --list             # Lists existing profiles

set -e

REGION="${AWS_REGION:-us-west-2}"
PROFILE_PREFIX="langgraph-lab"

# Model options
declare -A MODELS=(
    ["haiku"]="arn:aws:bedrock:${REGION}::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0"
    ["sonnet"]="arn:aws:bedrock:${REGION}::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0"
    ["sonnet-3.5"]="arn:aws:bedrock:${REGION}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
    ["sonnet-4.5"]="arn:aws:bedrock:${REGION}::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0"
)

show_help() {
    echo "Usage: $0 [model|--list|--delete|--help]"
    echo ""
    echo "Creates an application inference profile for LangGraph labs."
    echo ""
    echo "Models:"
    echo "  haiku       Claude 3.5 Haiku (default, fastest, cheapest)"
    echo "  sonnet      Claude Sonnet 4"
    echo "  sonnet-3.5  Claude 3.5 Sonnet v2"
    echo "  sonnet-4.5  Claude Sonnet 4.5"
    echo ""
    echo "Options:"
    echo "  --list      List existing inference profiles"
    echo "  --delete    Delete the lab inference profile"
    echo "  --help      Show this help"
    echo ""
    echo "Environment:"
    echo "  AWS_REGION  Region (default: us-west-2)"
    echo ""
    echo "Example:"
    echo "  ./setup-inference-profile.sh haiku"
    echo "  AWS_REGION=us-east-1 ./setup-inference-profile.sh sonnet"
}

list_profiles() {
    echo "Listing application inference profiles in ${REGION}..."
    aws bedrock list-inference-profiles \
        --region "${REGION}" \
        --type-equals APPLICATION \
        --query 'inferenceProfileSummaries[].{Name:inferenceProfileName,ARN:inferenceProfileArn,Status:status,Model:models[0].modelArn}' \
        --output table
}

delete_profile() {
    local profile_name="${PROFILE_PREFIX}"
    echo "Looking for profile: ${profile_name}..."

    # Get the ARN
    local arn=$(aws bedrock list-inference-profiles \
        --region "${REGION}" \
        --type-equals APPLICATION \
        --query "inferenceProfileSummaries[?inferenceProfileName=='${profile_name}'].inferenceProfileArn" \
        --output text)

    if [ -z "$arn" ] || [ "$arn" == "None" ]; then
        echo "Profile '${profile_name}' not found."
        exit 0
    fi

    echo "Deleting profile: ${arn}"
    aws bedrock delete-inference-profile \
        --region "${REGION}" \
        --inference-profile-identifier "${arn}"

    echo "Deleted successfully."
}

create_profile() {
    local model_key="${1:-haiku}"
    local model_arn="${MODELS[$model_key]}"

    if [ -z "$model_arn" ]; then
        echo "Error: Unknown model '${model_key}'"
        echo "Available models: ${!MODELS[*]}"
        exit 1
    fi

    local profile_name="${PROFILE_PREFIX}"

    echo "=============================================="
    echo "Creating Application Inference Profile"
    echo "=============================================="
    echo "Region:  ${REGION}"
    echo "Name:    ${profile_name}"
    echo "Model:   ${model_key}"
    echo "Source:  ${model_arn}"
    echo "=============================================="

    # Check if profile already exists
    local existing=$(aws bedrock list-inference-profiles \
        --region "${REGION}" \
        --type-equals APPLICATION \
        --query "inferenceProfileSummaries[?inferenceProfileName=='${profile_name}'].inferenceProfileArn" \
        --output text 2>/dev/null || echo "")

    if [ -n "$existing" ] && [ "$existing" != "None" ]; then
        echo ""
        echo "Profile already exists: ${existing}"
        echo ""
        echo "To recreate, first delete with: $0 --delete"
        echo ""
        output_config "$existing"
        exit 0
    fi

    # Create the profile
    local result=$(aws bedrock create-inference-profile \
        --region "${REGION}" \
        --inference-profile-name "${profile_name}" \
        --model-source "copyFrom=${model_arn}" \
        --description "LangGraph lab inference profile for ${model_key}" \
        --tags key=Purpose,value=LangGraphLab key=Model,value="${model_key}" \
        --output json)

    local profile_arn=$(echo "$result" | grep -o '"inferenceProfileArn": "[^"]*"' | cut -d'"' -f4)
    local status=$(echo "$result" | grep -o '"status": "[^"]*"' | cut -d'"' -f4)

    echo ""
    echo "Created successfully!"
    echo "Status: ${status}"
    echo ""
    output_config "$profile_arn"
}

output_config() {
    local arn="$1"
    echo "=============================================="
    echo "CONFIGURATION FOR YOUR NOTEBOOK"
    echo "=============================================="
    echo ""
    echo "# Copy this to your notebook cell:"
    echo ""
    echo "MODEL_ID = \"${arn}\""
    echo ""
    echo "llm = ChatBedrockConverse("
    echo "    model=MODEL_ID,"
    echo "    provider=\"anthropic\","
    echo "    region_name=\"${REGION}\","
    echo "    temperature=0,"
    echo ")"
    echo ""
    echo "=============================================="

    # Also save to a config file
    cat > .inference-profile.env << EOF
# Generated by setup-inference-profile.sh
# Source this file or copy values to your notebook

export INFERENCE_PROFILE_ARN="${arn}"
export AWS_REGION="${REGION}"
EOF
    echo "Config saved to: .inference-profile.env"
}

# Main
case "${1:-}" in
    --help|-h)
        show_help
        ;;
    --list|-l)
        list_profiles
        ;;
    --delete|-d)
        delete_profile
        ;;
    *)
        create_profile "${1:-haiku}"
        ;;
esac
