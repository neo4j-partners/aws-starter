"""Cognito login for the hosted UI.

``FLEET_UI_AUTH`` picks the mode. ``none``, or unset, serves every route with
no login, as local runs always have. ``cognito`` requires a Cognito session on
every route except the login routes and ``/ready``.

The login is the authorization code flow with PKCE against Cognito managed
login. The app client is public, so there is no client secret. The session is
the verified ID token, held in an HttpOnly cookie. Refresh tokens are not
used, so an expired session logs in again.
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import boto3
import httpx
import jwt
from botocore.exceptions import BotoCoreError, ClientError
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from fleet_supervisor.core.config import ConfigError

logger = logging.getLogger(__name__)

SESSION_COOKIE = "fleet_session"
FLOW_COOKIE = "fleet_login"
FLOW_COOKIE_PATH = "/auth/callback"
FLOW_MAX_AGE_S = 600
# The routes that need no session. Every other path, including /static, does.
OPEN_PATHS = frozenset({"/auth/login", "/auth/callback", "/auth/logout", "/ready"})
REQUIRED_SETTINGS = (
    "COGNITO_USER_POOL_ID",
    "COGNITO_CLIENT_ID_PARAMETER",
    "COGNITO_DOMAIN",
    "AWS_REGION",
)
LOGIN_FAILED = "The login did not complete. Open /auth/login to try again."


@dataclass(frozen=True)
class CognitoSettings:
    user_pool_id: str
    client_id: str
    domain: str
    region: str

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"


class CognitoLogin:
    """Builds the login redirect, trades the code for an ID token, and verifies tokens."""

    def __init__(self, settings: CognitoSettings, jwks_client: Any = None) -> None:
        self.settings = settings
        # PyJWKClient fetches the pool's signing keys once and caches them.
        self.jwks_client = jwks_client or jwt.PyJWKClient(
            f"{settings.issuer}/.well-known/jwks.json", cache_keys=True, timeout=5
        )

    def verify(self, token: str, nonce: str | None = None) -> dict[str, Any]:
        """Return the claims of a valid ID token for this app client.

        The signature must match a key from the pool's JWKS, and the issuer,
        audience, and expiry must be right. Raises ``jwt.PyJWTError`` otherwise.
        """
        key = self.jwks_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self.settings.client_id,
            issuer=self.settings.issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "token_use"]},
        )
        if claims["token_use"] != "id":
            raise jwt.InvalidTokenError("The token is not an ID token.")
        if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise jwt.InvalidTokenError("The token's nonce does not match this login.")
        return claims

    def authorize_url(self, redirect_uri: str, state: str, nonce: str, verifier: str) -> str:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        query = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge.decode().rstrip("="),
            "code_challenge_method": "S256",
        }
        return f"{self.settings.domain}/oauth2/authorize?{urlencode(query)}"

    def logout_url(self, logout_uri: str) -> str:
        query = {"client_id": self.settings.client_id, "logout_uri": logout_uri}
        return f"{self.settings.domain}/logout?{urlencode(query)}"

    async def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> str:
        """Trade an authorization code for its ID token at the Cognito token endpoint."""
        form = {
            "grant_type": "authorization_code",
            "client_id": self.settings.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.settings.domain}/oauth2/token", data=form)
        response.raise_for_status()
        return response.json()["id_token"]


def auth_mode() -> str:
    """Return ``none`` or ``cognito`` from ``FLEET_UI_AUTH``. Unset means none."""
    mode = os.getenv("FLEET_UI_AUTH") or "none"
    if mode not in {"none", "cognito"}:
        raise ConfigError(f"FLEET_UI_AUTH must be none or cognito, not {mode!r}.")
    return mode


def read_client_id(parameter: str, region: str) -> str:
    """Read the app client ID from the SSM String parameter the stack writes."""
    try:
        with closing(boto3.client("ssm", region_name=region)) as ssm:
            value = ssm.get_parameter(Name=parameter)["Parameter"]["Value"].strip()
    except (BotoCoreError, ClientError) as error:
        raise ConfigError(
            f"Could not read the Cognito client ID from SSM parameter {parameter}: {error}"
        ) from error
    if not value:
        raise ConfigError(f"SSM parameter {parameter} holds no Cognito client ID.")
    return value


def load_login() -> CognitoLogin | None:
    """Return the Cognito login for ``FLEET_UI_AUTH=cognito``, or None for no login.

    Raises ``ConfigError`` for an unknown mode or a missing setting, so the UI
    stops at startup instead of serving without a login.
    """
    if auth_mode() == "none":
        return None
    if missing := [name for name in REQUIRED_SETTINGS if not os.getenv(name)]:
        verb = "is" if len(missing) == 1 else "are"
        raise ConfigError(f"FLEET_UI_AUTH is cognito, but {', '.join(missing)} {verb} not set.")
    domain = os.environ["COGNITO_DOMAIN"].rstrip("/")
    if not domain.startswith("https://"):
        raise ConfigError("COGNITO_DOMAIN must be the managed login base URL, https://...")
    region = os.environ["AWS_REGION"]
    settings = CognitoSettings(
        user_pool_id=os.environ["COGNITO_USER_POOL_ID"],
        client_id=read_client_id(os.environ["COGNITO_CLIENT_ID_PARAMETER"], region),
        domain=domain,
        region=region,
    )
    return CognitoLogin(settings)


def _origin(request: Request) -> str:
    """The app's own origin, from the request's host. The hosted UI is always HTTPS."""
    return f"https://{request.headers['host']}"


def _set_cookie(response: Response, name: str, value: str, max_age: int, path: str) -> None:
    response.set_cookie(
        name, value, max_age=max_age, path=path, httponly=True, secure=True, samesite="lax"
    )


def _delete_cookie(response: Response, name: str, path: str) -> None:
    response.delete_cookie(name, path=path, httponly=True, secure=True, samesite="lax")


def _login_failed() -> Response:
    response = PlainTextResponse(LOGIN_FAILED, status_code=401)
    _delete_cookie(response, FLOW_COOKIE, FLOW_COOKIE_PATH)
    return response


async def login(request: Request) -> Response:
    """Start a login: remember the state, nonce, and PKCE verifier, then go to Cognito."""
    cognito: CognitoLogin | None = request.app.state.login
    if cognito is None:
        return PlainTextResponse("Not Found", status_code=404)
    state, nonce, verifier = (secrets.token_urlsafe(n) for n in (32, 32, 64))
    redirect_uri = f"{_origin(request)}/auth/callback"
    response = RedirectResponse(
        cognito.authorize_url(redirect_uri, state, nonce, verifier), status_code=303
    )
    # token_urlsafe never makes a dot, so the three values split back cleanly.
    flow = f"{state}.{nonce}.{verifier}"
    _set_cookie(response, FLOW_COOKIE, flow, FLOW_MAX_AGE_S, FLOW_COOKIE_PATH)
    return response


async def callback(request: Request) -> Response:
    """Finish a login: check the state, trade the code, verify the ID token, set the session."""
    cognito: CognitoLogin | None = request.app.state.login
    if cognito is None:
        return PlainTextResponse("Not Found", status_code=404)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    flow = request.cookies.get(FLOW_COOKIE, "").split(".")
    if not code or not state or len(flow) != 3 or not hmac.compare_digest(state, flow[0]):
        logger.warning("Rejected a login callback with no matching state")
        return _login_failed()
    _, nonce, verifier = flow
    try:
        id_token = await cognito.exchange_code(code, verifier, f"{_origin(request)}/auth/callback")
        claims = await asyncio.to_thread(cognito.verify, id_token, nonce)
    except (httpx.HTTPError, KeyError, ValueError, jwt.PyJWTError) as error:
        logger.warning("The Cognito login failed: %s", error)
        return _login_failed()
    response = RedirectResponse("/", status_code=303)
    max_age = max(0, int(claims["exp"] - time.time()))
    _set_cookie(response, SESSION_COOKIE, id_token, max_age, "/")
    _delete_cookie(response, FLOW_COOKIE, FLOW_COOKIE_PATH)
    return response


async def logout(request: Request) -> Response:
    """Clear the session, then end the Cognito session and come back to the app."""
    cognito: CognitoLogin | None = request.app.state.login
    if cognito is None:
        return PlainTextResponse("Not Found", status_code=404)
    response = RedirectResponse(cognito.logout_url(f"{_origin(request)}/"), status_code=303)
    _delete_cookie(response, SESSION_COOKIE, "/")
    return response


async def ready(_request: Request) -> Response:
    """Tell Lambda Web Adapter the app is up. It returns no data and needs no session."""
    return PlainTextResponse("ok")


class RequireLogin:
    """Reject a request with no valid Cognito session before it reaches a route.

    With no login configured, every request passes. Otherwise ``GET /``
    redirects to the login, and every other route gets a 401. A passing
    request carries the user's Cognito ``sub`` as ``request.state.user_id``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # The lifespan sets this. A request before it would fail here, closed.
        cognito: CognitoLogin | None = scope["app"].state.login
        if cognito is None or scope["path"] in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        claims = None
        if token := Request(scope).cookies.get(SESSION_COOKIE):
            try:
                claims = await asyncio.to_thread(cognito.verify, token)
            except jwt.PyJWTError as error:
                logger.info("Rejected a session token: %s", error)
        if claims is None:
            response: Response
            if scope["path"] == "/" and scope["method"] == "GET":
                response = RedirectResponse("/auth/login", status_code=303)
            else:
                response = JSONResponse({"error": "Sign in to use the fleet UI."}, status_code=401)
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["user_id"] = claims["sub"]
        await self.app(scope, receive, send)
