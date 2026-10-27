"""End-to-end API checks with an isolated database and a local model upstream."""

from __future__ import annotations

import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND = Path(__file__).resolve().parents[1] / "backend"
PASSWORD = "A-strong-demo-password-123"


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Import the application against a fresh database for every test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret-key-with-sufficient-length")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("ALLOW_LOOPBACK_UPSTREAMS", "1")
    monkeypatch.setenv("OIDC_DISCOVERY_URL", "")
    monkeypatch.syspath_prepend(str(BACKEND))
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    application = importlib.import_module("app.main").app
    yield application
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def create_user(client: TestClient, email: str, name: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "name": name},
    )
    assert response.status_code in (200, 201), response.text
    user = response.json()
    login = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return user


def write(client: TestClient, method: str, path: str, **kwargs):
    token_response = client.get("/api/auth/csrf")
    assert token_response.status_code == 200, token_response.text
    headers = {"X-CSRF-Token": token_response.json()["csrf_token"]}
    headers.update(kwargs.pop("headers", {}))
    return client.request(method, path, headers=headers, **kwargs)


def created(response) -> dict:
    assert response.status_code in (200, 201), response.text
    result = response.json()
    assert "id" in result, result
    return result


def test_first_user_admin_viewer_permissions_and_password_reset(app):
    with TestClient(app) as admin, TestClient(app) as viewer:
        first = create_user(admin, "admin@example.test", "Admin")
        second = create_user(viewer, "viewer@example.test", "Viewer")
        assert first["role"] == "admin"
        assert second["role"] == "viewer"

        assert admin.get("/api/users").status_code == 200
        assert viewer.get("/api/users").status_code == 403
        assert write(viewer, "POST", "/api/nodes", json={"name": "denied", "address": "10.0.0.10"}).status_code == 403
        assert write(viewer, "POST", "/api/api-keys", json={"name": "denied"}).status_code == 403
        assert write(viewer, "PUT", "/api/settings", json={"site_name": "denied"}).status_code == 403

        promoted = write(admin, "PUT", f"/api/users/{second['id']}/role", json={"role": "operator"})
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["role"] == "operator"
        allowed = write(viewer, "POST", "/api/nodes", json={"name": "operator node", "address": "10.0.0.12"})
        assert allowed.status_code in (200, 201), allowed.text
        assert viewer.get("/api/users").status_code == 403

        forgot = viewer.post("/api/auth/forgot-password", json={"email": "viewer@example.test"})
        assert forgot.status_code == 200, forgot.text
        reset_token = forgot.json().get("reset_token")
        assert reset_token, "DEMO_MODE must return a usable reset token"
        reset = viewer.post(
            "/api/auth/reset-password",
            json={"token": reset_token, "password": "A-new-strong-password-456"},
        )
        assert reset.status_code == 200, reset.text
        assert viewer.get("/api/auth/me").status_code == 401
        old_login = viewer.post(
            "/api/auth/login",
            json={"email": "viewer@example.test", "password": PASSWORD},
        )
        assert old_login.status_code in (400, 401)
        new_login = viewer.post(
            "/api/auth/login",
            json={"email": "viewer@example.test", "password": "A-new-strong-password-456"},
        )
        assert new_login.status_code == 200, new_login.text
        reused = viewer.post(
            "/api/auth/reset-password",
            json={"token": reset_token, "password": PASSWORD},
        )
        assert reused.status_code in (400, 401), "reset tokens must be single-use"


