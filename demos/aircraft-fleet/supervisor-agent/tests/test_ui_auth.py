"""Tests for the hosted UI's Cognito login, in ``ui/auth.py`` and ``ui/server.py``."""

import base64
import hashlib
import importlib.util
import json
import sys
import time
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import jwt
import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

UI_DIR = Path(__file__).resolve().parents[2] / "ui"
POOL_ID = "us-east-1_TestPool"
CLIENT_ID = "fleet-ui-client"
PARAMETER = "/fleet-ui/cognito-client-id"
DOMAIN = "https://fleet-test.auth.us-east-1.amazoncognito.com"
ISSUER = f"https://cognito-idp.us-east-1.amazonaws.com/{POOL_ID}"
SUB = "6f1c2e8a-0000-4000-8000-000000000001"
DONE = [{"type": "complete", "response": "Done."}]

POOL_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    """Stands in for PyJWKClient with the pool's one public key."""

    def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
        return SimpleNamespace(key=POOL_KEY.public_key())


class FakeSsm:
    """Returns one parameter value, or raises the error it was given."""

    def __init__(self, value: str = CLIENT_ID, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.names: list[str] = []

    def get_parameter(self, Name: str) -> dict[str, Any]:  # noqa: N803
        self.names.append(Name)
        if self.error is not None:
            raise self.error
        return {"Parameter": {"Name": Name, "Type": "String", "Value": self.value}}

    def close(self) -> None:
        pass


def id_token(key: rsa.RSAPrivateKey = POOL_KEY, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "sub": SUB,
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "token_use": "id",
        "iat": now,
        "exp": now + 3600,
        "nonce": "the-nonce",
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "pool-key"})


