"""Xiaozhi/Opus to OpenAI Realtime voice bridge for the conversation pilot.

Only conversational audio is supported. The desktop backend remains available
for connection failures and features that have not been ported.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import difflib
import hmac
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

import aiohttp
import opuslib_next
import yaml
from aiohttp import web


log = logging.getLogger("stackzeta-realtime")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

FRAME_MS = 60
INPUT_RATE = 16000
OUTPUT_RATE = 24000
OUTPUT_FRAME_BYTES = OUTPUT_RATE * FRAME_MS // 1000 * 2
MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1")
OPENAI_URL = os.getenv("OPENAI_REALTIME_URL", f"wss://api.openai.com/v1/realtime?model={MODEL}")
FALLBACK_URL = os.getenv("FALLBACK_WS_URL", "")
DEVICE_TOKEN_FILE = Path(os.getenv("DEVICE_TOKEN_FILE", "/run/secrets/device_token"))
PRIVACY_FILE = Path(os.getenv("PRIVACY_CONFIG_FILE", "/run/stackzeta/config.json"))
SECRETS_FILE = Path(os.getenv("SECRETS_FILE", "/run/stackzeta/secrets.json"))
XIAOZHI_CONFIG_FILE = Path(os.getenv("XIAOZHI_CONFIG_FILE", "/run/stackzeta/xiaozhi.yaml"))
PRIVACY_URL = os.getenv("PRIVACY_URL", "")
PRIVACY_TOKEN_FILE = Path(os.getenv("PRIVACY_TOKEN_FILE", "/run/secrets/privacy_token"))


def secret_from_file(path: Path, env_name: str) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return os.getenv(env_name, "")


def api_key() -> str:
    """Allow a Docker secret or the existing panel's private state volume."""
    if value := os.getenv("OPENAI_API_KEY", ""):
        return value
    if value := secret_from_file(Path(os.getenv("OPENAI_API_KEY_FILE", "/run/secrets/openai_api_key")),
                                 "OPENAI_API_KEY"):
        return value
    try:
        value = json.loads(SECRETS_FILE.read_text())["openai_api_key"]
        return value if isinstance(value, str) else ""
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        config = yaml.safe_load(XIAOZHI_CONFIG_FILE.read_text())
        value = config["LLM"]["OpenAILLM"]["api_key"]
        return value if isinstance(value, str) and value else ""
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return ""


def privacy_is_off() -> bool:
    """Fail closed when the control service's state is missing or malformed."""
    try:
        value = json.loads(PRIVACY_FILE.read_text())["device"]["privacy_mode"]
        return value is False
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def check_privacy(client: aiohttp.ClientSession) -> bool:
    if not PRIVACY_URL:
        return privacy_is_off()
    privacy_token = secret_from_file(PRIVACY_TOKEN_FILE, "PRIVACY_TOKEN")
    if not privacy_token:
        return False
    try:
        async with client.get(
            PRIVACY_URL,
            headers={"Authorization": f"Bearer {privacy_token}"},
            timeout=aiohttp.ClientTimeout(total=0.5),
        ) as response:
            if response.status != 200:
                return False
            state = await response.json()
            return state.get("privacy_mode") is False
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return False


def authorized(request: web.Request) -> bool:
    device_token = secret_from_file(DEVICE_TOKEN_FILE, "DEVICE_TOKEN")
    if not device_token:
        return False
    supplied = request.headers.get("Authorization", "")
    return hmac.compare_digest(supplied, f"Bearer {device_token}")


def realtime_session_update() -> dict:
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": MODEL,
            "instructions": (
                "You are Zeta, a small desktop companion for someone who writes code. "
                "Be a good rubber duck: listen, help them explain the problem, reflect the key "
                "assumption, and ask one useful question at a time. Suggest a concrete next "
                "debugging step when it helps. Speak naturally in short English turns. "
                "Do not claim to see their screen, know their files, or control their home."
            ),
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": OUTPUT_RATE},
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": False,
                        "interrupt_response": False,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500,
                    },
                    "transcription": {"model": "gpt-4o-mini-transcribe"},
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": OUTPUT_RATE},
                    "voice": "marin",
                },
            },
        },
    }


async def preflight_realtime(openai: aiohttp.ClientWebSocketResponse) -> None:
    """Confirm configuration before accepting the device WebSocket."""
    await openai.send_json(realtime_session_update())
    async with asyncio.timeout(8):
        async for message in openai:
            if message.type != aiohttp.WSMsgType.TEXT:
                raise RuntimeError("Realtime connection closed during setup")
            event = json.loads(message.data)
            if event.get("type") == "session.updated":
                return
            if event.get("type") == "error":
                raise RuntimeError("Realtime rejected session configuration")
    raise RuntimeError("Realtime connection closed during setup")


