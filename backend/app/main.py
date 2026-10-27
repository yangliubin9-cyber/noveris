"""Small, persistent control plane and honest OpenAI-compatible forwarding gateway.

Deployments in this MVP register *already running* inference endpoints. They do
not install runtimes, download weights, or launch GPU processes.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import smtplib
import socket
import ssl
import sqlite3
import time
from typing import Any, Iterator, Literal
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
import httpx
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware


load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./noveris.db")
SECRET_KEY = os.getenv("SECRET_KEY", "")
if len(SECRET_KEY) < 32:
    if os.getenv("DEMO_MODE", "0") != "1":
        raise RuntimeError("SECRET_KEY must contain at least 32 characters")
    SECRET_KEY = "demo-only-replace-this-secret-before-deployment"
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
if not DEMO_MODE and (SECRET_KEY.startswith("replace-with-") or SECRET_KEY.startswith("demo-only-")):
    raise RuntimeError("Replace the example SECRET_KEY before disabling DEMO_MODE")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
ALLOW_LOOPBACK = os.getenv("ALLOW_LOOPBACK_UPSTREAMS", "0") == "1" or DEMO_MODE
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_RAW = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
try:
    CORS_ORIGINS = json.loads(CORS_RAW) if CORS_RAW.startswith("[") else [x.strip() for x in CORS_RAW.split(",") if x.strip()]
except json.JSONDecodeError as exc:
    raise RuntimeError("CORS_ORIGINS must be comma-separated origins or a JSON array") from exc
if not CORS_ORIGINS or "*" in CORS_ORIGINS:
    raise RuntimeError("Set explicit CORS_ORIGINS when cookies are enabled")

OIDC_DISCOVERY_URL = os.getenv("OIDC_DISCOVERY_URL", "").strip()
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip()
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "").strip()
OIDC_PROVIDER_NAME = os.getenv("OIDC_PROVIDER_NAME", "Enterprise SSO")
OIDC_ENABLED = bool(OIDC_DISCOVERY_URL and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET)
if OIDC_ENABLED:
    discovery = urlparse(OIDC_DISCOVERY_URL)
    if discovery.scheme != "https" and not (DEMO_MODE and discovery.scheme == "http" and discovery.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise RuntimeError("OIDC_DISCOVERY_URL must use HTTPS (local HTTP is allowed only in DEMO_MODE)")

if not DATABASE_URL.startswith("sqlite:///"):
    raise RuntimeError("This MVP supports SQLite DATABASE_URL values only")
DB_PATH = Path(DATABASE_URL[len("sqlite:///"):]).expanduser()
if not DB_PATH.is_absolute():
    DB_PATH = (Path.cwd() / DB_PATH).resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(("upstream:" + SECRET_KEY).encode()).digest()))
SESSION_COOKIE = "noveris_session"
SESSION_TTL = 12 * 3600
RESET_TTL = 30 * 60
MAX_PROXY_BODY = 1024 * 1024


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(str(DB_PATH), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
          password_hash TEXT, role TEXT NOT NULL CHECK(role IN ('admin','operator','viewer')),
          auth_provider TEXT NOT NULL DEFAULT 'local', active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS password_resets (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          expires_at INTEGER NOT NULL, consumed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS nodes (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, address TEXT NOT NULL,
          port INTEGER NOT NULL DEFAULT 22 CHECK(port BETWEEN 1 AND 65535),
          description TEXT NOT NULL DEFAULT '', username TEXT, password_enc TEXT,
          facts_json TEXT, last_check_mode TEXT,
          status TEXT NOT NULL DEFAULT 'unknown' CHECK(status IN ('unknown','online','offline')),
          last_check_at TEXT, last_error TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS models (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, model_id TEXT NOT NULL UNIQUE,
          description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'chat',
          source TEXT NOT NULL DEFAULT 'Hugging Face',
          status TEXT NOT NULL DEFAULT 'catalog' CHECK(status='catalog'), created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deployments (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
          model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE RESTRICT,
          node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE RESTRICT,
          upstream_url TEXT NOT NULL, upstream_api_key_enc TEXT,
          status TEXT NOT NULL DEFAULT 'unknown' CHECK(status IN ('unknown','running','unavailable')),
          last_check_at TEXT, last_error TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS routes (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, model_alias TEXT NOT NULL UNIQUE,
          deployment_id INTEGER NOT NULL REFERENCES deployments(id) ON DELETE RESTRICT,
          status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS api_keys (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, prefix TEXT NOT NULL,
          key_hash TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','revoked')),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage_events (
          id INTEGER PRIMARY KEY, route_id INTEGER REFERENCES routes(id) ON DELETE SET NULL,
          api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
          status_code INTEGER NOT NULL, latency_ms INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_attempts (
          id INTEGER PRIMARY KEY, action TEXT NOT NULL, client_ip TEXT NOT NULL,
          identity TEXT NOT NULL, attempted_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
        CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_auth_attempts ON auth_attempts(action,client_ip,identity,attempted_at);
        """)
        existing_node_columns = {row["name"] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()}
        for column in ("username", "password_enc", "facts_json", "last_check_mode"):
            if column not in existing_node_columns:
                conn.execute(f"ALTER TABLE nodes ADD COLUMN {column} TEXT")
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('site_name','Noveris AI')")
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('allow_registration','true')")
        for name, model_id, category, description in [
            ("Qwen 2.5 7B Instruct", "Qwen/Qwen2.5-7B-Instruct", "chat", "目录条目，尚未下载模型权重。"),
            ("Qwen 2.5 3B Instruct", "Qwen/Qwen2.5-3B-Instruct", "chat", "目录条目，尚未下载模型权重。"),
            ("BGE M3", "BAAI/bge-m3", "embedding", "目录条目，尚未下载模型权重。"),
        ]:
            conn.execute("INSERT OR IGNORE INTO models(name,model_id,description,category,source,status,created_at) VALUES (?,?,?,?,?,'catalog',?)",
                         (name, model_id, description, category, "Hugging Face", utcnow()))


