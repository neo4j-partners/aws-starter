"""Tests for the image entrypoint that reads the Neo4j password secret."""

import json
import sys
import types
from collections.abc import Awaitable, Callable

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

import secret_entrypoint as entrypoint

ARN = "arn:aws:secretsmanager:us-west-2:123456789012:secret:neo4j-mcp-server/neo4j-password-AbCdEf"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(entrypoint.SECRET_ARN_VAR, raising=False)
    monkeypatch.delenv(entrypoint.PASSWORD_VAR, raising=False)


class FakeClient:
    def __init__(self, response: dict[str, str]) -> None:
        self.response = response
        self.secret_ids: list[str] = []

    def get_secret_value(self, SecretId: str) -> dict[str, str]:
        self.secret_ids.append(SecretId)
        return self.response


def test_plain_string_is_the_password() -> None:
    assert entrypoint.password_from_secret("s3cret") == "s3cret"


def test_json_object_uses_the_password_key() -> None:
    secret = json.dumps({"username": "reader", "password": "s3cret"})
    assert entrypoint.password_from_secret(secret) == "s3cret"


@pytest.mark.parametrize("secret", ["12345", '"quoted"', "[1, 2]", "true"])
def test_json_that_is_not_an_object_is_a_plain_password(secret: str) -> None:
    assert entrypoint.password_from_secret(secret) == secret


@pytest.mark.parametrize(
    "secret", ["", "{}", '{"password": ""}', '{"password": 12345}', '{"user": "x"}']
)
def test_rejects_an_empty_or_malformed_secret(secret: str) -> None:
    with pytest.raises(entrypoint.SecretError):
        entrypoint.password_from_secret(secret)


def test_region_comes_from_the_arn() -> None:
    assert entrypoint.region_from_arn(ARN) == "us-west-2"


@pytest.mark.parametrize(
    "arn", ["", "not-an-arn", "arn:aws:s3:::bucket", "arn:aws:secretsmanager::1:secret:x"]
)
def test_rejects_a_bad_arn(arn: str) -> None:
    with pytest.raises(entrypoint.SecretError):
        entrypoint.region_from_arn(arn)


def test_fetch_reads_the_secret_in_the_arn_region(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient({"SecretString": "s3cret"})
    regions: list[str] = []

    def fake_client(service: str, region_name: str) -> FakeClient:
        assert service == "secretsmanager"
        regions.append(region_name)
        return client

    monkeypatch.setattr(entrypoint.boto3, "client", fake_client)

    assert entrypoint.fetch_secret_string(ARN) == "s3cret"
    assert regions == ["us-west-2"]
    assert client.secret_ids == [ARN]


def test_fetch_rejects_a_binary_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        entrypoint.boto3, "client", lambda service, region_name: FakeClient({"SecretBinary": "x"})
    )
    with pytest.raises(entrypoint.SecretError):
        entrypoint.fetch_secret_string(ARN)


def test_secret_arn_sets_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(entrypoint.SECRET_ARN_VAR, f" {ARN} ")
    monkeypatch.setenv(entrypoint.PASSWORD_VAR, "password")
    fetched: list[str] = []

    def fake_fetch(secret_arn: str) -> str:
        fetched.append(secret_arn)
        return "s3cret"

    monkeypatch.setattr(entrypoint, "fetch_secret_string", fake_fetch)

    assert entrypoint.load_password() is True
    assert fetched == [ARN]
    assert entrypoint.os.environ[entrypoint.PASSWORD_VAR] == "s3cret"


def test_without_an_arn_the_env_password_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(entrypoint.PASSWORD_VAR, "from-env")

    def fail_fetch(secret_arn: str) -> str:
        raise AssertionError("no secret should be read")

    monkeypatch.setattr(entrypoint, "fetch_secret_string", fail_fetch)

    assert entrypoint.load_password() is False
    assert entrypoint.os.environ[entrypoint.PASSWORD_VAR] == "from-env"


def test_main_exits_on_a_bad_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(entrypoint.SECRET_ARN_VAR, ARN)
    monkeypatch.setattr(entrypoint, "fetch_secret_string", lambda secret_arn: "{}")

    with pytest.raises(SystemExit) as exit_info:
        entrypoint.main()
    assert entrypoint.SECRET_ARN_VAR in str(exit_info.value.code)


