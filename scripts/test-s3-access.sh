#!/bin/bash

# Test AWS S3 Access Script
# Creates a bucket, uploads a sample file, and lists contents

set -e

REGION="${AWS_REGION:-us-east-1}"

# Handle --cleanup flag
if [ "$1" = "--cleanup" ]; then
    if [ -z "$2" ]; then
        echo "Usage: $0 --cleanup <bucket-name>"
        echo "Example: $0 --cleanup test-bucket-1234567890-12345"
        exit 1
    fi
    BUCKET_NAME="$2"
    echo "=== Cleaning up S3 bucket ==="
    echo "Bucket: $BUCKET_NAME"
    echo ""
    echo "1. Removing all objects from bucket..."
    aws s3 rm "s3://$BUCKET_NAME" --recursive
    echo "2. Deleting bucket..."
    aws s3api delete-bucket --bucket "$BUCKET_NAME" --region "$REGION"
    echo ""
    echo "=== Cleanup Complete ==="
    exit 0
fi

# Handle --cleanup-all flag
if [ "$1" = "--cleanup-all" ]; then
    echo "=== Cleaning up all test-bucket-* buckets ==="
    echo ""
    BUCKETS=$(aws s3api list-buckets --query "Buckets[?starts_with(Name, 'test-bucket-')].Name" --output text)

    if [ -z "$BUCKETS" ]; then
        echo "No test-bucket-* buckets found."
        exit 0
    fi

    for BUCKET_NAME in $BUCKETS; do
        echo "Cleaning up: $BUCKET_NAME"
        echo "  Removing all objects..."
        aws s3 rm "s3://$BUCKET_NAME" --recursive 2>/dev/null || true
        echo "  Deleting bucket..."
        aws s3api delete-bucket --bucket "$BUCKET_NAME" 2>/dev/null || echo "  Warning: Could not delete $BUCKET_NAME"
        echo ""
    done

    echo "=== Cleanup Complete ==="
    exit 0
fi

# Generate a unique bucket name (S3 bucket names must be globally unique)
BUCKET_NAME="test-bucket-$(date +%s)-$RANDOM"
SAMPLE_FILE="sample-$(date +%Y%m%d-%H%M%S).md"

echo "=== AWS S3 Access Test ==="
echo "Bucket: $BUCKET_NAME"
echo "Region: $REGION"
echo ""

# Create the S3 bucket
echo "1. Creating S3 bucket..."
if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION"
else
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION" \
        --create-bucket-configuration LocationConstraint="$REGION"
fi
echo "   Bucket created successfully!"

# Create a random sample markdown file
echo "2. Creating sample markdown file..."
cat > "$SAMPLE_FILE" << EOF
# Sample Test File

Created: $(date)
Bucket: $BUCKET_NAME

## Random Content

This is a test file to verify AWS S3 access.

- Random number: $RANDOM
- Timestamp: $(date +%s)
- User: $(whoami)

## Purpose

This file was created to test:
1. S3 bucket creation
2. File upload capability
3. Bucket listing permissions
EOF
echo "   Created $SAMPLE_FILE"

# Upload the file to S3
echo "3. Uploading file to S3..."
aws s3 cp "$SAMPLE_FILE" "s3://$BUCKET_NAME/$SAMPLE_FILE"
echo "   File uploaded successfully!"

# List bucket contents
echo "4. Listing bucket contents..."
aws s3 ls "s3://$BUCKET_NAME/"

echo ""
echo "=== Test Complete ==="
echo "Bucket: $BUCKET_NAME"
echo "To clean up, run:"
echo "  $0 --cleanup $BUCKET_NAME"

# Clean up local file
rm -f "$SAMPLE_FILE"
