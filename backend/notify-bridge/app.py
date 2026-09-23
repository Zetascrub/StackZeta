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
import ipaddress
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

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

STATE_DIR = Path(os.environ.get("STATE_DIR", "/data/state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = STATE_DIR / "config.json"
HISTORY_PATH = STATE_DIR / "history.json"
CONTROL_HTML_PATH = Path(__file__).with_name("control.html")
MAX_HISTORY = 100

DEFAULT_CONFIG = {
    "location": {
        "name": "Home",
        "latitude": None,
        "longitude": None,
        "timezone": "Europe/London",
        "weather_entity": "weather.home",
    },
    "personality": {
        "activity": "balanced",
        "greetings_enabled": True,
        "greeting_cooldown_minutes": 120,
    },
    "device": {
        "volume": 70,
        "brightness": 80,
        "standby_timeout_seconds": 300,
        "standby_screen_off": True,
        "standby_leds_off": True,
        "standby_park_head": True,
        "sleep_timeout_seconds": 600,
        "privacy_mode": False,
    },
    "network_policy": {
        "enabled": True,
        "allowed_hosts": ["192.168.8.10", "192.168.8.135", "api.openai.com", "pool.ntp.org"],
        "blocked_hosts": [
            "open.bigmodel.cn", "whois.pconline.com.cn", "cn.pool.ntp.org",
            "api.tenclass.net", "47.113.125.164", "ezdata2.m5stack.com",
            "uiflow2.m5stack.com",
        ],
    },
    "notifications": {
        "dnd": False,
        "quiet_hours_enabled": False,
        "quiet_start": "22:00",
        "quiet_end": "07:00",
        "categories": {
            "general": {"color": "#00B8D4", "speak": True, "urgent": False},
            "security": {"color": "#FF5A36", "speak": True, "urgent": True},
            "doorbell": {"color": "#FFAA24", "speak": True, "urgent": True},
            "reminder": {"color": "#7B8CFF", "speak": True, "urgent": False},
            "household": {"color": "#2ECF73", "speak": True, "urgent": False},
        },
    },
    "led": {
        "idle": "#00141D",
        "listening": "#00E5F0",
        "speaking": "#0A799B",
        "notification": "#FFAA24",
        "urgent": "#FF5A36",
        "dnd": "#7B3FB2",
        "privacy": "#FF0000",
        "offline": "#303840",
    },
}


def _deep_merge(base: dict, update: dict) -> dict:
    result = deepcopy(base)
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return deepcopy(fallback)


def _atomic_write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


config = _deep_merge(DEFAULT_CONFIG, _load_json(CONFIG_PATH, {}))
history: list[dict] = _load_json(HISTORY_PATH, [])


def _public_config() -> dict:
    return deepcopy(config)


def _validate_config(candidate: dict) -> dict:
    merged = _deep_merge(DEFAULT_CONFIG, candidate)
    location = merged["location"]
    for key, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
        value = location.get(key)
        if value in (None, ""):
            location[key] = None
        else:
            value = float(value)
            if not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
            location[key] = value
    ZoneInfo(str(location["timezone"]))

    personality = merged["personality"]
    if personality["activity"] not in {"quiet", "balanced", "lively"}:
        raise ValueError("activity must be quiet, balanced, or lively")
    personality["greeting_cooldown_minutes"] = max(
        5, min(1440, int(personality["greeting_cooldown_minutes"]))
    )

    device = merged["device"]
    device["volume"] = max(0, min(100, int(device["volume"])))
    device["brightness"] = max(5, min(100, int(device["brightness"])))
    device["standby_timeout_seconds"] = max(
        0, min(86400, int(device["standby_timeout_seconds"]))
    )
    device["sleep_timeout_seconds"] = max(30, min(86400, int(device["sleep_timeout_seconds"])))

    network_policy = merged["network_policy"]
    network_policy["enabled"] = bool(network_policy.get("enabled", True))
    for key in ("allowed_hosts", "blocked_hosts"):
        values = network_policy.get(key, [])
        if not isinstance(values, list):
            raise ValueError(f"network_policy.{key} must be a list")
        cleaned = []
        for value in values:
            host = str(value).strip().lower().rstrip(".")
            if not host or any(ch in host for ch in "/:@?#"):
                raise ValueError(f"Invalid host in network_policy.{key}: {value}")
            if host not in cleaned:
                cleaned.append(host)
        network_policy[key] = cleaned[:64]

    for name, color in merged["led"].items():
        if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
            raise ValueError(f"LED color {name} must use #RRGGBB")
        int(color[1:], 16)
    return merged


def _host_matches(host: str, rule: str) -> bool:
    host = host.lower().rstrip(".")
    rule = rule.lower().rstrip(".")
    if rule.startswith("*."):
        suffix = rule[1:]
        return host.endswith(suffix) and host != suffix[1:]
    return host == rule


def _url_allowed(url: str) -> bool:
    policy = config["network_policy"]
    if not policy["enabled"]:
        return True
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https", "ws", "wss"} or not host:
            return False
        # Normalise IP literals before comparison and reject malformed ones.
        try:
            host = str(ipaddress.ip_address(host))
        except ValueError:
            pass
    except ValueError:
        return False
    if any(_host_matches(host, rule) for rule in policy["blocked_hosts"]):
        return False
    allowed = policy["allowed_hosts"]
    return not allowed or any(_host_matches(host, rule) for rule in allowed)


def _is_quiet_hours() -> bool:
    settings = config["notifications"]
    if not settings["quiet_hours_enabled"]:
        return False
    now = datetime.now(ZoneInfo(config["location"]["timezone"])).strftime("%H:%M")
    start, end = settings["quiet_start"], settings["quiet_end"]
    return start <= now < end if start < end else now >= start or now < end


class DeviceHub:
    """Tracks the single connected StackChan (v0.1: one device)."""

    def __init__(self) -> None:
        self.ws: web.WebSocketResponse | None = None

    async def register(self, ws: web.WebSocketResponse) -> None:
        if self.ws is not None:
            log.warning("a new device connection replaced an existing one")
        self.ws = ws
        log.info("device connected")
        await self.send_settings()

    def unregister(self, ws: web.WebSocketResponse) -> None:
        if self.ws is ws:
            self.ws = None
            log.info("device disconnected")

    async def send(self, message: dict) -> bool:
        if self.ws is None:
            log.warning("no device connected, dropping %s message", message.get("type"))
            return False
        try:
            await self.ws.send_str(json.dumps(message))
            # Type and id only: settings carry the home location and
            # notifications carry message text, neither of which belongs in logs.
            log.info("sent %s to device (id=%s)", message.get("type"), message.get("id", "-"))
            return True
        except Exception:
            log.exception("failed to send notification to device")
            self.ws = None
            return False

    async def send_settings(self, acknowledge: bool = False) -> bool:
        return await self.send(
            {"type": "settings", "settings": _public_config(), "acknowledge": acknowledge}
        )


hub = DeviceHub()


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    # No aiohttp-driven heartbeat here — the device sends its own periodic
    # {"type":"ping"} application-level keepalive instead, which it also
    # uses to actively detect a dead connection (rather than relying on
    # TCP/WS-layer close detection, which was unreliable in practice).
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    log.info("device websocket peer=%s", request.remote)
    await hub.register(ws)
    try:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                log.info("ignoring non-text device frame: %s", msg.type)
                continue
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                log.info("ignoring non-JSON device frame: %r", str(msg.data)[:120])
                continue
            if payload.get("type") == "notification_ack":
                notification_id = str(payload.get("id", ""))
                for item in history:
                    if item.get("id") == notification_id:
                        item["acknowledged"] = True
                        item["acknowledged_at"] = datetime.now().astimezone().isoformat()
                        _atomic_write_json(HISTORY_PATH, history)
                        break
            elif payload.get("type") == "device_event":
                log.info("device event: %s", str(payload.get("event", ""))[:200])
            elif payload.get("type") == "settings_ack":
                log.info("device acknowledged settings (beep played=%s)", payload.get("played"))
            elif payload.get("type") != "ping":
                log.info("unhandled device message type: %s", payload.get("type"))
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
    if not _url_allowed(url):
        log.warning("network policy blocked notification image URL: %s", url)
        return None
    headers = {}
    if HA_BASE_URL and url.startswith(HA_BASE_URL) and HA_TOKEN:
        headers["Authorization"] = f"Bearer {HA_TOKEN}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False
            ) as resp:
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


async def control_handler(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(CONTROL_HTML_PATH)


async def config_get_handler(request: web.Request) -> web.Response:
    return web.json_response(_public_config())


async def config_put_handler(request: web.Request) -> web.Response:
    global config
    try:
        candidate = await request.json()
        if not isinstance(candidate, dict):
            raise ValueError("configuration must be an object")
        config = _validate_config(candidate)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    _atomic_write_json(CONFIG_PATH, config)
    await hub.send_settings(acknowledge=True)
    return web.json_response(_public_config())


async def import_home_assistant_handler(request: web.Request) -> web.Response:
    global config
    if not HA_BASE_URL or not HA_TOKEN:
        raise web.HTTPBadRequest(text="HA_BASE_URL and HA_TOKEN must be configured")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{HA_BASE_URL}/api/config",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                ha_config = await response.json()
    except Exception as exc:
        raise web.HTTPBadGateway(text="Could not read Home Assistant configuration") from exc

    candidate = _public_config()
    location = candidate["location"]
    location["name"] = str(ha_config.get("location_name") or location["name"])
    location["latitude"] = ha_config.get("latitude")
    location["longitude"] = ha_config.get("longitude")
    location["timezone"] = str(ha_config.get("time_zone") or location["timezone"])
    config = _validate_config(candidate)
    _atomic_write_json(CONFIG_PATH, config)
    await hub.send_settings(acknowledge=True)
    return web.json_response(_public_config())


async def history_handler(request: web.Request) -> web.Response:
    return web.json_response(history)


async def history_clear_handler(request: web.Request) -> web.Response:
    history.clear()
    _atomic_write_json(HISTORY_PATH, history)
    return web.json_response({"ok": True})


async def handle_mqtt_notification(payload: dict) -> None:
    log.info("received MQTT notification (category=%s)", payload.get("category", "general"))
    try:
        category = str(payload.get("category", "general"))
        policy = config["notifications"]["categories"].get(
            category, config["notifications"]["categories"]["general"]
        )
        notification_id = uuid.uuid4().hex
        urgent = payload.get("urgent") if isinstance(payload.get("urgent"), bool) else policy["urgent"]
        speak = payload.get("speak") if isinstance(payload.get("speak"), bool) else policy["speak"]
        if _is_quiet_hours() and not urgent:
            speak = False

        message = {
            "type": "notification",
            "id": notification_id,
            "title": str(payload.get("title", "")),
            "body": str(payload.get("body", "")),
            "category": category,
            "color": policy["color"],
            "urgent": urgent,
        }

        image_url = payload.get("image_url")
        if image_url:
            filename = await fetch_and_prepare_image(str(image_url))
            if filename:
                message["image_url"] = f"{PUBLIC_BASE_URL}/images/{filename}"

        if speak:
            announce_text = " ".join(p for p in (message["title"], message["body"]) if p)
            audio_filename = await synthesize_notification_audio(announce_text)
            if audio_filename:
                message["audio_url"] = f"{PUBLIC_BASE_URL}/audio/{audio_filename}"

        delivered = False
        if not config["notifications"]["dnd"]:
            delivered = await hub.send(message)

        history.insert(
            0,
            {
                "id": notification_id,
                "timestamp": datetime.now().astimezone().isoformat(),
                "title": message["title"],
                "body": message["body"],
                "category": category,
                "urgent": urgent,
                "spoken": speak,
                "delivered": delivered,
                "acknowledged": False,
            },
        )
        del history[MAX_HISTORY:]
        _atomic_write_json(HISTORY_PATH, history)
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
    app.router.add_get("/", control_handler)
    app.router.add_get("/api/config", config_get_handler)
    app.router.add_put("/api/config", config_put_handler)
    app.router.add_post("/api/import-home-assistant", import_home_assistant_handler)
    app.router.add_get("/api/history", history_handler)
    app.router.add_delete("/api/history", history_clear_handler)

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
