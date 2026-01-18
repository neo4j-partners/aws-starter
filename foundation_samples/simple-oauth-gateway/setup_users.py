#!/usr/bin/env python3
"""
Create Test Users for RBAC Demo

This script creates test users in the Cognito User Pool with different
group memberships to demonstrate role-based access control:

- admin@example.com: Member of 'admin' and 'users' groups (full access)
- user@example.com: Member of 'users' group only (no admin access)

Usage:
    python setup_users.py                    # Use defaults
    python setup_users.py --stack MyStack    # Different stack name
    python setup_users.py --region us-east-1 # Override region

The script is idempotent - running it multiple times is safe.
"""

import argparse
import os
import sys

import boto3
from botocore.exceptions import ClientError

DEFAULT_STACK_NAME = "SimpleOAuthDemo"

# Test user definitions
TEST_USERS = [
    {
        "username": "admin@example.com",
        "password": "AdminPass123!",
        "groups": ["admin", "users"],
        "description": "Admin user with full access"
    },
    {
        "username": "user@example.com",
        "password": "UserPass123!",
        "groups": ["users"],
        "description": "Regular user (no admin access)"
    }
]


def get_default_region() -> str:
    """Get the default AWS region."""
    if os.environ.get("AWS_REGION"):
        return os.environ["AWS_REGION"]
    if os.environ.get("AWS_DEFAULT_REGION"):
        return os.environ["AWS_DEFAULT_REGION"]

    session = boto3.Session()
    if session.region_name:
        return session.region_name

    return "us-west-2"


def get_user_pool_id(stack_name: str, region: str) -> str:
    """Get User Pool ID from CloudFormation stack outputs."""
    cf = boto3.client("cloudformation", region_name=region)
    response = cf.describe_stacks(StackName=stack_name)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in response["Stacks"][0]["Outputs"]}
    return outputs.get("CognitoUserPoolId")


def create_user(cognito, user_pool_id: str, username: str, password: str) -> bool:
    """
    Create a Cognito user with a permanent password.

    Args:
        cognito: Cognito IDP client
        user_pool_id: User Pool ID
        username: User email/username
        password: User password

    Returns:
        True if user was created or already exists
    """
    try:
        # Create user
        cognito.admin_create_user(
            UserPoolId=user_pool_id,
            Username=username,
            UserAttributes=[
                {"Name": "email", "Value": username},
                {"Name": "email_verified", "Value": "true"}
            ],
            MessageAction="SUPPRESS"  # Don't send welcome email
        )
        print(f"    Created user: {username}")
    except cognito.exceptions.UsernameExistsException:
        print(f"    User already exists: {username}")
    except ClientError as e:
        print(f"    Error creating user {username}: {e}")
        return False

    # Set permanent password (skip forced password change)
    try:
        cognito.admin_set_user_password(
            UserPoolId=user_pool_id,
            Username=username,
            Password=password,
            Permanent=True
        )
        print(f"    Set password for: {username}")
    except ClientError as e:
        print(f"    Error setting password for {username}: {e}")
        return False

    return True


def add_user_to_group(cognito, user_pool_id: str, username: str, group_name: str) -> bool:
    """Add a user to a Cognito group."""
    try:
        cognito.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName=group_name
        )
        print(f"    Added {username} to group: {group_name}")
        return True
    except cognito.exceptions.ResourceNotFoundException:
        print(f"    Group not found: {group_name}")
        print(f"    Make sure the stack is deployed with the latest version.")
        return False
    except ClientError as e:
        print(f"    Error adding {username} to {group_name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Create test users for RBAC demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Users Created:
  admin@example.com / AdminPass123!  -> groups: admin, users
  user@example.com  / UserPass123!   -> groups: users

After running this script, test with:
  python client/demo.py --mode user --username admin@example.com
  python client/demo.py --mode user --username user@example.com
        """
    )

    parser.add_argument(
        "--stack",
        default=DEFAULT_STACK_NAME,
        help=f"CloudFormation stack name (default: {DEFAULT_STACK_NAME})"
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region (default: from AWS config)"
    )

    args = parser.parse_args()
    region = args.region or get_default_region()

    print(f"Setting up test users for stack: {args.stack} (region: {region})")
    print("=" * 60)

    # Get User Pool ID
    try:
        user_pool_id = get_user_pool_id(args.stack, region)
        if not user_pool_id:
            print(f"\nError: Could not find CognitoUserPoolId in stack outputs")
            sys.exit(1)
        print(f"User Pool ID: {user_pool_id}")
    except Exception as e:
        print(f"\nError: Could not get stack outputs: {e}")
        print(f"Make sure '{args.stack}' is deployed. Run: ./deploy.sh")
        sys.exit(1)

    cognito = boto3.client("cognito-idp", region_name=region)

    # Create each test user
    success = True
    for user_config in TEST_USERS:
        username = user_config["username"]
        password = user_config["password"]
        groups = user_config["groups"]
        description = user_config["description"]

        print(f"\n{description}:")
        print(f"  Username: {username}")
        print(f"  Password: {password}")
        print(f"  Groups: {', '.join(groups)}")

        # Create user
        if not create_user(cognito, user_pool_id, username, password):
            success = False
            continue

        # Add to groups
        for group in groups:
            if not add_user_to_group(cognito, user_pool_id, username, group):
                success = False

    print("\n" + "=" * 60)
    if success:
        print("Test users created successfully!")
        print("\nTest with:")
        print("  # Admin user (full access)")
        print("  python client/demo.py --mode user --username admin@example.com")
        print("")
        print("  # Regular user (admin tools blocked)")
        print("  python client/demo.py --mode user --username user@example.com")
    else:
        print("Some users could not be created. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