@pytest.mark.parametrize("partition", ["aws-cn", "aws-us-gov"])
def test_region_comes_from_an_arn_in_any_partition(partition: str) -> None:
    arn = f"arn:{partition}:secretsmanager:cn-north-1:123456789012:secret:x-AbCdEf"
    assert entrypoint.region_from_arn(arn) == "cn-north-1"


class FailingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_secret_value(self, SecretId: str) -> dict[str, str]:
        raise self.error


ACCESS_DENIED = ClientError(
    {
        "Error": {
            "Code": "AccessDeniedException",
            "Message": f"User: arn:aws:sts::123456789012:assumed-role/role is not "
            f"authorized to perform secretsmanager:GetSecretValue on {ARN}",
        }
    },
    "GetSecretValue",
)


@pytest.mark.parametrize(
    ("error", "named"),
    [
        (ACCESS_DENIED, "AccessDeniedException"),
        (EndpointConnectionError(endpoint_url="https://example"), "EndpointConnectionError"),
    ],
)
def test_fetch_turns_an_aws_error_into_a_secret_error(
    monkeypatch: pytest.MonkeyPatch, error: Exception, named: str
) -> None:
    monkeypatch.setattr(
        entrypoint.boto3, "client", lambda service, region_name: FailingClient(error)
    )

    with pytest.raises(entrypoint.SecretError) as error_info:
        entrypoint.fetch_secret_string(ARN)

    message = str(error_info.value)
    assert named in message
    assert "assumed-role" not in message
    assert "123456789012" not in message
    assert error_info.value.__cause__ is None
    assert error_info.value.__suppress_context__ is True


def test_main_exits_cleanly_when_access_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(entrypoint.SECRET_ARN_VAR, ARN)
    monkeypatch.setattr(
        entrypoint.boto3, "client", lambda service, region_name: FailingClient(ACCESS_DENIED)
    )

    with pytest.raises(SystemExit) as exit_info:
        entrypoint.main()
    assert "AccessDeniedException" in str(exit_info.value.code)
    assert "assumed-role" not in str(exit_info.value.code)


Handler = Callable[[Request], Awaitable[Response]]


class FakeServer:
    """Stands in for FastMCP, whose custom_route appends a Starlette Route."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.routes: list[Route] = []

    def custom_route(
        self, path: str, methods: list[str], include_in_schema: bool = True
    ) -> Callable[[Handler], Handler]:
        def register(handler: Handler) -> Handler:
            self.routes.append(
                Route(path, handler, methods=methods, include_in_schema=include_in_schema)
            )
            return handler

        return register


def test_ping_route_answers_healthy() -> None:
    server = entrypoint.add_ping_route(FakeServer())

    with TestClient(Starlette(routes=server.routes)) as client:
        response = client.get("/ping")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    # No time_of_last_update: a timestamp that moves on every ping would keep
    # idle Runtime sessions alive until their maximum lifetime.
    assert response.json() == {"status": "Healthy"}


def test_ping_route_is_get_only() -> None:
    server = entrypoint.add_ping_route(FakeServer())

    with TestClient(Starlette(routes=server.routes)) as client:
        assert client.post("/ping").status_code == 405


def test_wrapped_factory_passes_arguments_and_adds_ping() -> None:
    create = entrypoint.with_ping_route(FakeServer)

    server = create("driver", "neo4j", read_only=True)

    assert server.args == ("driver", "neo4j")
    assert server.kwargs == {"read_only": True}
    assert [route.path for route in server.routes] == [entrypoint.PING_PATH]


def test_main_serves_ping_from_the_server_it_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[FakeServer] = []
    server_module = types.ModuleType("mcp_neo4j_cypher.server")
    server_module.create_mcp_server = FakeServer

    def fake_server_main() -> None:
        # Like mcp_neo4j_cypher.server.main, look the factory up at call time.
        built.append(server_module.create_mcp_server("driver"))

    package = types.ModuleType("mcp_neo4j_cypher")
    package.main = fake_server_main
    package.server = server_module
    monkeypatch.setitem(sys.modules, "mcp_neo4j_cypher", package)
    monkeypatch.setitem(sys.modules, "mcp_neo4j_cypher.server", server_module)

    entrypoint.main()

    assert len(built) == 1
    assert [route.path for route in built[0].routes] == [entrypoint.PING_PATH]