def test_resource_crud_and_api_key_secret_is_shown_once(app):
    with TestClient(app) as client:
        create_user(client, "admin@example.test", "Admin")
        missing_csrf = client.post("/api/nodes", json={"name": "must fail", "address": "127.0.0.1"})
        assert missing_csrf.status_code == 403
        node = created(write(client, "POST", "/api/nodes", json={"name": "GPU host", "address": "127.0.0.1"}))
        model = created(write(client, "POST", "/api/models", json={"name": "Demo model", "model_id": "demo/model"}))
        deployment = created(
            write(
                client,
                "POST",
                "/api/deployments",
                json={
                    "name": "Demo service",
                    "model_id": model["id"],
                    "node_id": node["id"],
                    "upstream_url": "http://127.0.0.1:9999/v1",
                },
            )
        )
        route = created(
            write(
                client,
                "POST",
                "/api/routes",
                json={"name": "Demo route", "model_alias": "demo-chat", "deployment_id": deployment["id"]},
            )
        )
        key = created(write(client, "POST", "/api/api-keys", json={"name": "Demo key"}))
        assert key["secret"]
        keys = client.get("/api/api-keys")
        assert keys.status_code == 200, keys.text
        assert all("secret" not in item for item in keys.json())

        nodes = client.get("/api/nodes")
        assert nodes.status_code == 200 and any(item["id"] == node["id"] for item in nodes.json())
        updated = write(
            client,
            "PUT",
            f"/api/nodes/{node['id']}",
            json={"name": "GPU host updated"},
        )
        assert updated.status_code == 200 and updated.json()["name"] == "GPU host updated"
        assert write(client, "DELETE", f"/api/api-keys/{key['id']}").status_code in (200, 204)
        assert write(client, "DELETE", f"/api/routes/{route['id']}").status_code in (200, 204)
        assert write(client, "DELETE", f"/api/deployments/{deployment['id']}").status_code in (200, 204)
        assert write(client, "DELETE", f"/api/nodes/{node['id']}").status_code in (200, 204)


def test_profile_settings_and_unconfigured_sso(app):
    with TestClient(app) as client:
        create_user(client, "admin@example.test", "Admin")
        sso = client.get("/api/sso/config")
        assert sso.status_code == 200 and sso.json()["enabled"] is False
        assert client.get("/api/auth/oidc/start").status_code == 503

        profile = write(client, "PUT", "/api/auth/profile", json={"name": "Updated name"})
        assert profile.status_code == 200 and profile.json()["name"] == "Updated name"
        assert client.get("/api/auth/me").json()["name"] == "Updated name"

        settings = client.get("/api/settings")
        assert settings.status_code == 200, settings.text
        updated = write(client, "PUT", "/api/settings", json={"site_name": "Noveris Demo"})
        assert updated.status_code == 200, updated.text
        assert client.get("/api/settings").json()["site_name"] == "Noveris Demo"


