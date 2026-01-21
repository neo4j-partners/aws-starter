#!/bin/bash
# setup-inference-profile.sh
# Creates an application inference profile for use in labs
#
# For SageMaker Unified Studio, set these environment variables:
#   DATAZONE_PROJECT_ID - Your DataZone project ID
#   DATAZONE_DOMAIN_ID  - Your DataZone domain ID (dzd-...)
#
# Usage:
#   ./setup-inference-profile.sh                    # Uses defaults (Claude 3.5 Sonnet)
#   ./setup-inference-profile.sh haiku              # Creates profile for Claude 3.5 Haiku
#   ./setup-inference-profile.sh --delete           # Deletes the profile
#   ./setup-inference-profile.sh --list             # Lists existing profiles
#   ./setup-inference-profile.sh --detect           # Auto-detect DataZone IDs from Bedrock IDE export

set -e

REGION="${AWS_REGION:-us-west-2}"
PROFILE_PREFIX="langgraph-lab"

# DataZone tags (set these for SageMaker Unified Studio)
DATAZONE_PROJECT_ID="${DATAZONE_PROJECT_ID:-}"
DATAZONE_DOMAIN_ID="${DATAZONE_DOMAIN_ID:-}"

get_model_arn() {
    local model_key="$1"
    local account_id=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)

    # Use cross-region inference profiles (like Bedrock IDE does)
    # This creates multi-region capable application profiles
    case "$model_key" in
        haiku)
            echo "arn:aws:bedrock:${REGION}:${account_id}:inference-profile/us.anthropic.claude-3-5-haiku-20241022-v1:0"
            ;;
        sonnet|sonnet35)
            echo "arn:aws:bedrock:${REGION}:${account_id}:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0"
            ;;
        sonnet4)
            echo "arn:aws:bedrock:${REGION}:${account_id}:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0"
            ;;
        sonnet45)
            echo "arn:aws:bedrock:${REGION}:${account_id}:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
            ;;
        *)
            echo ""
            ;;
    esac
}

show_help() {
    echo "Usage: $0 [model|--list|--delete|--help]"
    echo ""
    echo "Creates an application inference profile for LangGraph labs."
    echo "Automatically detects DataZone IDs from Bedrock IDE exports."
    echo ""
    echo "Models:"
    echo "  sonnet      Claude 3.5 Sonnet v2 (default, recommended)"
    echo "  haiku       Claude 3.5 Haiku (faster, cheaper)"
    echo "  sonnet4     Claude Sonnet 4"
    echo "  sonnet45    Claude Sonnet 4.5"
    echo ""
    echo "Options:"
    echo "  --list      List existing inference profiles"
    echo "  --delete    Delete the lab inference profile"
    echo "  --help      Show this help"
    echo ""
    echo "Example:"
    echo "  $0 sonnet      # Create profile, copy ARN to notebook"
    echo "  $0 --list      # See existing profiles"
    echo "  $0 --delete    # Remove profile"
}

detect_datazone_ids() {
    echo "# Auto-detecting DataZone IDs from Bedrock IDE exports..." >&2

    local project_id=""
    local domain_id=""

    # Look for Bedrock IDE export folders
    for dir in ../amazon-bedrock-ide-app-export-* ./amazon-bedrock-ide-app-export-*; do
        if [ -d "$dir" ]; then
            local stack_file=$(ls "$dir"/amazon-bedrock-ide-app-stack-*.json 2>/dev/null | head -1)
            if [ -f "$stack_file" ]; then
                # Extract project ID from bedrockServiceRoleArn (more reliable than exportProjectId)
                # Format: AmazonBedrockServiceRole-{project_id}-{random}
                project_id=$(grep -o '"bedrockServiceRoleArn"[^,]*' "$stack_file" 2>/dev/null | \
                    grep -o 'AmazonBedrockServiceRole-[^-]*' | \
                    sed 's/AmazonBedrockServiceRole-//' | head -1)
                domain_id=$(grep -o 'dzd-[a-z0-9]*' "$stack_file" 2>/dev/null | head -1)
                if [ -n "$project_id" ] && [ -n "$domain_id" ]; then
                    echo "# Found in: $stack_file" >&2
                    break
                fi
            fi
        fi
    done

    if [ -n "$project_id" ] && [ -n "$domain_id" ]; then
        echo "# DataZone Project ID: $project_id" >&2
        echo "# DataZone Domain ID:  $domain_id" >&2
        echo ""
        echo "export DATAZONE_PROJECT_ID=\"$project_id\""
        echo "export DATAZONE_DOMAIN_ID=\"$domain_id\""
        echo ""
        echo "# Run: eval \$($0 --detect)" >&2
    else
        echo "# Could not auto-detect DataZone IDs." >&2
        echo "# Make sure you have a Bedrock IDE export folder nearby." >&2
        echo "# Or set manually:" >&2
        echo "#   export DATAZONE_PROJECT_ID=your_project_id" >&2
        echo "#   export DATAZONE_DOMAIN_ID=dzd-your_domain_id" >&2
        exit 1
    fi
}

list_profiles() {
    echo "Listing application inference profiles in ${REGION}..."
    aws bedrock list-inference-profiles \
        --region "${REGION}" \
        --type-equals APPLICATION \
        --query 'inferenceProfileSummaries[].{Name:inferenceProfileName,ARN:inferenceProfileArn,Status:status}' \
        --output table
}

