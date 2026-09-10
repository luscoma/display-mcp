"""Cloudflare Access JWT verification as a Starlette middleware.

Wraps the MCP app. Reads `Cf-Access-Jwt-Assertion`, falling back to
`Authorization: Bearer`. Verifies RS256 against the team's JWKS
(https://<team>/cdn-cgi/access/certs), iss == team domain, aud contains the
configured AUD tag, 60 s leeway. 401 with a JSON body otherwise.

One exemption: a request whose peer is loopback and that carries no proxy
header (X-Forwarded-*, CF-Connecting-IP) is a local operator, i.e.
`display-mcp-cli publish` run on the host. cloudflared connects from
loopback too but always sets X-Forwarded-For and CF-Connecting-IP, so
anything that came through the tunnel still needs a token.

When settings.auth_enabled is False the middleware is a no-op.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, MutableMapping
from typing import Any

import jwt
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings

logger = logging.getLogger(__name__)

# Injectable so tests can point at a locally generated RSA key / fake JWKS
# endpoint instead of a real network call. Defaults to PyJWT's own client,
# which fetches https://<team>/cdn-cgi/access/certs and caches it (tier 1:
# the whole JWK Set, 5 min TTL) plus, with cache_keys=True, individual
# signing keys by kid (tier 2, LRU); an unseen kid still triggers exactly
# one refetch-and-retry inside PyJWKClient.get_signing_key before it gives up.
JWKClientFactory = Callable[[str], "jwt.PyJWKClient"]


def _default_jwk_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True)


class _MissingToken(Exception):
    pass


class _InvalidToken(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _extract_token(headers: Headers) -> str:
    token = headers.get("cf-access-jwt-assertion")
    if token:
        return token
    authorization = headers.get("authorization", "")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value
    raise _MissingToken()


_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "cf-connecting-ip")


def _is_local_operator(scope: Scope, headers: Headers) -> bool:
    """True for a request from 127.0.0.1/::1 that no reverse proxy touched."""
    client = scope.get("client")
    if not client or client[0] not in ("127.0.0.1", "::1"):
        return False
    return not any(h in headers for h in _PROXY_HEADERS)


def _peer(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else "?"


def _via(headers: Headers) -> str:
    """Which proxy headers came with the request; tells tunnel from local."""
    return ",".join(h for h in _PROXY_HEADERS if h in headers) or "direct"


def _logging_send(scope: Scope, headers: Headers, send: Send) -> Send:
    """Wrap `send` so every request gets one line: method path -> status, ms.

    The MCP app has no access log of its own, and this is the only place that
    sees the request before the SDK answers it. Auth-related lines are logged
    separately; this one is for "did the request arrive, and what came back".
    """
    started = time.monotonic()

    async def wrapped(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            logger.info(
                "%s %s -> %s %.0fms peer=%s via=%s token=%s",
                scope.get("method"), scope.get("path"), message["status"],
                (time.monotonic() - started) * 1000, _peer(scope), _via(headers),
                "assertion" if "cf-access-jwt-assertion" in headers
                else "bearer" if headers.get("authorization", "").lower().startswith("bearer ")
                else "none",
            )
        await send(message)

    return wrapped


class _AccessAuthMiddleware:
    """Verifies a Cloudflare Access JWT on every HTTP request, else 401.

    On success, `{"email", "sub"}` from the token's claims is stashed at
    `scope["state"]["access_identity"]` and one INFO line is logged naming
    the email — so the identity behind each tool call (a stateless-HTTP call
    is one HTTP request) ends up in the log without threading it through the
    MCP tool layer.
    """

    def __init__(self, app: ASGIApp, settings: Settings, jwk_client: jwt.PyJWKClient) -> None:
        self.app = app
        self.settings = settings
        self.jwk_client = jwk_client
        assert settings.cf_access_team_domain is not None
        assert settings.cf_access_aud is not None
        self._team = settings.cf_access_team_domain.rstrip("/")
        self._aud = settings.cf_access_aud

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        send = _logging_send(scope, headers, send)
        if _is_local_operator(scope, headers):
            # display-mcp-cli publish on the host itself. cloudflared always
            # adds X-Forwarded-For, so a loopback peer without any proxy
            # header is a local process, not the internet.
            state = scope.setdefault("state", {})
            state["access_identity"] = {"email": None, "sub": "local"}
            logger.info("Cloudflare Access: local operator on loopback, no token required")
            await self.app(scope, receive, send)
            return
        try:
            token = _extract_token(headers)
            claims = self._verify(token)
        except _MissingToken:
            logger.info(
                "Cloudflare Access: no token on %s %s from %s (via=%s)",
                scope.get("method"), scope.get("path"), _peer(scope), _via(headers),
            )
            await self._reject(scope, receive, send, {"error": "missing Cloudflare Access token"})
            return
        except _InvalidToken as exc:
            logger.info("Cloudflare Access: rejected token (%s)", exc.reason)
            body = {"error": "invalid Cloudflare Access token", "reason": exc.reason}
            await self._reject(scope, receive, send, body)
            return

        identity = {"email": claims.get("email"), "sub": claims.get("sub")}
        state = scope.setdefault("state", {})
        state["access_identity"] = identity
        logger.info("Cloudflare Access: %s", identity["email"])
        await self.app(scope, receive, send)

    def _verify(self, token: str) -> dict[str, object]:
        try:
            signing_key = self.jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._aud,
                leeway=60,
                options={"require": ["exp", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise _InvalidToken("expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise _InvalidToken("bad audience") from exc
        except (jwt.InvalidSignatureError, jwt.DecodeError, jwt.PyJWKClientError) as exc:
            raise _InvalidToken("bad signature") from exc
        except jwt.InvalidTokenError as exc:
            raise _InvalidToken("invalid token") from exc

        # PyJWT's `issuer=` check wants an exact string match; Access's `iss`
        # is the bare team domain, but we accept a trailing slash too rather
        # than depend on exactly how the operator wrote the env var.
        iss = claims.get("iss")
        if iss not in (self._team, f"{self._team}/"):
            raise _InvalidToken("bad issuer")
        return claims

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, body: dict[str, str]) -> None:
        response = JSONResponse(body, status_code=401)
        await response(scope, receive, send)


def wrap_with_access_auth(
    app: ASGIApp,
    settings: Settings,
    *,
    jwk_client_factory: JWKClientFactory | None = None,
) -> ASGIApp:
    """Wrap `app` with Cloudflare Access verification, or return it unchanged.

    A no-op when `settings.auth_enabled` is False (no team domain / AUD
    configured), which is the local-dev shape. `jwk_client_factory` lets
    tests substitute a fake JWKS client (e.g. backed by a locally generated
    RSA key) instead of PyJWT's default, which fetches over the network.
    """
    if not settings.auth_enabled:
        return app
    assert settings.cf_access_team_domain is not None
    factory = jwk_client_factory or _default_jwk_client
    jwks_url = f"{settings.cf_access_team_domain.rstrip('/')}/cdn-cgi/access/certs"
    jwk_client = factory(jwks_url)
    return _AccessAuthMiddleware(app, settings, jwk_client)