def test_production_rejects_dns_names_for_nodes_and_upstreams(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'production.db').as_posix()}")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret-key-with-sufficient-length")
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("ALLOW_LOOPBACK_UPSTREAMS", "0")
    monkeypatch.setenv("OIDC_DISCOVERY_URL", "")
    monkeypatch.syspath_prepend(str(BACKEND))
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    try:
        production_app = importlib.import_module("app.main").app
        with TestClient(production_app) as client:
            create_user(client, "admin@example.test", "Admin")
            bad_node = write(client, "POST", "/api/nodes", json={"name": "DNS node", "address": "example.com"})
            assert bad_node.status_code == 422
            assert write(client, "POST", "/api/nodes", json={"name": "Localhost", "address": "localhost"}).status_code == 422
            node = created(write(client, "POST", "/api/nodes", json={"name": "IP node", "address": "192.0.2.10"}))
            model = created(write(client, "POST", "/api/models", json={"name": "Model", "model_id": "test/model"}))
            bad_deployment = write(
                client,
                "POST",
                "/api/deployments",
                json={
                    "name": "DNS upstream",
                    "model_id": model["id"],
                    "node_id": node["id"],
                    "upstream_url": "http://example.com:8000/v1",
                },
            )
            assert bad_deployment.status_code == 422
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def test_ssh_node_credentials_are_encrypted_and_never_returned(app, monkeypatch):
    backend = sys.modules["app.main"]
    synthetic_password = "synthetic-ssh-fixture-password-123"
    facts = {
        "hostname": "fixture-node",
        "os": "Test Linux",
        "kernel": "6.0-test",
        "cpu_cores": 8,
        "memory_gb": 32.0,
        "gpus": [{"name": "Test GPU", "memory_mb": 16384, "driver_version": "test-driver"}],
    }
    observed: dict = {}

    def fake_ssh_collect(address, port, username, password):
        observed.update(address=address, port=port, username=username, password=password)
        return facts

    monkeypatch.setattr(backend, "ssh_collect_facts", fake_ssh_collect)
    with TestClient(app) as client:
        create_user(client, "admin@example.test", "Admin")
        too_long_password = "synthetic-overlong-password-" * 50
        invalid = write(
            client,
            "POST",
            "/api/nodes",
            json={"name": "invalid SSH fixture", "address": "192.0.2.10", "username": "test-operator", "password": too_long_password},
        )
        assert invalid.status_code == 422
        assert too_long_password not in invalid.text
        node = created(
            write(
                client,
                "POST",
                "/api/nodes",
                json={
                    "name": "SSH fixture",
                    "address": "192.0.2.10",
                    "port": 22,
                    "username": "test-operator",
                    "password": synthetic_password,
                },
            )
        )
        assert node["has_password"] is True
        assert "password" not in node and "password_enc" not in node
        with backend.db() as conn:
            stored = conn.execute("SELECT password_enc FROM nodes WHERE id=?", (node["id"],)).fetchone()["password_enc"]
        assert stored and synthetic_password not in stored
        assert backend.FERNET.decrypt(stored.encode()).decode() == synthetic_password

        checked = write(client, "POST", f"/api/nodes/{node['id']}/check")
        assert checked.status_code == 200, checked.text
        assert checked.json()["status"] == "online"
        assert checked.json()["last_check_mode"] == "ssh"
        assert checked.json()["facts"] == facts
        assert observed == {
            "address": "192.0.2.10",
            "port": 22,
            "username": "test-operator",
            "password": synthetic_password,
        }
        for payload in (node, checked.json(), client.get(f"/api/nodes/{node['id']}").json(), client.get("/api/nodes").json()):
            encoded = json.dumps(payload)
            assert synthetic_password not in encoded
            assert "password_enc" not in encoded

        def unexpected_ssh_failure(*_args):
            raise RuntimeError(f"internal exception included {synthetic_password}")

        monkeypatch.setattr(backend, "ssh_collect_facts", unexpected_ssh_failure)
        failed = write(client, "POST", f"/api/nodes/{node['id']}/check")
        assert failed.status_code == 200 and failed.json()["status"] == "offline"
        assert synthetic_password not in json.dumps(failed.json())


def test_ssh_check_requires_pinned_known_hosts(app, monkeypatch):
    pytest.importorskip("paramiko")
    backend = sys.modules["app.main"]
    monkeypatch.delenv("SSH_KNOWN_HOSTS", raising=False)
    with pytest.raises(backend.NodeCheckError, match="known_hosts"):
        backend.ssh_collect_facts("192.0.2.10", 22, "test-operator", "synthetic-ssh-fixture-password-123")