@pytest.fixture
def ui_server(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load ``ui/server.py``, which imports ``auth`` and ``evidence`` from its own folder."""
    monkeypatch.syspath_prepend(str(UI_DIR))
    spec = importlib.util.spec_from_file_location("fleet_ui_server", UI_DIR / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ui_auth(ui_server: ModuleType) -> ModuleType:
    """The ``auth`` module that ``ui/server.py`` imported."""
    return sys.modules["auth"]


@pytest.fixture
def ssm(ui_auth: ModuleType, monkeypatch: pytest.MonkeyPatch) -> FakeSsm:
    fake = FakeSsm()
    monkeypatch.setattr(ui_auth.boto3, "client", lambda service, region_name: fake)
    return fake


@pytest.fixture
def cognito_env(monkeypatch: pytest.MonkeyPatch, ssm: FakeSsm) -> FakeSsm:
    monkeypatch.setenv("FLEET_UI_AUTH", "cognito")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", POOL_ID)
    monkeypatch.setenv("COGNITO_CLIENT_ID_PARAMETER", PARAMETER)
    monkeypatch.setenv("COGNITO_DOMAIN", DOMAIN + "/")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    return ssm


@pytest.fixture
def turns(ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """Record each chat turn the UI relays, with the user it relays it for."""
    calls: list[tuple[Any, Any]] = []

    def fake_stream(turn: Any, user_id: str | None) -> Any:
        calls.append((turn, user_id))
        return nullcontext(iter(DONE))

    monkeypatch.setattr(ui_server, "supervisor_stream", fake_stream)
    return calls


@pytest.fixture
def client(ui_server: ModuleType, cognito_env: FakeSsm) -> Iterator[TestClient]:
    """A browser on the hosted UI, with the pool's keys served by ``FakeJwks``."""
    with TestClient(
        ui_server.app, base_url="https://fleet.example.test", follow_redirects=False
    ) as browser:
        browser.app.state.login.jwks_client = FakeJwks()
        yield browser


def start(ui_server: ModuleType) -> None:
    """Run the UI's startup and shutdown."""
    with TestClient(ui_server.app):
        pass


def ask(browser: TestClient) -> Any:
    return browser.post(
        "/api/chat", json={"prompt": "Find hydraulic issues", "session_id": str(uuid4())}
    )


def sign_in(browser: TestClient, token: str) -> None:
    browser.cookies.set("fleet_session", token, domain="fleet.example.test", path="/")


def start_login(browser: TestClient) -> dict[str, str]:
    response = browser.get("/auth/login")
    assert response.status_code == 303
    return {
        name: values[0]
        for name, values in parse_qs(urlsplit(response.headers["location"]).query).items()
    }


# The login mode


def test_an_unset_login_mode_serves_every_route_with_no_login(
    ui_server: ModuleType, turns: list[tuple[Any, Any]]
) -> None:
    with TestClient(ui_server.app, base_url="http://127.0.0.1:8081") as browser:
        assert browser.app.state.login is None
        assert browser.get("/").status_code == 200
        assert browser.get("/static/app.js").status_code == 200
        reply = ask(browser)
        assert browser.get("/auth/login").status_code == 404

    assert reply.status_code == 200
    assert [
        json.loads(line.removeprefix("data: ")) for line in reply.text.split("\n\n") if line
    ] == DONE
    assert [user_id for _turn, user_id in turns] == [None]


def test_an_unknown_login_mode_stops_the_ui_at_startup(
    ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLEET_UI_AUTH", "basic")

    with pytest.raises(ui_server.ConfigError, match="must be none or cognito, not 'basic'"):
        start(ui_server)


@pytest.mark.parametrize(
    "unset", ["COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID_PARAMETER", "COGNITO_DOMAIN", "AWS_REGION"]
)
def test_cognito_mode_with_a_missing_setting_stops_the_ui_at_startup(
    ui_server: ModuleType, cognito_env: FakeSsm, monkeypatch: pytest.MonkeyPatch, unset: str
) -> None:
    monkeypatch.delenv(unset)

    with pytest.raises(ui_server.ConfigError, match=f"cognito, but {unset} is not set"):
        start(ui_server)


def test_a_cognito_domain_that_is_not_https_stops_the_ui_at_startup(
    ui_server: ModuleType, cognito_env: FakeSsm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COGNITO_DOMAIN", "fleet-test.auth.us-east-1.amazoncognito.com")

    with pytest.raises(ui_server.ConfigError, match="managed login base URL"):
        start(ui_server)


def test_the_client_id_is_read_from_its_ssm_parameter_at_startup(
    ui_server: ModuleType, cognito_env: FakeSsm
) -> None:
    with TestClient(ui_server.app) as browser:
        settings = browser.app.state.login.settings

    assert cognito_env.names == [PARAMETER]
    assert settings.client_id == CLIENT_ID
    assert settings.domain == DOMAIN
    assert settings.issuer == ISSUER


@pytest.mark.parametrize(
    ("ssm_result", "message"),
    [
        (
            FakeSsm(error=ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")),
            "Could not read the Cognito client ID",
        ),
        (FakeSsm(value=" "), "holds no Cognito client ID"),
    ],
    ids=["missing-parameter", "empty-parameter"],
)
def test_an_unreadable_client_id_stops_the_ui_at_startup(
    ui_server: ModuleType,
    ui_auth: ModuleType,
    cognito_env: FakeSsm,
    monkeypatch: pytest.MonkeyPatch,
    ssm_result: FakeSsm,
    message: str,
) -> None:
    monkeypatch.setattr(ui_auth.boto3, "client", lambda service, region_name: ssm_result)

    with pytest.raises(ui_server.ConfigError, match=message):
        start(ui_server)


# Routes without a session


def test_the_page_with_no_session_redirects_to_the_login(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_a_question_with_no_session_gets_a_401_and_reaches_nothing(
    client: TestClient, turns: list[tuple[Any, Any]]
) -> None:
    response = ask(client)

    assert response.status_code == 401
    assert response.json() == {"error": "Sign in to use the fleet UI."}
    assert turns == []
    assert client.app.state.driver is None


def test_static_files_with_no_session_get_a_401(client: TestClient) -> None:
    assert client.get("/static/app.js").status_code == 401


def test_the_readiness_route_needs_no_session_and_returns_no_data(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.text == "ok"


# The login flow


def test_the_login_sends_the_browser_to_cognito_with_pkce(client: TestClient) -> None:
    response = client.get("/auth/login")
    location = urlsplit(response.headers["location"])
    query = {name: values[0] for name, values in parse_qs(location.query).items()}
    flow_cookie = response.headers["set-cookie"]
    state, nonce, verifier = client.cookies["fleet_login"].split(".")

    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{DOMAIN}/oauth2/authorize"
    assert query["response_type"] == "code"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == "https://fleet.example.test/auth/callback"
    assert query["scope"] == "openid"
    assert query["state"] == state
    assert query["nonce"] == nonce
    assert query["code_challenge_method"] == "S256"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert query["code_challenge"] == challenge.decode()
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/auth/callback", "Max-Age=600"):
        assert attribute in flow_cookie


def test_a_callback_with_a_matching_state_sets_the_session(
    client: TestClient, turns: list[tuple[Any, Any]]
) -> None:
    query = start_login(client)
    exchanged: list[tuple[str, str, str]] = []

    async def exchange_code(code: str, verifier: str, redirect_uri: str) -> str:
        exchanged.append((code, verifier, redirect_uri))
        return id_token(nonce=query["nonce"])

    client.app.state.login.exchange_code = exchange_code
    verifier = client.cookies["fleet_login"].split(".")[2]

    response = client.get("/auth/callback", params={"code": "the-code", "state": query["state"]})

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert exchanged == [("the-code", verifier, "https://fleet.example.test/auth/callback")]
    session_cookie = next(
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith("fleet_session=")
    )
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute in session_cookie
    assert client.cookies.get("fleet_login") is None
    assert client.get("/").status_code == 200
    assert ask(client).status_code == 200
    assert [user_id for _turn, user_id in turns] == [SUB]


@pytest.mark.parametrize(
    "cookie",
    [None, "wrong-state.nonce.verifier", "no-dots"],
    ids=["no-flow", "other-state", "bad-flow"],
)
def test_a_callback_without_a_matching_state_is_refused(
    client: TestClient, cookie: str | None
) -> None:
    async def exchange_code(*_args: str) -> str:
        raise AssertionError("the code must not be exchanged")

    client.app.state.login.exchange_code = exchange_code
    if cookie is not None:
        client.cookies.set(
            "fleet_login", cookie, domain="fleet.example.test", path="/auth/callback"
        )

    response = client.get("/auth/callback", params={"code": "the-code", "state": "the-state"})

    assert response.status_code == 401
    assert "fleet_session" not in response.headers.get("set-cookie", "")


def test_a_callback_whose_token_has_another_nonce_is_refused(client: TestClient) -> None:
    query = start_login(client)

    async def exchange_code(*_args: str) -> str:
        return id_token(nonce="a-replayed-nonce")

    client.app.state.login.exchange_code = exchange_code

    response = client.get("/auth/callback", params={"code": "the-code", "state": query["state"]})

    assert response.status_code == 401
    assert client.cookies.get("fleet_session") is None


def test_the_logout_clears_the_session_and_ends_the_cognito_session(client: TestClient) -> None:
    sign_in(client, id_token())

    response = client.get("/auth/logout")

    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{DOMAIN}/logout"
    assert parse_qs(location.query) == {
        "client_id": [CLIENT_ID],
        "logout_uri": ["https://fleet.example.test/"],
    }
    assert 'fleet_session=""' in response.headers["set-cookie"]
    assert client.cookies.get("fleet_session") is None
    assert client.get("/").status_code == 303


# Session tokens


@pytest.mark.parametrize(
    "token",
    [
        id_token(key=OTHER_KEY),
        id_token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OtherPool"),
        id_token(aud="another-client"),
        id_token(exp=int(time.time()) - 60),
        id_token(token_use="access"),
        id_token(sub=None),
        "not-a-jwt",
    ],
    ids=[
        "bad-signature",
        "other-issuer",
        "other-audience",
        "expired",
        "access-token",
        "no-sub",
        "garbage",
    ],
)
def test_a_session_token_that_fails_verification_is_refused(
    client: TestClient, turns: list[tuple[Any, Any]], token: str
) -> None:
    sign_in(client, token)

    assert client.get("/").status_code == 303
    assert ask(client).status_code == 401
    assert turns == []


def test_a_verified_session_relays_the_question_for_its_user(
    client: TestClient, turns: list[tuple[Any, Any]]
) -> None:
    sign_in(client, id_token(nonce=None))

    response = ask(client)

    assert response.status_code == 200
    assert [user_id for _turn, user_id in turns] == [SUB]


# The supervisor session


@pytest.fixture
def opened(
    ui_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[dict[str, Any], str]]:
    """Record the payload and session ID of each turn the local supervisor gets."""
    calls: list[tuple[dict[str, Any], str]] = []
    monkeypatch.setattr(
        ui_server,
        "stream_local",
        lambda payload, session_id, _url: calls.append((payload, session_id)),
    )
    return calls


def test_a_signed_in_user_sends_the_user_and_a_session_of_their_own(
    ui_server: ModuleType, opened: list[tuple[dict[str, Any], str]]
) -> None:
    browser_session = uuid4()
    turn = ui_server.ChatRequest(prompt="hi", session_id=browser_session)

    ui_server.supervisor_stream(turn, SUB)
    ui_server.supervisor_stream(turn, "another-user")
    ui_server.supervisor_stream(turn, SUB)

    (payload, mine), (_, theirs), (_, mine_again) = opened
    assert payload == {"prompt": "hi", "trace": True, "user_id": SUB}
    assert mine == hashlib.sha256(f"{SUB}\x00{browser_session}".encode()).hexdigest()
    assert len(mine) >= 33
    assert theirs != mine
    assert mine_again == mine


def test_a_local_run_sends_no_user_and_the_browser_session_unchanged(
    ui_server: ModuleType, opened: list[tuple[dict[str, Any], str]]
) -> None:
    browser_session = UUID("12345678-1234-4234-8234-123456789abc")

    ui_server.supervisor_stream(
        ui_server.ChatRequest(prompt="hi", session_id=browser_session), None
    )

    assert opened == [({"prompt": "hi", "trace": True}, "12345678-1234-4234-8234-123456789abc")]