class RealtimeBridge:
    def __init__(self, device: web.WebSocketResponse, openai: aiohttp.ClientWebSocketResponse,
                 client: aiohttp.ClientSession):
        self.device = device
        self.openai = openai
        self.client = client
        self.privacy_allowed = True
        self.decoder = opuslib_next.Decoder(INPUT_RATE, 1)
        self.encoder = opuslib_next.Encoder(OUTPUT_RATE, 1, opuslib_next.APPLICATION_AUDIO)
        self.input_resample_state = None
        self.output_buffer = bytearray()
        self.listening = False
        self.input_bytes = 0
        self.input_frames = 0
        self.turn_submitted = False
        self.pending_item_id: str | None = None
        self.ignore_input_until = 0.0
        self.last_spoken_text = ""
        self.speaking = False
        self.response_text = ""
        self.turn_end_at: float | None = None
        self.session_id = str(uuid.uuid4())

    @staticmethod
    def looks_like_echo(transcript: str, spoken: str) -> bool:
        def normalize(value: str) -> str:
            return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

        heard, output = normalize(transcript), normalize(spoken)
        if len(heard) < 12 or not output:
            return False
        return heard in output or difflib.SequenceMatcher(None, heard, output).ratio() >= 0.68

    async def send_device(self, message: dict) -> None:
        message.setdefault("session_id", self.session_id)
        await self.device.send_json(message)

    async def send_openai(self, message: dict) -> None:
        await self.openai.send_json(message)

    async def device_event(self, message: aiohttp.WSMessage) -> None:
        if message.type == aiohttp.WSMsgType.BINARY:
            if not self.listening or not self.privacy_allowed:
                return
            if time.monotonic() < self.ignore_input_until:
                return
            try:
                pcm = self.decoder.decode(message.data, INPUT_RATE * FRAME_MS // 1000)
            except Exception:
                log.warning("invalid Opus packet", exc_info=False)
                return
            pcm, self.input_resample_state = audioop.ratecv(
                pcm, 2, 1, INPUT_RATE, OUTPUT_RATE, self.input_resample_state
            )
            self.input_bytes += len(pcm)
            self.input_frames += 1
            await self.send_openai({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode("ascii"),
            })
            return
        if message.type != aiohttp.WSMsgType.TEXT:
            return
        try:
            event = json.loads(message.data)
        except (ValueError, TypeError):
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "hello":
            params = event.get("audio_params") or {}
            if event.get("version") != 1 or params.get("format") != "opus" or params.get("sample_rate") != INPUT_RATE:
                await self.device.close(code=1003, message=b"unsupported Xiaozhi audio")
                return
            await self.send_device({
                "type": "hello", "version": 1, "transport": "websocket",
                "audio_params": {"format": "opus", "sample_rate": OUTPUT_RATE,
                                 "channels": 1, "frame_duration": FRAME_MS},
            })
        elif kind == "listen":
            state = event.get("state")
            if state == "start":
                if not self.privacy_allowed:
                    await self.device.close(code=1008, message=b"privacy mode")
                    return
                if self.speaking:
                    await self.send_openai({"type": "response.cancel"})
                    self.output_buffer.clear()
                    self.speaking = False
                self.listening = True
                self.input_bytes = 0
                self.input_frames = 0
                self.turn_submitted = False
                self.pending_item_id = None
                self.input_resample_state = None
                await self.send_openai({"type": "input_audio_buffer.clear"})
                self.ignore_input_until = (time.monotonic() + 1.25) if self.last_spoken_text else 0.0
                log.info("device listening started mode=%s echo_guard=%s", event.get("mode", "unknown"),
                         bool(self.ignore_input_until))
            elif state == "stop" and self.listening:
                self.listening = False
                log.info("device listening stopped frames=%d submitted=%s", self.input_frames,
                         self.turn_submitted)
                if self.input_bytes and not self.turn_submitted:
                    self.turn_submitted = True
                    self.turn_end_at = time.monotonic()
                    await self.send_openai({"type": "input_audio_buffer.commit"})
        elif kind == "abort":
            await self.send_openai({"type": "response.cancel"})
            self.output_buffer.clear()
            if self.speaking:
                self.speaking = False
                await self.send_device({"type": "tts", "state": "stop"})

    async def openai_event(self, message: aiohttp.WSMessage) -> None:
        if message.type != aiohttp.WSMsgType.TEXT:
            return
        try:
            event = json.loads(message.data)
        except ValueError:
            return
        kind = event.get("type")
        if kind == "error":
            log.warning("OpenAI Realtime error type=%s", (event.get("error") or {}).get("type", "unknown"))
            return
        if kind == "input_audio_buffer.speech_stopped":
            self.turn_submitted = True
            self.turn_end_at = time.monotonic()
            self.pending_item_id = event.get("item_id")
            log.info("server speech stopped frames=%d", self.input_frames)
        elif kind == "input_audio_buffer.committed" and not self.pending_item_id:
            self.pending_item_id = event.get("item_id")
        elif kind == "response.created":
            log.info("server response started")
        elif kind == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript")
            if event.get("item_id") == self.pending_item_id and isinstance(transcript, str):
                self.pending_item_id = None
                if self.looks_like_echo(transcript, self.last_spoken_text):
                    log.info("echo turn suppressed")
                    await self.send_openai({"type": "conversation.item.delete", "item_id": event["item_id"]})
                    return
                await self.send_device({"type": "stt", "text": transcript})
                await self.send_openai({"type": "response.create"})
        elif kind == "conversation.item.input_audio_transcription.failed":
            if event.get("item_id") == self.pending_item_id:
                self.pending_item_id = None
                await self.send_openai({"type": "response.create"})
        elif kind == "response.output_audio_transcript.delta":
            self.response_text += event.get("delta", "")
        elif kind == "response.output_audio.delta":
            if not self.privacy_allowed:
                await self.device.close(code=1008, message=b"privacy mode")
                return
            if not self.speaking:
                self.speaking = True
                if self.turn_end_at is not None:
                    log.info("first_audio_ms=%d", round((time.monotonic() - self.turn_end_at) * 1000))
                await self.send_device({"type": "tts", "state": "start"})
            try:
                self.output_buffer.extend(base64.b64decode(event["delta"], validate=True))
            except (KeyError, ValueError):
                return
            while len(self.output_buffer) >= OUTPUT_FRAME_BYTES:
                frame = bytes(self.output_buffer[:OUTPUT_FRAME_BYTES])
                del self.output_buffer[:OUTPUT_FRAME_BYTES]
                await self.device.send_bytes(self.encoder.encode(frame, OUTPUT_RATE * FRAME_MS // 1000))
        elif kind == "response.done":
            if self.speaking:
                if self.output_buffer:
                    frame = bytes(self.output_buffer).ljust(OUTPUT_FRAME_BYTES, b"\0")
                    await self.device.send_bytes(self.encoder.encode(frame, OUTPUT_RATE * FRAME_MS // 1000))
                    self.output_buffer.clear()
                if self.response_text:
                    await self.send_device({"type": "tts", "state": "sentence_start", "text": self.response_text})
                await self.send_device({"type": "tts", "state": "stop"})
                self.last_spoken_text = self.response_text
            self.response_text = ""
            self.speaking = False
            self.turn_end_at = None

    async def run(self) -> None:
        async def device_loop() -> None:
            async for message in self.device:
                await self.device_event(message)

        async def openai_loop() -> None:
            async for message in self.openai:
                await self.openai_event(message)

        async def privacy_loop() -> None:
            while not self.device.closed:
                self.privacy_allowed = await check_privacy(self.client)
                if not self.privacy_allowed:
                    await self.device.close(code=1008, message=b"privacy mode")
                    return
                await asyncio.sleep(0.25)

        tasks = [asyncio.create_task(coro()) for coro in (device_loop, openai_loop, privacy_loop)]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in done:
            if exc := task.exception():
                raise exc


async def proxy_fallback(request: web.Request, device: web.WebSocketResponse,
                         client: aiohttp.ClientSession) -> None:
    headers = {name: value for name, value in request.headers.items()
               if name.lower() in {"authorization", "device-id", "client-id", "protocol-version"}}
    async with client.ws_connect(FALLBACK_URL, headers=headers, heartbeat=None) as fallback:
        async def forward(source, destination) -> None:
            async for message in source:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await destination.send_str(message.data)
                elif message.type == aiohttp.WSMsgType.BINARY:
                    await destination.send_bytes(message.data)
                else:
                    break

        tasks = [asyncio.create_task(forward(device, fallback)),
                 asyncio.create_task(forward(fallback, device))]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def voice_handler(request: web.Request) -> web.WebSocketResponse:
    if not authorized(request):
        raise web.HTTPUnauthorized()
    key = api_key()
    if not key and not FALLBACK_URL:
        raise web.HTTPServiceUnavailable(text="voice service unavailable")

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=5)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        if not await check_privacy(client):
            raise web.HTTPServiceUnavailable(text="privacy state unavailable or enabled")
        openai = None
        if key:
            try:
                openai = await client.ws_connect(
                    OPENAI_URL, headers={"Authorization": f"Bearer {key}"},
                    heartbeat=20, max_msg_size=4 * 1024 * 1024,
                )
                await preflight_realtime(openai)
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError):
                log.warning("Realtime connection unavailable; using desktop fallback if configured")
                if openai is not None:
                    await openai.close()
                openai = None
        if openai is None and not FALLBACK_URL:
            raise web.HTTPServiceUnavailable(text="Realtime connection unavailable")

        device = web.WebSocketResponse(heartbeat=None, max_msg_size=1024 * 1024)
        await device.prepare(request)
        try:
            if openai is not None:
                async with openai:
                    await RealtimeBridge(device, openai, client).run()
            else:
                await proxy_fallback(request, device, client)
        finally:
            await device.close()
        return device


async def health_handler(request: web.Request) -> web.Response:
    privacy_configured = bool(PRIVACY_URL and secret_from_file(PRIVACY_TOKEN_FILE, "PRIVACY_TOKEN")) or PRIVACY_FILE.exists()
    device_configured = bool(secret_from_file(DEVICE_TOKEN_FILE, "DEVICE_TOKEN"))
    return web.json_response({"status": "ready" if api_key() and privacy_configured and device_configured else "unavailable"})


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/xiaozhi/v1/", voice_handler)
    app.router.add_get("/health", health_handler)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=8010)