delete_profile() {
    local profile_name="${PROFILE_PREFIX}"
    echo "Looking for profile: ${profile_name}..."

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
    local model_key="${1:-sonnet}"
    local model_arn=$(get_model_arn "$model_key")

    if [ -z "$model_arn" ]; then
        echo "Error: Unknown model '${model_key}'"
        echo "Available models: haiku, sonnet, sonnet4, sonnet45"
        exit 1
    fi

    # Use Bedrock IDE naming pattern if DataZone IDs are available
    local profile_name
    local description
    if [ -n "$DATAZONE_PROJECT_ID" ] && [ -n "$DATAZONE_DOMAIN_ID" ]; then
        # Bedrock IDE pattern: "{domain_id} {project_id}"
        profile_name="${DATAZONE_DOMAIN_ID} ${DATAZONE_PROJECT_ID} lab"
        description="Lab profile for domain ${DATAZONE_DOMAIN_ID} to provide access to Amazon Bedrock model in project ${DATAZONE_PROJECT_ID}"
    else
        profile_name="${PROFILE_PREFIX}"
        description="LangGraph lab inference profile for ${model_key}"
    fi

    echo "=============================================="
    echo "Creating Application Inference Profile"
    echo "=============================================="
    echo "Region:  ${REGION}"
    echo "Name:    ${profile_name}"
    echo "Model:   ${model_key}"
    echo "Source:  ${model_arn}"

    if [ -n "$DATAZONE_PROJECT_ID" ]; then
        echo ""
        echo "DataZone Tags (for SageMaker Unified Studio):"
        echo "  Project: ${DATAZONE_PROJECT_ID}"
        echo "  Domain:  ${DATAZONE_DOMAIN_ID}"
        echo "  AmazonBedrockManaged: true"
    fi
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
        echo "To recreate with new settings, first delete:"
        echo "  $0 --delete"
        echo ""
        output_config "$existing"
        exit 0
    fi

    # Build tags - CRITICAL: Include AmazonBedrockManaged=true for SageMaker Unified Studio
    local tags="key=Purpose,value=LangGraphLab key=Model,value=${model_key}"

    if [ -n "$DATAZONE_PROJECT_ID" ]; then
        tags="$tags key=AmazonDataZoneProject,value=${DATAZONE_PROJECT_ID}"
    fi

    if [ -n "$DATAZONE_DOMAIN_ID" ]; then
        tags="$tags key=AmazonDataZoneDomain,value=${DATAZONE_DOMAIN_ID}"
    fi

    # CRITICAL: This tag is required for SageMaker Unified Studio permissions boundary
    if [ -n "$DATAZONE_PROJECT_ID" ] && [ -n "$DATAZONE_DOMAIN_ID" ]; then
        tags="$tags key=AmazonBedrockManaged,value=true"
    fi

    # Create the profile
    local result=$(aws bedrock create-inference-profile \
        --region "${REGION}" \
        --inference-profile-name "${profile_name}" \
        --model-source "copyFrom=${model_arn}" \
        --description "${description}" \
        --tags $tags \
        --output json)

    local profile_arn=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('inferenceProfileArn',''))")
    local status=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")

    echo ""
    echo "Created successfully!"
    echo "Status: ${status}"
    output_config "$profile_arn"
}

output_config() {
    local arn="$1"
    echo ""
    echo "=============================================="
    echo "  COPY THIS TO YOUR NOTEBOOK"
    echo "=============================================="
    echo ""
    echo "INFERENCE_PROFILE_ARN = \"${arn}\""
    echo ""
    echo "=============================================="
    echo ""

    # Save to config file
    cat > .inference-profile.env << EOF
# Generated by setup-inference-profile.sh
INFERENCE_PROFILE_ARN="${arn}"
AWS_REGION="${REGION}"
EOF
    echo "Config saved to: .inference-profile.env"
}

# Auto-detect DataZone IDs if not set
auto_detect_datazone() {
    if [ -z "$DATAZONE_PROJECT_ID" ] || [ -z "$DATAZONE_DOMAIN_ID" ]; then
        # Look for Bedrock IDE export folders
        for dir in ../amazon-bedrock-ide-app-export-* ./amazon-bedrock-ide-app-export-*; do
            if [ -d "$dir" ]; then
                local stack_file=$(ls "$dir"/amazon-bedrock-ide-app-stack-*.json 2>/dev/null | head -1)
                if [ -f "$stack_file" ]; then
                    # Extract project ID from bedrockServiceRoleArn (more reliable)
                    DATAZONE_PROJECT_ID=$(grep -o '"bedrockServiceRoleArn"[^,]*' "$stack_file" 2>/dev/null | \
                        grep -o 'AmazonBedrockServiceRole-[^-]*' | \
                        sed 's/AmazonBedrockServiceRole-//' | head -1)
                    DATAZONE_DOMAIN_ID=$(grep -o 'dzd-[a-z0-9]*' "$stack_file" 2>/dev/null | head -1)
                    if [ -n "$DATAZONE_PROJECT_ID" ] && [ -n "$DATAZONE_DOMAIN_ID" ]; then
                        echo "Auto-detected DataZone IDs from: $stack_file"
                        echo "  Project: $DATAZONE_PROJECT_ID"
                        echo "  Domain:  $DATAZONE_DOMAIN_ID"
                        break
                    fi
                fi
            fi
        done
    fi
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
    --detect)
        detect_datazone_ids
        ;;
    *)
        auto_detect_datazone
        create_profile "${1:-sonnet}"
        ;;
esac
