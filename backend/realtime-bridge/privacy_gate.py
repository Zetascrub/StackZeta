"""Minimal authenticated read of the desktop control panel's privacy state."""

import hmac
import json
import os
from pathlib import Path

from aiohttp import web


STATE_FILE = Path(os.getenv("PRIVACY_CONFIG_FILE", "/run/stackzeta/config.json"))
TOKEN_FILE = Path(os.getenv("PRIVACY_TOKEN_FILE", "/run/secrets/privacy_token"))


def token() -> str:
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError:
        return os.getenv("PRIVACY_TOKEN", "")


async def privacy(request: web.Request) -> web.Response:
    current_token = token()
    if not current_token or not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {current_token}"):
        raise web.HTTPUnauthorized()
    try:
        value = json.loads(STATE_FILE.read_text())["device"]["privacy_mode"]
    except (OSError, ValueError, KeyError, TypeError):
        raise web.HTTPServiceUnavailable(text="privacy state unavailable")
    if not isinstance(value, bool):
        raise web.HTTPServiceUnavailable(text="privacy state invalid")
    return web.json_response({"privacy_mode": value})


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/privacy", privacy)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=8011)