@pytest.fixture
def model_upstream():
    calls: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            calls.append({"path": self.path, "headers": dict(self.headers), "body": None})
            data = json.dumps({"object": "list", "data": [{"id": "real-upstream-model", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            request_body = json.loads(body)
            calls.append({"path": self.path, "headers": dict(self.headers), "body": request_body})
            if request_body.get("stream") is True:
                data = (
                    b'data: {"id":"chunk-from-upstream","choices":[{"delta":{"content":"streamed reply"}}]}\n\n'
                    b"data: [DONE]\n\n"
                )
                media_type = "text/event-stream"
            else:
                payload = {
                    "id": "chatcmpl-from-upstream",
                    "object": "chat.completion",
                    "model": "real-upstream-model",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "reply from local upstream"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6},
                }
                data = json.dumps(payload).encode()
                media_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_gateway_uses_route_and_forwards_to_real_http_upstream(app, model_upstream):
    upstream_url, calls = model_upstream
    with TestClient(app) as client:
        create_user(client, "admin@example.test", "Admin")
        node = created(write(client, "POST", "/api/nodes", json={"name": "Local node", "address": "127.0.0.1"}))
        model = created(write(client, "POST", "/api/models", json={"name": "Test model", "model_id": "real-upstream-model"}))
        deployment = created(
            write(
                client,
                "POST",
                "/api/deployments",
                json={
                    "name": "Live upstream",
                    "model_id": model["id"],
                    "node_id": node["id"],
                    "upstream_url": upstream_url,
                    "upstream_api_key": "upstream-secret",
                },
            )
        )
        created_route = created(
            write(
                client,
                "POST",
                "/api/routes",
                json={"name": "Public alias", "model_alias": "public-chat", "deployment_id": deployment["id"]},
            )
        )
        key = created(write(client, "POST", "/api/api-keys", json={"name": "Client key"}))

        health = write(client, "POST", f"/api/deployments/{deployment['id']}/check")
        assert health.status_code == 200, health.text
        assert any(call["path"] == "/v1/models" for call in calls)
        model_test = write(client, "POST", "/api/test", json={"route_id": created_route["id"], "prompt": "ping"})
        assert model_test.status_code == 200, model_test.text
        assert model_test.json()["choices"][0]["message"]["content"] == "reply from local upstream"

        request_body = {"model": "public-chat", "messages": [{"role": "user", "content": "ping"}], "stream": False}
        unauthorized = client.post("/v1/chat/completions", json=request_body, headers={"Authorization": "Bearer wrong-key"})
        assert unauthorized.status_code == 401
        response = client.post(
            "/v1/chat/completions",
            json=request_body,
            headers={"Authorization": f"Bearer {key['secret']}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["choices"][0]["message"]["content"] == "reply from local upstream"
        assert response.json()["usage"]["total_tokens"] == 6
        chat_calls = [call for call in calls if call["path"] == "/v1/chat/completions"]
        assert len(chat_calls) == 2
        assert chat_calls[-1]["body"]["messages"] == request_body["messages"]
        assert chat_calls[-1]["headers"]["Authorization"] == "Bearer upstream-secret"


def test_gateway_streams_sse_bytes_from_real_http_upstream(app, model_upstream):
    upstream_url, calls = model_upstream
    with TestClient(app) as client:
        create_user(client, "admin@example.test", "Admin")
        node = created(write(client, "POST", "/api/nodes", json={"name": "Stream node", "address": "127.0.0.1"}))
        model = created(write(client, "POST", "/api/models", json={"name": "Stream model", "model_id": "real-upstream-model"}))
        deployment = created(
            write(
                client,
                "POST",
                "/api/deployments",
                json={
                    "name": "Stream upstream",
                    "model_id": model["id"],
                    "node_id": node["id"],
                    "upstream_url": upstream_url,
                    "upstream_api_key": "upstream-secret",
                },
            )
        )
        created(
            write(
                client,
                "POST",
                "/api/routes",
                json={"name": "Stream route", "model_alias": "stream-chat", "deployment_id": deployment["id"]},
            )
        )
        key = created(write(client, "POST", "/api/api-keys", json={"name": "Stream key"}))
        request_body = {"model": "stream-chat", "messages": [{"role": "user", "content": "stream please"}], "stream": True}

        with client.stream(
            "POST",
            "/v1/chat/completions",
            json=request_body,
            headers={"Authorization": f"Bearer {key['secret']}"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            received = b"".join(response.iter_bytes())

        assert b'"content":"streamed reply"' in received
        assert received.endswith(b"data: [DONE]\n\n")
        assert len(calls) == 1
        assert calls[0]["path"] == "/v1/chat/completions"
        assert calls[0]["body"]["model"] == "real-upstream-model"
        assert calls[0]["body"]["stream"] is True
        assert calls[0]["headers"]["Authorization"] == "Bearer upstream-secret"
