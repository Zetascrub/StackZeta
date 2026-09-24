"""Control-panel login and write-only secret storage.

Login: a single panel password, from CONTROL_PANEL_PASSWORD in .env, or else
generated on first start (logged once) and stored as a scrypt hash. Sessions
are random tokens in an HttpOnly, SameSite=Strict cookie, held in memory, so
a restart signs everyone out.

Request checks for panel routes (the device's /ws, /images, /audio and
/health stay open, since the firmware has no credentials):
- Host header must be one of the panel's own names (DNS-rebinding guard);
  extra names go in PANEL_ALLOWED_HOSTS.
- State-changing requests must not carry a foreign Origin (CSRF guard).

Secrets (API keys, tokens, MQTT credentials) are write-only: the API reports
only whether each is set and where from, never the value. They live in
secrets.json (mode 600) on the state volume, which the voice server also
mounts read-only to pick up the OpenAI key and the Home Assistant token.
Values from .env remain as a fallback, so existing setups keep working.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets as pysecrets
import time
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web

log = logging.getLogger("notify-bridge")

SESSION_COOKIE = "stackzeta_session"
SESSION_SECONDS = 7 * 24 * 3600

# name -> fallback environment variable (None: panel only)
SECRET_FIELDS = {
    "openai_api_key": None,
    "ha_token": "HA_TOKEN",
    "mqtt_username": "MQTT_USERNAME",
    "mqtt_password": "MQTT_PASSWORD",
}

# Paths the device uses; everything else requires a panel session.
DEVICE_PATH_PREFIXES = ("/ws", "/images/", "/audio/", "/health")
PUBLIC_PANEL_PATHS = ("/api/login",)


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def _host_only(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value.split("]")[0].lstrip("[")
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class PanelSecurity:
    def __init__(self, state_dir: Path, public_base_url: str) -> None:
        self._auth_path = state_dir / "panel_auth.json"
        self._secrets_path = state_dir / "secrets.json"
        self._sessions: dict[str, float] = {}
        self._secrets = self._load_secrets()
        self._password_hash, self._salt = self._load_or_create_password()

        hosts = {"localhost", "127.0.0.1", "::1"}
        public_host = urlparse(public_base_url).hostname
        if public_host:
            hosts.add(public_host.lower())
        for extra in os.environ.get("PANEL_ALLOWED_HOSTS", "").split(","):
            if extra.strip():
                hosts.add(_host_only(extra))
        self.allowed_hosts = hosts

    # ---- password -------------------------------------------------------

    def _load_or_create_password(self) -> tuple[str, bytes]:
        env_password = os.environ.get("CONTROL_PANEL_PASSWORD", "")
        if env_password:
            salt = pysecrets.token_bytes(16)
            return _hash_password(env_password, salt), salt
        try:
            stored = json.loads(self._auth_path.read_text())
            return stored["hash"], bytes.fromhex(stored["salt"])
        except (OSError, ValueError, KeyError):
            pass
        password = pysecrets.token_urlsafe(12)
        salt = pysecrets.token_bytes(16)
        password_hash = _hash_password(password, salt)
        self._write_private(self._auth_path, {"hash": password_hash, "salt": salt.hex()})
        log.warning(
            "control panel password generated (shown once, change it in the Keys tab "
            "or set CONTROL_PANEL_PASSWORD in .env): %s",
            password,
        )
        return password_hash, salt

    def check_password(self, password: str) -> bool:
        return hmac.compare_digest(_hash_password(password, self._salt), self._password_hash)

    def set_password(self, password: str) -> None:
        if os.environ.get("CONTROL_PANEL_PASSWORD"):
            raise ValueError("password is set by CONTROL_PANEL_PASSWORD in .env; change it there")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        salt = pysecrets.token_bytes(16)
        self._password_hash, self._salt = _hash_password(password, salt), salt
        self._write_private(self._auth_path, {"hash": self._password_hash, "salt": salt.hex()})
        self._sessions.clear()

    # ---- sessions -------------------------------------------------------

    def new_session(self) -> str:
        token = pysecrets.token_urlsafe(32)
        self._sessions[token] = time.time() + SESSION_SECONDS
        return token

    def end_session(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def session_valid(self, token: str | None) -> bool:
        expiry = self._sessions.get(token or "")
        if expiry is None:
            return False
        if expiry < time.time():
            self._sessions.pop(token, None)
            return False
        return True

    # ---- secrets --------------------------------------------------------

    def _load_secrets(self) -> dict:
        try:
            data = json.loads(self._secrets_path.read_text())
            return {k: v for k, v in data.items() if k in SECRET_FIELDS and isinstance(v, str)}
        except (OSError, ValueError):
            return {}

    def secret(self, name: str) -> str:
        value = self._secrets.get(name, "")
        if value:
            return value
        env_name = SECRET_FIELDS[name]
        return os.environ.get(env_name, "") if env_name else ""

    def secret_status(self) -> dict:
        status = {}
        for name, env_name in SECRET_FIELDS.items():
            if self._secrets.get(name):
                source = "panel"
            elif env_name and os.environ.get(env_name):
                source = ".env"
            else:
                source = None
            status[name] = {"set": source is not None, "source": source}
        return status

    def update_secrets(self, changes: dict) -> set[str]:
        """Applies {name: value}; an empty string clears the panel value."""
        changed = set()
        for name, value in changes.items():
            if name not in SECRET_FIELDS or not isinstance(value, str):
                raise ValueError(f"unknown secret: {name}")
            value = value.strip()
            if len(value) > 4096:
                raise ValueError(f"{name} is too long")
            if value:
                self._secrets[name] = value
            else:
                self._secrets.pop(name, None)
            changed.add(name)
        self._write_private(self._secrets_path, self._secrets)
        return changed

    @staticmethod
    def _write_private(path: Path, value) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(value, f)
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    # ---- middleware -----------------------------------------------------

    def middleware(self):
        @web.middleware
        async def check(request: web.Request, handler):
            path = request.path
            if path.startswith(DEVICE_PATH_PREFIXES):
                return await handler(request)

            if _host_only(request.host or "") not in self.allowed_hosts:
                raise web.HTTPMisdirectedRequest(
                    text=f"Unknown host '{request.host}'. Add it to PANEL_ALLOWED_HOSTS in .env."
                )
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("Origin")
                if origin and _host_only(urlparse(origin).netloc) != _host_only(request.host or ""):
                    raise web.HTTPForbidden(text="cross-origin request refused")

            if path in PUBLIC_PANEL_PATHS or self.session_valid(request.cookies.get(SESSION_COOKIE)):
                return await handler(request)
            if path.startswith("/api/"):
                raise web.HTTPUnauthorized(text="sign in required")
            return web.FileResponse(Path(__file__).with_name("login.html"))

        return check

    # ---- routes ---------------------------------------------------------

    async def login_handler(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            password = str(body.get("password", ""))
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest(text="expected JSON with a password")
        if not self.check_password(password):
            await asyncio.sleep(1)  # slow down guessing
            raise web.HTTPUnauthorized(text="wrong password")
        response = web.json_response({"ok": True})
        response.set_cookie(
            SESSION_COOKIE, self.new_session(), max_age=SESSION_SECONDS,
            httponly=True, samesite="Strict", path="/",
        )
        return response

    async def logout_handler(self, request: web.Request) -> web.Response:
        self.end_session(request.cookies.get(SESSION_COOKIE))
        response = web.json_response({"ok": True})
        response.del_cookie(SESSION_COOKIE, path="/")
        return response

    async def password_handler(self, request: web.Request) -> web.Response:
        body = await request.json()
        if not self.check_password(str(body.get("current", ""))):
            await asyncio.sleep(1)
            raise web.HTTPForbidden(text="current password is wrong")
        try:
            self.set_password(str(body.get("new", "")))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response({"ok": True})