initialize_database()

app = FastAPI(title="Noveris MVP API", version="0.1.0")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="noveris_oidc", https_only=COOKIE_SECURE, same_site="lax")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"])


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic includes the rejected input by default; never echo credentials.
    errors = [{key: value for key, value in item.items() if key not in {"input", "ctx"}}
              for item in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


def rowdict(row: sqlite3.Row | None, *, exclude: tuple[str, ...] = ()) -> dict[str, Any] | None:
    return {k: row[k] for k in row.keys() if k not in exclude} if row else None


def get_row(table: str, item_id: int) -> dict[str, Any]:
    if table not in {"nodes", "models", "deployments", "routes", "api_keys", "users"}:
        raise ValueError("Invalid table")
    with db() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Not found")
    if table == "nodes":
        result = rowdict(row, exclude=("password_enc", "facts_json")) or {}
        result["has_password"] = bool(row["password_enc"])
        result["facts"] = json.loads(row["facts_json"]) if row["facts_json"] else None
        return result
    exclusions = {
        "users": ("password_hash", "auth_provider", "active"),
        "deployments": ("upstream_api_key_enc",),
        "api_keys": ("key_hash",),
    }
    return rowdict(row, exclude=exclusions.get(table, ())) or {}


def list_rows(table: str) -> list[dict[str, Any]]:
    if table not in {"nodes", "models", "deployments", "routes", "api_keys", "users"}:
        raise ValueError("Invalid table")
    with db() as conn:
        rows = conn.execute(f"SELECT id FROM {table} ORDER BY id DESC").fetchall()
    return [get_row(table, int(row["id"])) for row in rows]


def conflict(exc: sqlite3.IntegrityError) -> HTTPException:
    return HTTPException(409, "Resource conflicts with an existing record or is still in use")


def password_ok(password: str) -> str:
    if len(password) < 8 or len(password) > 256:
        raise HTTPException(422, "Password must contain 8 to 256 characters")
    return password


def nonblank(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(422, f"{label} cannot be blank")
    return cleaned


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise HTTPException(422, "Invalid email address")
    return value


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in CORS_ORIGINS:
        raise HTTPException(403, "Origin is not allowed")


def auth_rate_limit(action: str, client_ip: str, identity: str, *, window: int, limit: int, record: bool) -> None:
    now = int(time.time())
    with db() as conn:
        conn.execute("DELETE FROM auth_attempts WHERE attempted_at<?", (now - 3600,))
        count = conn.execute("""SELECT COUNT(*) FROM auth_attempts WHERE action=? AND client_ip=?
                                AND identity=? AND attempted_at>=?""",
                             (action, client_ip, identity, now - window)).fetchone()[0]
        if count >= limit:
            raise HTTPException(429, "Too many attempts; try again later")
        if record:
            conn.execute("INSERT INTO auth_attempts(action,client_ip,identity,attempted_at) VALUES (?,?,?,?)",
                         (action, client_ip, identity, now))


def session_hash(token: str) -> str:
    return hashlib.sha256((SECRET_KEY + token).encode()).hexdigest()


def issue_session(response: Response, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES (?,?,?,?,?)",
                     (session_hash(token), user_id, csrf, int(time.time()) + SESSION_TTL, utcnow()))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=COOKIE_SECURE,
                        samesite="lax", max_age=SESSION_TTL, path="/")
    return csrf


def clear_session(response: Response, token: str | None) -> None:
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (session_hash(token),))
    response.delete_cookie(SESSION_COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax")


def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Login required")
    with db() as conn:
        row = conn.execute("""SELECT users.*, sessions.csrf_token FROM sessions JOIN users
                              ON users.id=sessions.user_id WHERE sessions.token_hash=?
                              AND sessions.expires_at>? AND users.active=1""",
                           (session_hash(token), int(time.time()))).fetchone()
    if row is None:
        raise HTTPException(401, "Session expired")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(supplied, row["csrf_token"]):
            raise HTTPException(403, "CSRF token is missing or invalid")
        check_origin(request)
    result = rowdict(row, exclude=("password_hash", "auth_provider", "active")) or {}
    return result


def operator(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] not in {"admin", "operator"}:
        raise HTTPException(403, "Operator role required")
    return user


def admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator role required")
    return user


class RegisterBody(BaseModel):
    email: str
    password: str
    name: str = Field(min_length=1, max_length=120)


class LoginBody(BaseModel):
    email: str
    password: str


class ForgotBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    token: str
    password: str


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


@app.get("/api/health")
def health() -> dict[str, str]:
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterBody, response: Response, request: Request) -> dict[str, Any]:
    check_origin(request)
    auth_rate_limit("register", request.client.host if request.client else "unknown", "*", window=3600, limit=10, record=True)
    email = normalize_email(body.email)
    password_ok(body.password)
    name = nonblank(body.name, "Name")
    try:
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            setting = conn.execute("SELECT value FROM settings WHERE key='allow_registration'").fetchone()
            if count and setting["value"] != "true":
                raise HTTPException(403, "Registration is disabled")
            cursor = conn.execute("INSERT INTO users(email,name,password_hash,role,auth_provider,created_at) VALUES (?,?,?,?,?,?)",
                                  (email, name, PASSWORD_HASHER.hash(body.password), "admin" if count == 0 else "viewer", "local", utcnow()))
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Email is already registered") from exc
    csrf = issue_session(response, user_id)
    return {**get_row("users", user_id), "csrf_token": csrf}


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response, request: Request) -> dict[str, Any]:
    check_origin(request)
    email = normalize_email(body.email)
    client_ip = request.client.host if request.client else "unknown"
    auth_rate_limit("login_ip", client_ip, "*", window=900, limit=30, record=True)
    auth_rate_limit("login", client_ip, email, window=900, limit=5, record=False)
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
    if row is None or not row["password_hash"]:
        auth_rate_limit("login", client_ip, email, window=900, limit=5, record=True)
        raise HTTPException(401, "Invalid email or password")
    try:
        PASSWORD_HASHER.verify(row["password_hash"], body.password)
    except (VerifyMismatchError, VerificationError):
        auth_rate_limit("login", client_ip, email, window=900, limit=5, record=True)
        raise HTTPException(401, "Invalid email or password")
    with db() as conn:
        conn.execute("DELETE FROM auth_attempts WHERE action='login' AND client_ip=? AND identity=?", (client_ip, email))
    csrf = issue_session(response, int(row["id"]))
    return {**get_row("users", int(row["id"])), "csrf_token": csrf}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user


