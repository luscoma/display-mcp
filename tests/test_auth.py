"""auth.py: Cloudflare Access JWT verification, with a locally signed token
against a fake JWKS client (no network)."""

from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from display_mcp.auth import _PROXY_HEADERS, wrap_with_access_auth
from display_mcp.config import Settings

TEAM = "https://example.cloudflareaccess.com"
AUD = "test-aud-tag"
KID = "test-kid"


def _rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


PRIVATE_KEY, PUBLIC_KEY = _rsa_keypair()
OTHER_PRIVATE_KEY, _OTHER_PUBLIC_KEY = _rsa_keypair()


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class FakeJWKClient:
    """Stands in for jwt.PyJWKClient: resolves a `kid` to a public key, no network."""

    def __init__(self, keys):
        self._keys = dict(keys)

    def get_signing_key_from_jwt(self, token):
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if kid not in self._keys:
            raise jwt.PyJWKClientError(f"no signing key for kid {kid!r}")
        return _FakeSigningKey(self._keys[kid])


def _sign(claims, *, key=None, kid=KID):
    key = PRIVATE_KEY if key is None else key
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _claims(**overrides):
    now = int(time.time())
    base = {
        "iss": TEAM,
        "aud": AUD,
        "email": "alex@example.com",
        "sub": "user-123",
        "iat": now,
        "exp": now + 3600,
    }
    base.update(overrides)
    return base


def _settings(**overrides) -> Settings:
    base = {"cf_access_team_domain": TEAM, "cf_access_aud": AUD}
    base.update(overrides)
    return Settings(**base)


async def _downstream(scope, receive, send):
    state = scope.get("state", {}) if scope["type"] == "http" else {}
    identity = state.get("access_identity")
    body = json.dumps({"ok": True, "identity": identity}).encode()
    headers = [(b"content-type", b"application/json")]
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _client(keys=None, settings=None) -> TestClient:
    jwk_client = FakeJWKClient(keys if keys is not None else {KID: PUBLIC_KEY})
    settings = settings or _settings()
    app = wrap_with_access_auth(_downstream, settings, jwk_client_factory=lambda url: jwk_client)
    return TestClient(app)


def test_valid_token_via_access_header():
    token = _sign(_claims())
    resp = _client().post("/mcp", headers={"Cf-Access-Jwt-Assertion": token})
    assert resp.status_code == 200
    assert resp.json()["identity"] == {"email": "alex@example.com", "sub": "user-123"}


def test_valid_token_via_bearer_fallback():
    token = _sign(_claims())
    resp = _client().post("/mcp", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["identity"]["email"] == "alex@example.com"


def test_access_header_preferred_over_bearer():
    good = _sign(_claims())
    resp = _client().post(
        "/mcp",
        headers={"Cf-Access-Jwt-Assertion": good, "Authorization": "Bearer garbage-not-a-jwt"},
    )
    assert resp.status_code == 200


def test_missing_token_401():
    resp = _client().post("/mcp")
    assert resp.status_code == 401
    assert resp.json() == {"error": "missing Cloudflare Access token"}


def test_expired_token_401():
    token = _sign(_claims(iat=int(time.time()) - 7200, exp=int(time.time()) - 3600))
    resp = _client().post("/mcp", headers={"Cf-Access-Jwt-Assertion": token})
    assert resp.status_code == 401
    assert resp.json()["reason"] == "expired"


def test_wrong_audience_401():
    token = _sign(_claims(aud="someone-elses-aud"))
    resp = _client().post("/mcp", headers={"Cf-Access-Jwt-Assertion": token})
    assert resp.status_code == 401
    assert resp.json()["reason"] == "bad audience"


def test_wrong_issuer_401():
    token = _sign(_claims(iss="https://someone-else.cloudflareaccess.com"))
    resp = _client().post("/mcp", headers={"Cf-Access-Jwt-Assertion": token})
    assert resp.status_code == 401
    assert resp.json()["reason"] == "bad issuer"


def test_issuer_trailing_slash_is_accepted():
    token = _sign(_claims(iss=f"{TEAM}/"))
    resp = _client().post("/mcp", headers={"Cf-Access-Jwt-Assertion": token})
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "token_kwargs",
    [
        # Signed with a key never registered under this kid in the JWKS
        # (jwt.InvalidSignatureError) ...
        pytest.param({"key": OTHER_PRIVATE_KEY}, id="wrong-signing-key"),
        # ... and a kid the JWKS has never heard of (jwt.PyJWKClientError).
        pytest.param({"kid": "not-in-the-jwks"}, id="unknown-kid"),
    ],
)
def test_unverifiable_signature_401(token_kwargs):
    """Both arrive as "bad signature": two different PyJWT exceptions caught
    by the one `except` tuple in `_verify`, deliberately not distinguished in
    the reply -- a caller has no business learning which."""
    token = _sign(_claims(), **token_kwargs)
    resp = _client().post("/mcp", headers={"Cf-Access-Jwt-Assertion": token})
    assert resp.status_code == 401
    assert resp.json()["reason"] == "bad signature"


def test_disabled_settings_returns_app_unchanged():
    """No team domain / AUD configured (the local-dev shape) returns the very
    same app object -- so there is no middleware at all to wrap a request,
    stash an identity, or demand a header."""
    app = wrap_with_access_auth(_downstream, Settings())
    assert app is _downstream
    resp = TestClient(app).post("/mcp")
    assert resp.status_code == 200
    assert resp.json()["identity"] is None


def _auth_client(peer: tuple[str, int]) -> TestClient:
    jwk_client = FakeJWKClient({KID: PUBLIC_KEY})
    app = wrap_with_access_auth(_downstream, _settings(), jwk_client_factory=lambda url: jwk_client)
    return TestClient(app, client=peer)


def test_loopback_without_proxy_headers_is_a_local_operator():
    r = _auth_client(("127.0.0.1", 40000)).get("/")
    assert r.status_code == 200
    assert r.json()["identity"] == {"email": None, "sub": "local"}
    # And a non-loopback peer without a token is rejected as before.
    assert _auth_client(("192.168.0.180", 40000)).get("/").status_code == 401


@pytest.mark.parametrize("header", _PROXY_HEADERS)
def test_a_proxy_header_on_loopback_still_needs_a_token(header):
    """cloudflared connects from 127.0.0.1 but forwards Cloudflare's own
    headers, so the local-operator exemption must not fire for tunnel
    traffic. Parametrized over `auth._PROXY_HEADERS` itself rather than a
    hand-picked few, so a header added to that tuple is covered here too."""
    local = _auth_client(("127.0.0.1", 40000))
    assert local.get("/", headers={header: "203.0.113.9"}).status_code == 401


def test_every_request_gets_one_log_line(caplog):
    import logging

    client = _auth_client(("192.168.0.180", 40000))
    with caplog.at_level(logging.INFO, logger="display_mcp.auth"):
        client.get("/mcp", headers={"CF-Connecting-IP": "203.0.113.9"})
    lines = [r.getMessage() for r in caplog.records]
    assert any("no token on GET /mcp" in ln for ln in lines)
    hit = [ln for ln in lines if "GET /mcp -> 401" in ln]
    assert hit and "via=cf-connecting-ip" in hit[0] and "token=none" in hit[0]
