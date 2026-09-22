"""
stackzeta-notify-bridge

Relays Home-Assistant-triggered MQTT notifications to the StackChan over a
small custom WebSocket (kept separate from the xiaozhi voice connection).
Optional images are fetched, resized to fit the device's screen, and served
back over plain HTTP so the device can fetch+decode them itself.

The device (not this service) decides when it's safe to actually display a
queued notification — see main/stackchan/notify/notify_client.cpp in the
firmware — so this service is a thin, stateless-per-notification relay.
"""

import asyncio
import io
import json
import logging
import os
import uuid
from pathlib import Path

import aiohttp
import paho.mqtt.client as mqtt
from aiohttp import web
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notify-bridge")

MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME") or None
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD") or None
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "stackchan/notify")

HA_BASE_URL = os.environ.get("HA_BASE_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8090"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", f"http://localhost:{LISTEN_PORT}")

IMAGE_MAX_SIZE = (320, 240)
IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", "/data/images"))
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
MAX_STORED_IMAGES = 50

PIPER_URL = os.environ.get("PIPER_URL", "http://piper-tts:5000/synthesize")
AUDIO_DIR = Path(os.environ.get("AUDIO_DIR", "/data/audio"))
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
MAX_STORED_AUDIO = 50


class DeviceHub:
    """Tracks the single connected StackChan (v0.1: one device)."""

    def __init__(self) -> None:
        self.ws: web.WebSocketResponse | None = None

    async def register(self, ws: web.WebSocketResponse) -> None:
        if self.ws is not None:
            log.warning("a new device connection replaced an existing one")
        self.ws = ws
        log.info("device connected")

    def unregister(self, ws: web.WebSocketResponse) -> None:
        if self.ws is ws:
            self.ws = None
            log.info("device disconnected")

    async def send(self, message: dict) -> bool:
        if self.ws is None:
            log.warning("no device connected, dropping notification: %s", message.get("title"))
            return False
        try:
            await self.ws.send_str(json.dumps(message))
            log.info("sent to device: %s", message)
            return True
        except Exception:
            log.exception("failed to send notification to device")
            self.ws = None
            return False


hub = DeviceHub()


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    # No aiohttp-driven heartbeat here — the device sends its own periodic
    # {"type":"ping"} application-level keepalive instead, which it also
    # uses to actively detect a dead connection (rather than relying on
    # TCP/WS-layer close detection, which was unreliable in practice).
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await hub.register(ws)
    try:
        async for _ in ws:
            pass
    finally:
        hub.unregister(ws)
    return ws


def _prune_old_images() -> None:
    files = sorted(IMAGES_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    while len(files) > MAX_STORED_IMAGES:
        oldest = files.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass


async def fetch_and_prepare_image(url: str) -> str | None:
    headers = {}
    if HA_BASE_URL and url.startswith(HA_BASE_URL) and HA_TOKEN:
        headers["Authorization"] = f"Bearer {HA_TOKEN}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                raw = await resp.read()
    except Exception:
        log.exception("failed to fetch notification image: %s", url)
        return None

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail(IMAGE_MAX_SIZE)
        filename = f"{uuid.uuid4().hex}.jpg"
        img.save(IMAGES_DIR / filename, "JPEG", quality=85)
        _prune_old_images()
        return filename
    except Exception:
        log.exception("failed to process notification image")
        return None


async def images_handler(request: web.Request) -> web.StreamResponse:
    filename = request.match_info["filename"]
    if "/" in filename or ".." in filename:
        raise web.HTTPBadRequest()
    path = IMAGES_DIR / filename
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


def _prune_old_audio() -> None:
    files = sorted(AUDIO_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    while len(files) > MAX_STORED_AUDIO:
        oldest = files.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass


# Device output codec: mono, 16-bit, 24kHz (see
# firmware/main/hal/board/config.h AUDIO_OUTPUT_SAMPLE_RATE). Notification
# audio used to go through the firmware's Ogg/Opus playback pipeline
# (Application::PlaySound(), same path as the built-in chimes), but that
# vendored decoder reliably corrupted the heap on this dynamically
# synthesized speech (reproduced repeatedly during testing — see notify
# client history). The firmware now parses this WAV directly and writes the
# PCM straight to the codec, bypassing that decoder entirely, so we
# transcode to exactly the format it expects instead.
NOTIFICATION_AUDIO_SAMPLE_RATE = 24000


async def synthesize_notification_audio(text: str) -> str | None:
    """Synthesizes `text` via Piper, then resamples to mono/16-bit/24kHz PCM
    WAV for the firmware to play directly."""
    if not text.strip():
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PIPER_URL, json={"text": text}, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                resp.raise_for_status()
                wav_bytes = await resp.read()
    except Exception:
        log.exception("failed to synthesize notification audio")
        return None

    token = uuid.uuid4().hex
    raw_path = AUDIO_DIR / f"{token}.raw.wav"
    out_path = AUDIO_DIR / f"{token}.wav"
    raw_path.write_bytes(wav_bytes)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(raw_path),
            "-ac",
            "1",
            "-ar",
            str(NOTIFICATION_AUDIO_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(out_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        returncode = await proc.wait()
    except Exception:
        log.exception("ffmpeg resample failed")
        returncode = -1
    finally:
        raw_path.unlink(missing_ok=True)

    if returncode != 0 or not out_path.is_file():
        log.error("ffmpeg produced no output for notification audio (rc=%s)", returncode)
        out_path.unlink(missing_ok=True)
        return None

    _prune_old_audio()
    return out_path.name


async def audio_handler(request: web.Request) -> web.StreamResponse:
    filename = request.match_info["filename"]
    if "/" in filename or ".." in filename:
        raise web.HTTPBadRequest()
    path = AUDIO_DIR / filename
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "device_connected": hub.ws is not None})


async def handle_mqtt_notification(payload: dict) -> None:
    log.info("received MQTT notification: %s", payload)
    try:
        message = {
            "type": "notification",
            "title": str(payload.get("title", "")),
            "body": str(payload.get("body", "")),
            # Strict boolean on purpose: a quoted string such as "false"
            # must not accidentally become an interrupting notification.
            "urgent": payload.get("urgent") is True,
        }

        image_url = payload.get("image_url")
        if image_url:
            filename = await fetch_and_prepare_image(str(image_url))
            if filename:
                message["image_url"] = f"{PUBLIC_BASE_URL}/images/{filename}"

        speak = payload.get("speak", True)
        if speak:
            announce_text = " ".join(p for p in (message["title"], message["body"]) if p)
            audio_filename = await synthesize_notification_audio(announce_text)
            if audio_filename:
                message["audio_url"] = f"{PUBLIC_BASE_URL}/audio/{audio_filename}"

        await hub.send(message)
    except Exception:
        log.exception("unhandled error while processing MQTT notification")


def start_mqtt(loop: asyncio.AbstractEventLoop) -> mqtt.Client:
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info("MQTT connected, subscribing to %s", MQTT_TOPIC)
            client.subscribe(MQTT_TOPIC)
        else:
            log.error("MQTT connect failed, rc=%s", rc)

    def on_message(client, userdata, msg):
        log.info("MQTT message on %s (%d bytes)", msg.topic, len(msg.payload))
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("ignoring non-JSON MQTT payload on %s", msg.topic)
            return

        future = asyncio.run_coroutine_threadsafe(handle_mqtt_notification(payload), loop)

        def _log_if_failed(fut):
            exc = fut.exception()
            if exc is not None:
                log.error("handle_mqtt_notification raised: %r", exc)

        future.add_done_callback(_log_if_failed)

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    return client


async def main() -> None:
    loop = asyncio.get_running_loop()

    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/images/{filename}", images_handler)
    app.router.add_get("/audio/{filename}", audio_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", LISTEN_PORT)
    await site.start()
    log.info("notify-bridge listening on :%d (public base: %s)", LISTEN_PORT, PUBLIC_BASE_URL)

    mqtt_client = start_mqtt(loop)
    try:
        await asyncio.Event().wait()
    finally:
        mqtt_client.loop_stop()


if __name__ == "__main__":
    asyncio.run(main())