@app.get("/api/auth/csrf")
def csrf(user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    return {"csrf_token": user["csrf_token"]}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, _user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    clear_session(response, request.cookies.get(SESSION_COOKIE))
    return {"message": "Logged out"}


def send_reset_email(recipient: str, token: str) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("SMTP_FROM", "").strip()
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Noveris password reset"
    message.set_content(f"Reset your password: {FRONTEND_URL.rstrip('/')}/reset-password?token={token}\nThis link expires in 30 minutes.")
    tls_context = ssl.create_default_context()
    if os.getenv("SMTP_TLS", "1") == "ssl":
        smtp: Any = smtplib.SMTP_SSL(host, port, timeout=10, context=tls_context)
    else:
        smtp = smtplib.SMTP(host, port, timeout=10)
    with smtp:
        if os.getenv("SMTP_TLS", "1") == "1":
            smtp.starttls(context=tls_context)
        username = os.getenv("SMTP_USER", "")
        if username:
            smtp.login(username, os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)


@app.post("/api/auth/forgot-password")
def forgot_password(body: ForgotBody, request: Request) -> dict[str, str]:
    check_origin(request)
    auth_rate_limit("forgot", request.client.host if request.client else "unknown", "*", window=3600, limit=10, record=True)
    if not DEMO_MODE and not (os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM")):
        raise HTTPException(503, "Password reset email is not configured")
    email = normalize_email(body.email)
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE email=? AND active=1 AND password_hash IS NOT NULL", (email,)).fetchone()
    result = {"message": "If this account exists, a reset link has been issued"}
    if row is None:
        return result
    token = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("DELETE FROM password_resets WHERE user_id=?", (row["id"],))
        conn.execute("INSERT INTO password_resets(token_hash,user_id,expires_at) VALUES (?,?,?)",
                     (session_hash(token), row["id"], int(time.time()) + RESET_TTL))
    if os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"):
        try:
            send_reset_email(email, token)
        except (OSError, smtplib.SMTPException) as exc:
            raise HTTPException(503, "Password reset email could not be sent") from exc
    if DEMO_MODE:
        result["reset_token"] = token
        result["reset_link"] = f"{FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
    return result


@app.post("/api/auth/reset-password")
def reset_password(body: ResetBody, request: Request) -> dict[str, str]:
    check_origin(request)
    password_ok(body.password)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM password_resets WHERE token_hash=? AND consumed_at IS NULL AND expires_at>?",
                           (session_hash(body.token), int(time.time()))).fetchone()
        if row is None:
            raise HTTPException(400, "Reset token is invalid or expired")
        conn.execute("UPDATE users SET password_hash=?,auth_provider='local' WHERE id=?",
                     (PASSWORD_HASHER.hash(body.password), row["user_id"]))
        conn.execute("UPDATE password_resets SET consumed_at=? WHERE token_hash=?", (utcnow(), session_hash(body.token)))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
    return {"message": "Password changed"}


@app.put("/api/auth/profile")
def update_profile(body: ProfileBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    with db() as conn:
        conn.execute("UPDATE users SET name=? WHERE id=?", (nonblank(body.name, "Name"), user["id"]))
    return get_row("users", user["id"])


@app.put("/api/auth/password")
def change_password(body: PasswordBody, response: Response, user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    password_ok(body.new_password)
    with db() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row["password_hash"]:
        raise HTTPException(400, "This SSO account has no local password")
    try:
        PASSWORD_HASHER.verify(row["password_hash"], body.current_password)
    except (VerifyMismatchError, VerificationError):
        raise HTTPException(400, "Current password is incorrect")
    with db() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (PASSWORD_HASHER.hash(body.new_password), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    response.delete_cookie(SESSION_COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax")
    return {"message": "Password changed"}


@app.get("/api/sso/config")
def sso_config() -> dict[str, Any]:
    return {"enabled": OIDC_ENABLED, "provider_name": OIDC_PROVIDER_NAME if OIDC_ENABLED else None}


if OIDC_ENABLED:
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="enterprise",
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        server_metadata_url=OIDC_DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )


@app.get("/api/auth/oidc/start")
async def oidc_start(request: Request) -> Response:
    if not OIDC_ENABLED:
        raise HTTPException(503, "SSO is not configured")
    redirect_uri = str(request.url_for("oidc_callback"))
    # Authlib stores state, nonce and the PKCE verifier in the signed OIDC session.
    return await oauth.enterprise.authorize_redirect(request, redirect_uri)


@app.get("/api/auth/oidc/callback")
async def oidc_callback(request: Request) -> Response:
    if not OIDC_ENABLED:
        raise HTTPException(503, "SSO is not configured")
    try:
        token = await oauth.enterprise.authorize_access_token(request)
        # Authlib attaches userinfo only after verifying the signed ID token and nonce.
        if not token.get("id_token") or not token.get("userinfo"):
            raise ValueError("OIDC provider omitted a verifiable ID token")
        userinfo = token["userinfo"]
    except Exception as exc:
        raise HTTPException(401, "SSO authentication failed") from exc
    if userinfo.get("email_verified") is not True:
        raise HTTPException(403, "SSO provider did not verify the email address")
    email = normalize_email(str(userinfo.get("email", "")))
    name = str(userinfo.get("name") or userinfo.get("preferred_username") or email).strip()[:120]
    try:
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT id,active FROM users WHERE email=?", (email,)).fetchone()
            if row:
                if not row["active"]:
                    raise HTTPException(403, "Account is disabled")
                user_id = int(row["id"])
            else:
                user_id = int(conn.execute("INSERT INTO users(email,name,password_hash,role,auth_provider,created_at) VALUES (?,?,NULL,'viewer','oidc',?)",
                                           (email, name, utcnow())).lastrowid)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "SSO user could not be created") from exc
    response = RedirectResponse(FRONTEND_URL.rstrip("/") + "/", status_code=303)
    issue_session(response, user_id)
    return response


class NodeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    description: str = Field(default="", max_length=1000)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=1024)


class NodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    description: str | None = Field(default=None, max_length=1000)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=1024)


def validate_host(host: str) -> str:
    value = host.strip().lower().rstrip(".")
    if value == "localhost" and ALLOW_LOOPBACK:
        return value
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise HTTPException(422, "Use an IP address for nodes and upstreams; DNS names are not supported in this MVP") from exc


@app.get("/api/nodes")
def nodes(_user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return list_rows("nodes")


@app.post("/api/nodes", status_code=201)
def create_node(body: NodeCreate, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    username = nonblank(body.username, "SSH username") if body.username is not None else None
    if body.password and not username:
        raise HTTPException(422, "SSH username is required when a password is supplied")
    password_enc = FERNET.encrypt(body.password.encode()).decode() if body.password else None
    try:
        with db() as conn:
            item_id = int(conn.execute("INSERT INTO nodes(name,address,port,description,username,password_enc,created_at) VALUES (?,?,?,?,?,?,?)",
                                       (nonblank(body.name, "Name"), validate_host(body.address), body.port,
                                        body.description, username, password_enc, utcnow())).lastrowid)
    except sqlite3.IntegrityError as exc:
        raise conflict(exc) from exc
    return get_row("nodes", item_id)


@app.get("/api/nodes/{item_id}")
def node_detail(item_id: int, _user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return get_row("nodes", item_id)


def update_fields(table: str, item_id: int, values: dict[str, Any], allowed: set[str], nullable: set[str] | None = None) -> dict[str, Any]:
    nullable = nullable or set()
    data = {key: value for key, value in values.items() if key in allowed and (value is not None or key in nullable)}
    if not data:
        raise HTTPException(422, "No fields to update")
    assignments = ", ".join(f"{key}=?" for key in data)
    try:
        with db() as conn:
            cursor = conn.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (*data.values(), item_id))
            if cursor.rowcount == 0:
                raise HTTPException(404, "Not found")
    except sqlite3.IntegrityError as exc:
        raise conflict(exc) from exc
    return get_row(table, item_id)


@app.put("/api/nodes/{item_id}")
def update_node(item_id: int, body: NodeUpdate, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    prior = get_row("nodes", item_id)
    data = body.model_dump(exclude_unset=True)
    if "address" in data and data["address"] is not None:
        data["address"] = validate_host(data["address"])
    if "name" in data and data["name"] is not None:
        data["name"] = nonblank(data["name"], "Name")
    if "username" in data and data["username"] is not None:
        data["username"] = nonblank(data["username"], "SSH username")
    elif "username" in data:
        data["password_enc"] = None
    if "password" in data:
        password = data.pop("password")
        if password is None:
            data["password_enc"] = None
        elif password:
            if not data.get("username", prior["username"]):
                raise HTTPException(422, "SSH username is required when a password is supplied")
            data["password_enc"] = FERNET.encrypt(password.encode()).decode()
        # An empty password in the edit form intentionally preserves the old one.
    if any(key in data for key in ("address", "port", "username", "password_enc")):
        data.update(status="unknown", facts_json=None, last_check_at=None, last_error=None, last_check_mode=None)
    return update_fields("nodes", item_id, data,
                         {"name", "address", "port", "description", "username", "password_enc",
                          "status", "facts_json", "last_check_at", "last_error", "last_check_mode"},
                         {"username", "password_enc", "facts_json", "last_check_at", "last_error", "last_check_mode"})


@app.delete("/api/nodes/{item_id}")
def delete_node(item_id: int, _user: dict[str, Any] = Depends(operator)) -> dict[str, str]:
    try:
        with db() as conn:
            cursor = conn.execute("DELETE FROM nodes WHERE id=?", (item_id,))
            if cursor.rowcount == 0:
                raise HTTPException(404, "Not found")
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Node is used by a deployment") from exc
    return {"message": "Deleted"}


class NodeCheckError(Exception):
    """A public, credential-safe summary of an SSH or node check failure."""


def ssh_collect_facts(address: str, port: int, username: str, password: str) -> dict[str, Any]:
    """Verify a pinned SSH host key, authenticate, and run fixed read-only commands."""
    import paramiko

    known_hosts = os.getenv("SSH_KNOWN_HOSTS", "").strip()
    if not known_hosts or not Path(known_hosts).is_file():
        raise NodeCheckError("SSH known_hosts 未配置；请先核对并登记主机密钥")
    client = paramiko.SSHClient()
    try:
        client.load_host_keys(known_hosts)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(address, port=port, username=username, password=password,
                       timeout=4, auth_timeout=4, banner_timeout=4,
                       look_for_keys=False, allow_agent=False)
        script = """
printf 'HOSTNAME='; hostname 2>/dev/null
printf 'OS='; if [ -r /etc/os-release ]; then . /etc/os-release; printf '%s\\n' "$PRETTY_NAME"; else uname -s; fi
printf 'KERNEL='; uname -r 2>/dev/null
printf 'CPU_CORES='; getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null
printf 'MEMORY_KB='; awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>/dev/null | sed 's/^/GPU=/'
fi
"""
        _stdin, stdout, _stderr = client.exec_command("sh -c " + shlex.quote(script), timeout=8)
        output = stdout.read(65536).decode("utf-8", "replace")
        values: dict[str, str] = {}
        gpus: list[dict[str, Any]] = []
        for line in output.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if key == "GPU":
                parts = [part.strip() for part in value.split(",")]
                if len(parts) >= 3:
                    try:
                        memory_mb = int(parts[-2])
                    except ValueError:
                        memory_mb = None
                    gpus.append({"name": ",".join(parts[:-2]).strip(), "memory_mb": memory_mb,
                                 "driver_version": parts[-1]})
            else:
                values[key] = value
        if not values.get("HOSTNAME") or not values.get("KERNEL"):
            raise NodeCheckError("SSH 已连接，但节点事实采集失败")
        try:
            cpu_cores = int(values.get("CPU_CORES", "0")) or None
        except ValueError:
            cpu_cores = None
        try:
            memory_gb = round(int(values.get("MEMORY_KB", "0")) / 1048576, 1) or None
        except ValueError:
            memory_gb = None
        return {"hostname": values["HOSTNAME"], "os": values.get("OS") or None,
                "kernel": values["KERNEL"], "cpu_cores": cpu_cores,
                "memory_gb": memory_gb, "gpus": gpus}
    except paramiko.BadHostKeyException as exc:
        raise NodeCheckError("SSH 主机密钥与 known_hosts 不匹配") from exc
    except paramiko.AuthenticationException as exc:
        raise NodeCheckError("SSH 用户名或密码认证失败") from exc
    except paramiko.SSHException as exc:
        raise NodeCheckError("SSH 握手失败或主机密钥未被信任") from exc
    except (OSError, socket.timeout) as exc:
        raise NodeCheckError("SSH 连接或采集超时") from exc
    finally:
        client.close()


@app.post("/api/nodes/{item_id}/check")
def check_node(item_id: int, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    node = get_row("nodes", item_id)
    facts: dict[str, Any] | None = None
    if node["username"] and node["has_password"]:
        mode = "ssh"
        try:
            check_target_host(node["address"])
            with db() as conn:
                stored = conn.execute("SELECT password_enc FROM nodes WHERE id=?", (item_id,)).fetchone()["password_enc"]
            try:
                password = FERNET.decrypt(stored.encode()).decode()
            except InvalidToken as exc:
                raise NodeCheckError("SSH 凭证无法解密，请重新录入密码") from exc
            facts = ssh_collect_facts(node["address"], node["port"], node["username"], password)
            status, error = "online", None
        except NodeCheckError as exc:
            status, error = "offline", str(exc)
        except HTTPException:
            status, error = "offline", "节点地址未通过安全校验"
        except Exception:
            status, error = "offline", "SSH 检查失败，请核对连接配置"
    else:
        mode = "tcp"
        try:
            check_target_host(node["address"])
            with socket.create_connection((node["address"], node["port"]), timeout=3):
                status, error = "online", None
        except (OSError, HTTPException):
            status, error = "offline", "TCP 连接失败或节点地址未通过安全校验"
    with db() as conn:
        conn.execute("UPDATE nodes SET status=?,last_check_at=?,last_error=?,last_check_mode=?,facts_json=? WHERE id=?",
                     (status, utcnow(), error, mode, json.dumps(facts, ensure_ascii=False) if facts else None, item_id))
    return get_row("nodes", item_id)


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    model_id: str | None = Field(default=None, max_length=255)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="chat", max_length=80)
    source: str = Field(default="custom", max_length=120)


@app.get("/api/models")
def models(_user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return list_rows("models")


@app.post("/api/models", status_code=201)
def create_model(body: ModelCreate, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    model_identifier = nonblank(body.model_id if body.model_id is not None else body.name, "Model ID")
    try:
        with db() as conn:
            item_id = int(conn.execute("INSERT INTO models(name,model_id,description,category,source,status,created_at) VALUES (?,?,?,?,?,'catalog',?)",
                                       (nonblank(body.name, "Name"), model_identifier, body.description,
                                        nonblank(body.category, "Category"), nonblank(body.source, "Source"), utcnow())).lastrowid)
    except sqlite3.IntegrityError as exc:
        raise conflict(exc) from exc
    return get_row("models", item_id)


@app.get("/api/models/{item_id}")
def model_detail(item_id: int, _user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return get_row("models", item_id)


def validate_upstream_url(value: str, node_address: str) -> str:
    try:
        parsed = urlparse(value.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(422, "Invalid upstream URL") from exc
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(422, "Upstream URL must be an HTTP(S) base URL without credentials or query")
    if parsed.path.rstrip("/") not in {"", "/v1"}:
        raise HTTPException(422, "Upstream URL path must be empty or /v1")
    host = validate_host(host)
    if host != node_address.lower().rstrip("."):
        raise HTTPException(422, "Upstream host must match the selected node address")
    if port is not None and not 1 <= port <= 65535:
        raise HTTPException(422, "Invalid upstream port")
    return value.strip().rstrip("/")


class DeploymentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    model_id: int
    node_id: int
    upstream_url: str = Field(min_length=1, max_length=2048)
    upstream_api_key: str | None = Field(default=None, max_length=2048)


class DeploymentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    model_id: int | None = None
    node_id: int | None = None
    upstream_url: str | None = Field(default=None, min_length=1, max_length=2048)
    upstream_api_key: str | None = Field(default=None, max_length=2048)


@app.get("/api/deployments")
def deployments(_user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return list_rows("deployments")


@app.post("/api/deployments", status_code=201)
def create_deployment(body: DeploymentCreate, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    get_row("models", body.model_id)
    node = get_row("nodes", body.node_id)
    url = validate_upstream_url(body.upstream_url, node["address"])
    encrypted = FERNET.encrypt(body.upstream_api_key.encode()).decode() if body.upstream_api_key else None
    try:
        with db() as conn:
            item_id = int(conn.execute("""INSERT INTO deployments
              (name,model_id,node_id,upstream_url,upstream_api_key_enc,created_at)
              VALUES (?,?,?,?,?,?)""",
              (nonblank(body.name, "Name"), body.model_id, body.node_id, url, encrypted, utcnow())).lastrowid)
    except sqlite3.IntegrityError as exc:
        raise conflict(exc) from exc
    return get_row("deployments", item_id)


@app.get("/api/deployments/{item_id}")
def deployment_detail(item_id: int, _user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return get_row("deployments", item_id)


@app.put("/api/deployments/{item_id}")
def update_deployment(item_id: int, body: DeploymentUpdate, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    prior = get_row("deployments", item_id)
    data = body.model_dump(exclude_unset=True)
    node_id = data.get("node_id") or prior["node_id"]
    if "model_id" in data and data["model_id"] is not None:
        get_row("models", data["model_id"])
    node = get_row("nodes", node_id)
    url = data.get("upstream_url") or prior["upstream_url"]
    data["upstream_url"] = validate_upstream_url(url, node["address"])
    if "upstream_api_key" in data:
        secret = data.pop("upstream_api_key")
        data["upstream_api_key_enc"] = FERNET.encrypt(secret.encode()).decode() if secret else None
    if "name" in data and data["name"] is not None:
        data["name"] = nonblank(data["name"], "Name")
    data["status"] = "unknown"
    data["last_check_at"] = None
    data["last_error"] = None
    return update_fields("deployments", item_id, data, {"name", "model_id", "node_id", "upstream_url", "upstream_api_key_enc", "status", "last_check_at", "last_error"},
                         {"upstream_api_key_enc", "last_check_at", "last_error"})


@app.delete("/api/deployments/{item_id}")
def delete_deployment(item_id: int, _user: dict[str, Any] = Depends(operator)) -> dict[str, str]:
    try:
        with db() as conn:
            cursor = conn.execute("DELETE FROM deployments WHERE id=?", (item_id,))
            if cursor.rowcount == 0:
                raise HTTPException(404, "Not found")
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Deployment is used by a route") from exc
    return {"message": "Deleted"}


def check_target_host(host: str) -> None:
    approved = validate_host(host)
    # Never pre-check DNS and then let httpx resolve it again: that permits DNS
    # rebinding into localhost or cloud metadata addresses between the two steps.
    addresses = [ipaddress.ip_address("127.0.0.1")] if approved == "localhost" else [ipaddress.ip_address(approved)]
    for address in addresses:
        if address.is_unspecified or address.is_multicast or address.is_link_local or (address.is_reserved and not (address.is_loopback and ALLOW_LOOPBACK)):
            raise HTTPException(403, "Upstream address is not allowed")
        if (address.is_loopback or str(address) == "169.254.169.254") and not ALLOW_LOOPBACK:
            raise HTTPException(403, "Loopback upstream requires explicit development opt-in")


def check_upstream_target(url: str) -> None:
    host = urlparse(url).hostname
    if not host:
        raise HTTPException(422, "Invalid upstream URL")
    check_target_host(host)


def upstream_path(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    return base + suffix if base.endswith("/v1") else base + "/v1" + suffix


@app.post("/api/deployments/{item_id}/check")
async def check_deployment(item_id: int, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    deployment = get_row("deployments", item_id)
    try:
        check_upstream_target(deployment["upstream_url"])
        with db() as conn:
            row = conn.execute("SELECT upstream_api_key_enc FROM deployments WHERE id=?", (item_id,)).fetchone()
        headers = {"Authorization": "Bearer " + FERNET.decrypt(row["upstream_api_key_enc"].encode()).decode()} if row["upstream_api_key_enc"] else {}
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            upstream = await client.get(upstream_path(deployment["upstream_url"], "/models"), headers=headers)
        valid_list = False
        if upstream.status_code == 200:
            try:
                valid_list = isinstance(upstream.json().get("data"), list)
            except (ValueError, AttributeError):
                pass
        status = "running" if valid_list else "unavailable"
        error = None if status == "running" else f"Upstream /v1/models returned HTTP {upstream.status_code} or an invalid model list"
    except (httpx.HTTPError, HTTPException, OSError) as exc:
        status, error = "unavailable", str(exc)[:500]
    with db() as conn:
        conn.execute("UPDATE deployments SET status=?,last_check_at=?,last_error=? WHERE id=?",
                     (status, utcnow(), error, item_id))
    return get_row("deployments", item_id)


class RouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    model_alias: str = Field(min_length=1, max_length=255)
    deployment_id: int
    status: Literal["active", "disabled"] = "active"


class RouteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    model_alias: str | None = Field(default=None, min_length=1, max_length=255)
    deployment_id: int | None = None
    status: Literal["active", "disabled"] | None = None


@app.get("/api/routes")
def routes(_user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return list_rows("routes")


@app.post("/api/routes", status_code=201)
def create_route(body: RouteCreate, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    get_row("deployments", body.deployment_id)
    alias = nonblank(body.model_alias, "Model alias")
    try:
        with db() as conn:
            item_id = int(conn.execute("INSERT INTO routes(name,model_alias,deployment_id,status,created_at) VALUES (?,?,?,?,?)",
                                       (nonblank(body.name, "Name"), alias, body.deployment_id, body.status, utcnow())).lastrowid)
    except sqlite3.IntegrityError as exc:
        raise conflict(exc) from exc
    return get_row("routes", item_id)


@app.get("/api/routes/{item_id}")
def route_detail(item_id: int, _user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return get_row("routes", item_id)


@app.put("/api/routes/{item_id}")
def update_route(item_id: int, body: RouteUpdate, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if "deployment_id" in data and data["deployment_id"] is not None:
        get_row("deployments", data["deployment_id"])
    for key in ("name", "model_alias"):
        if key in data and data[key] is not None:
            data[key] = nonblank(data[key], "Name" if key == "name" else "Model alias")
    return update_fields("routes", item_id, data, {"name", "model_alias", "deployment_id", "status"})


@app.delete("/api/routes/{item_id}")
def delete_route(item_id: int, _user: dict[str, Any] = Depends(operator)) -> dict[str, str]:
    with db() as conn:
        cursor = conn.execute("DELETE FROM routes WHERE id=?", (item_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, "Not found")
    return {"message": "Deleted"}


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def api_key_hash(secret: str) -> str:
    return hashlib.sha256(("api-key:" + SECRET_KEY + secret).encode()).hexdigest()


@app.get("/api/api-keys")
def api_keys(_user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return list_rows("api_keys")


@app.post("/api/api-keys", status_code=201)
def create_api_key(body: APIKeyCreate, _user: dict[str, Any] = Depends(operator)) -> dict[str, Any]:
    secret = "sk-nov-" + secrets.token_urlsafe(32)
    with db() as conn:
        item_id = int(conn.execute("INSERT INTO api_keys(name,prefix,key_hash,created_at) VALUES (?,?,?,?)",
                                   (nonblank(body.name, "Name"), secret[:14], api_key_hash(secret), utcnow())).lastrowid)
    return {**get_row("api_keys", item_id), "secret": secret}


@app.delete("/api/api-keys/{item_id}")
def delete_api_key(item_id: int, _user: dict[str, Any] = Depends(operator)) -> dict[str, str]:
    with db() as conn:
        cursor = conn.execute("DELETE FROM api_keys WHERE id=?", (item_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, "Not found")
    return {"message": "Deleted"}


def bearer_key(request: Request) -> dict[str, Any]:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "API key required", headers={"WWW-Authenticate": "Bearer"})
    secret = authorization[7:].strip()
    if not secret.startswith("sk-nov-"):
        raise HTTPException(401, "Invalid API key")
    with db() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE key_hash=? AND status='active'", (api_key_hash(secret),)).fetchone()
    if row is None:
        raise HTTPException(401, "Invalid API key")
    return rowdict(row, exclude=("key_hash",)) or {}


class RoleBody(BaseModel):
    role: Literal["admin", "operator", "viewer"]


@app.get("/api/users")
def users(_user: dict[str, Any] = Depends(admin)) -> list[dict[str, Any]]:
    return list_rows("users")


@app.put("/api/users/{item_id}/role")
def update_user_role(item_id: int, body: RoleBody, _user: dict[str, Any] = Depends(admin)) -> dict[str, Any]:
    target = get_row("users", item_id)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if target["role"] == "admin" and body.role != "admin":
            count = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
            if count <= 1:
                raise HTTPException(409, "Cannot remove the last administrator")
        conn.execute("UPDATE users SET role=? WHERE id=?", (body.role, item_id))
    return get_row("users", item_id)


class SettingsUpdate(BaseModel):
    site_name: str | None = Field(default=None, min_length=1, max_length=120)
    allow_registration: bool | None = None


def read_settings() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute("SELECT key,value FROM settings").fetchall()
    raw = {row["key"]: row["value"] for row in rows}
    return {"site_name": raw.get("site_name", "Noveris AI"),
            "allow_registration": raw.get("allow_registration", "true") == "true"}


@app.get("/api/settings/public")
def public_settings() -> dict[str, Any]:
    return read_settings()


@app.get("/api/settings")
def settings(_user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return read_settings()


@app.put("/api/settings")
def update_settings(body: SettingsUpdate, _user: dict[str, Any] = Depends(admin)) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "No settings to update")
    with db() as conn:
        for key, value in data.items():
            if value is None:
                continue
            conn.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, str(value).lower() if isinstance(value, bool) else nonblank(value, "Site name")))
    return read_settings()


@app.get("/api/dashboard")
def dashboard(_user: dict[str, Any] = Depends(current_user)) -> dict[str, int]:
    with db() as conn:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("nodes", "models", "deployments", "routes", "api_keys")}
        counts["healthy_nodes"] = conn.execute("SELECT COUNT(*) FROM nodes WHERE status='online'").fetchone()[0]
        counts["running_deployments"] = conn.execute("SELECT COUNT(*) FROM deployments WHERE status='running'").fetchone()[0]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        counts["recent_requests"] = conn.execute("SELECT COUNT(*) FROM usage_events WHERE created_at>=?", (cutoff,)).fetchone()[0]
    return counts


def route_target(*, route_id: int | None = None, alias: str | None = None) -> dict[str, Any]:
    with db() as conn:
        query = """SELECT routes.id AS route_id, routes.model_alias, routes.status AS route_status,
                   deployments.id AS deployment_id, deployments.upstream_url,
                   deployments.upstream_api_key_enc, models.model_id AS upstream_model_id
                   FROM routes JOIN deployments ON deployments.id=routes.deployment_id
                   JOIN models ON models.id=deployments.model_id WHERE """
        if route_id is not None:
            row = conn.execute(query + "routes.id=?", (route_id,)).fetchone()
        else:
            row = conn.execute(query + "routes.model_alias=?", (alias,)).fetchone()
    if row is None:
        raise HTTPException(404, "Route not found")
    if row["route_status"] != "active":
        raise HTTPException(503, "Route is disabled")
    return rowdict(row) or {}


def record_usage(route_id: int, api_key_id: int | None, status_code: int, started_at: float) -> None:
    with db() as conn:
        conn.execute("INSERT INTO usage_events(route_id,api_key_id,status_code,latency_ms,created_at) VALUES (?,?,?,?,?)",
                     (route_id, api_key_id, status_code, int((time.monotonic() - started_at) * 1000), utcnow()))


def upstream_headers(target: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if target["upstream_api_key_enc"]:
        headers["Authorization"] = "Bearer " + FERNET.decrypt(target["upstream_api_key_enc"].encode()).decode()
    return headers


async def forward_chat(target: dict[str, Any], payload: dict[str, Any], api_key_id: int | None = None) -> Response:
    check_upstream_target(target["upstream_url"])
    body = dict(payload)
    body["model"] = target["upstream_model_id"]
    url = upstream_path(target["upstream_url"], "/chat/completions")
    started = time.monotonic()
    client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5), follow_redirects=False, trust_env=False)
    stream = body.get("stream") is True
    try:
        if stream:
            request = client.build_request("POST", url, json=body, headers=upstream_headers(target))
            upstream = await client.send(request, stream=True)
            record_usage(target["route_id"], api_key_id, upstream.status_code, started)

            async def chunks() -> Iterator[bytes]:
                try:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            return StreamingResponse(chunks(), status_code=upstream.status_code,
                                     media_type=upstream.headers.get("content-type", "text/event-stream"),
                                     headers={"Cache-Control": "no-cache"})
        upstream = await client.post(url, json=body, headers=upstream_headers(target))
        record_usage(target["route_id"], api_key_id, upstream.status_code, started)
        return Response(content=upstream.content, status_code=upstream.status_code,
                        media_type=upstream.headers.get("content-type", "application/json"))
    except httpx.TimeoutException as exc:
        record_usage(target["route_id"], api_key_id, 504, started)
        raise HTTPException(504, "Upstream timed out") from exc
    except httpx.HTTPError as exc:
        record_usage(target["route_id"], api_key_id, 502, started)
        raise HTTPException(502, "Upstream connection failed") from exc
    finally:
        if not stream or "upstream" not in locals():
            await client.aclose()


class TestBody(BaseModel):
    route_id: int
    prompt: str = Field(min_length=1, max_length=10000)


@app.post("/api/test")
async def test_route(body: TestBody, _user: dict[str, Any] = Depends(operator)) -> Response:
    target = route_target(route_id=body.route_id)
    return await forward_chat(target, {"model": target["model_alias"],
                                       "messages": [{"role": "user", "content": body.prompt}], "stream": False})


@app.get("/v1/models")
def gateway_models(_api_key: dict[str, Any] = Depends(bearer_key)) -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute("SELECT model_alias,created_at FROM routes WHERE status='active' ORDER BY model_alias").fetchall()
    return {"object": "list", "data": [
        {"id": row["model_alias"], "object": "model", "created": int(datetime.fromisoformat(row["created_at"]).timestamp()), "owned_by": "noveris"}
        for row in rows]}


@app.post("/v1/chat/completions")
async def gateway_chat(request: Request, api_key: dict[str, Any] = Depends(bearer_key)) -> Response:
    raw = await request.body()
    if len(raw) > MAX_PROXY_BODY:
        raise HTTPException(413, "Request body is too large")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str) or not isinstance(payload.get("messages"), list):
        raise HTTPException(422, "model and messages are required")
    target = route_target(alias=payload["model"])
    return await forward_chat(target, payload, int(api_key["id"]))


# An optional production build can share this origin with the API. Keep this
# last so existing API, gateway, and documentation routes retain precedence.
frontend_dist_raw = os.getenv("FRONTEND_DIST", "").strip()
if frontend_dist_raw:
    frontend_dist = Path(frontend_dist_raw).expanduser().resolve()
    frontend_index = (frontend_dist / "index.html").resolve()
    frontend_assets = frontend_dist / "assets"
    if not frontend_index.is_relative_to(frontend_dist) or not frontend_index.is_file() or not frontend_assets.is_dir():
        raise RuntimeError("FRONTEND_DIST must contain index.html and an assets directory")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def serve_frontend(full_path: str) -> FileResponse:
        # Missing API/gateway endpoints must never become HTML.
        first_segment = full_path.split("/", 1)[0]
        if first_segment in {"api", "v1"}:
            raise HTTPException(404, "Not Found")
        requested = (frontend_dist / full_path).resolve()
        if not requested.is_relative_to(frontend_dist):
            raise HTTPException(404, "Not Found")
        relative_parts = requested.relative_to(frontend_dist).parts
        if any(part.startswith(".") for part in relative_parts):
            raise HTTPException(404, "Not Found")
        if requested.is_file():
            return FileResponse(requested)
        # A missing hashed asset or other file must not return index.html.
        if first_segment == "assets" or Path(full_path).suffix:
            raise HTTPException(404, "Not Found")
        return FileResponse(frontend_index)
