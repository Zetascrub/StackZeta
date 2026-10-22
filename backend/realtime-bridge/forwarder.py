"""Temporary LAN forwarder for a firmware-free Realtime device pilot.

The device obtains this URL from the existing OTA server. The forwarder adds
the bridge credential and selects Realtime or the unchanged desktop backend.
"""

import asyncio
import hmac
import logging
import os
from pathlib import Path

import aiohttp
from aiohttp import web


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stackzeta-forwarder")

PRIMARY_URL = os.environ["PRIMARY_WS_URL"]
FALLBACK_URL = os.environ["FALLBACK_WS_URL"]
DEVICE_ID = os.environ["DEVICE_ID"].lower()
VOICE_ROUTE = os.getenv("VOICE_ROUTE", "realtime")
TOKEN_FILE = Path(os.getenv("DEVICE_TOKEN_FILE", "/run/secrets/device_token"))


async def relay(source, destination) -> None:
    async for message in source:
        if message.type == aiohttp.WSMsgType.TEXT:
            await destination.send_str(message.data)
        elif message.type == aiohttp.WSMsgType.BINARY:
            await destination.send_bytes(message.data)
        else:
            return


async def voice(request: web.Request) -> web.WebSocketResponse:
    if not hmac.compare_digest(request.headers.get("Device-Id", "").lower(), DEVICE_ID):
        raise web.HTTPUnauthorized()
    try:
        token = TOKEN_FILE.read_text().strip()
    except OSError:
        raise web.HTTPServiceUnavailable(text="bridge credential unavailable")
    if not token:
        raise web.HTTPServiceUnavailable(text="bridge credential unavailable")

    headers = {key: request.headers[key] for key in ("Device-Id", "Client-Id", "Protocol-Version")
               if key in request.headers}
    fallback_auth = request.headers.get("Authorization")
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=3)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async def connect_desktop():
            fallback_headers = {**headers}
            if fallback_auth:
                fallback_headers["Authorization"] = fallback_auth
            return await client.ws_connect(
                FALLBACK_URL, headers=fallback_headers, heartbeat=None,
                timeout=aiohttp.ClientWSTimeout(ws_close=6),
            )

        if VOICE_ROUTE == "desktop":
            try:
                upstream = await connect_desktop()
                route = "desktop"
            except (aiohttp.ClientError, asyncio.TimeoutError):
                raise web.HTTPServiceUnavailable(text="desktop voice backend unavailable")
        else:
            try:
                upstream = await client.ws_connect(
                    PRIMARY_URL, headers={**headers, "Authorization": f"Bearer {token}"},
                    heartbeat=None, timeout=aiohttp.ClientWSTimeout(ws_close=6),
                )
                route = "realtime"
            except (aiohttp.ClientError, asyncio.TimeoutError):
                try:
                    upstream = await connect_desktop()
                    route = "desktop"
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    raise web.HTTPServiceUnavailable(text="voice backends unavailable")

        device = web.WebSocketResponse(heartbeat=None, max_msg_size=1024 * 1024)
        await device.prepare(request)
        log.info("voice route=%s", route)
        async with upstream:
            tasks = [asyncio.create_task(relay(device, upstream)),
                     asyncio.create_task(relay(upstream, device))]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        await device.close()
        return device


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/xiaozhi/v1/", voice)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=8012)
