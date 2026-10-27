"""Exercise the configured OIDC authorization-code flow against a local signed IdP."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient


BACKEND = Path(__file__).resolve().parents[1] / "backend"


@pytest.fixture
def local_idp():
    pytest.importorskip("authlib")
    from authlib.jose import JsonWebKey, jwt

    good_key = JsonWebKey.generate_key("RSA", 2048, options={"kid": "test-key"}, is_private=True)
    wrong_key = JsonWebKey.generate_key("RSA", 2048, options={"kid": "test-key"}, is_private=True)
    state: dict = {"nonce": None, "challenge": None, "bad_signature": False, "token_requests": []}

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status: int, payload: dict):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            issuer = f"http://127.0.0.1:{self.server.server_port}"
            if self.path == "/.well-known/openid-configuration":
                self.respond(200, {
                    "issuer": issuer,
                    "authorization_endpoint": issuer + "/authorize",
                    "token_endpoint": issuer + "/token",
                    "jwks_uri": issuer + "/jwks",
                    "userinfo_endpoint": issuer + "/userinfo",
                    "response_types_supported": ["code"],
                    "subject_types_supported": ["public"],
                    "id_token_signing_alg_values_supported": ["RS256"],
                    "code_challenge_methods_supported": ["S256"],
                })
            elif self.path == "/jwks":
                self.respond(200, {"keys": [good_key.as_dict(is_private=False)]})
            else:
                self.respond(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path != "/token":
                self.respond(404, {"error": "not_found"})
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
            params = {key: values[0] for key, values in parse_qs(body).items()}
            state["token_requests"].append(params)
            verifier = params.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if params.get("code") != "valid-code" or challenge != state["challenge"]:
                self.respond(400, {"error": "invalid_grant"})
                return
            issuer = f"http://127.0.0.1:{self.server.server_port}"
            now = int(time.time())
            claims = {
                "iss": issuer,
                "sub": "employee-123",
                "aud": "noveris-test-client",
                "iat": now,
                "exp": now + 300,
                "nonce": state["nonce"],
                "email": "sso-user@example.test",
                "email_verified": True,
                "name": "SSO User",
            }
            signing_key = wrong_key if state["bad_signature"] else good_key
            id_token = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, signing_key).decode()
            self.respond(200, {"access_token": "local-access-token", "token_type": "Bearer", "expires_in": 300, "id_token": id_token})

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_oidc_validates_signed_id_token_state_nonce_and_pkce(local_idp, tmp_path, monkeypatch):
    issuer, idp_state = local_idp
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'oidc.db').as_posix()}")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret-key-with-sufficient-length")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("OIDC_DISCOVERY_URL", issuer + "/.well-known/openid-configuration")
    monkeypatch.setenv("OIDC_CLIENT_ID", "noveris-test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("AUTHLIB_INSECURE_TRANSPORT", "1")
    monkeypatch.syspath_prepend(str(BACKEND))
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    app = importlib.import_module("app.main").app

    def start(client: TestClient) -> str:
        response = client.get("/api/auth/oidc/start", follow_redirects=False)
        assert response.status_code in (302, 303), response.text
        params = parse_qs(urlparse(response.headers["location"]).query)
        assert params["code_challenge_method"] == ["S256"]
        idp_state["nonce"] = params["nonce"][0]
        idp_state["challenge"] = params["code_challenge"][0]
        return params["state"][0]

    try:
        with TestClient(app) as client:
            state = start(client)
            callback = client.get(f"/api/auth/oidc/callback?code=valid-code&state={state}", follow_redirects=False)
            assert callback.status_code == 303, callback.text
            assert idp_state["token_requests"][-1].get("code_verifier")
            me = client.get("/api/auth/me")
            assert me.status_code == 200, me.text
            assert me.json()["email"] == "sso-user@example.test"
            assert me.json()["role"] == "viewer"

        with TestClient(app) as client:
            idp_state["bad_signature"] = True
            state = start(client)
            rejected = client.get(f"/api/auth/oidc/callback?code=valid-code&state={state}", follow_redirects=False)
            assert rejected.status_code == 401
            assert client.get("/api/auth/me").status_code == 401
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
