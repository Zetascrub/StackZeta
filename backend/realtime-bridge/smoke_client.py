"""Send a 16 kHz mono PCM sample through a pilot bridge without using the device."""

import asyncio
import os
import sys
import time
from pathlib import Path

import aiohttp
import opuslib_next


async def main() -> None:
    pcm = Path(sys.argv[1]).read_bytes()
    frame_bytes = 16000 * 60 // 1000 * 2
    encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    url = os.environ.get("PILOT_URL", "http://127.0.0.1:8010/xiaozhi/v1/")
    token_file = os.environ.get("PILOT_TOKEN_FILE")
    token = Path(token_file).read_text().strip() if token_file else os.environ.get("PILOT_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if device_id := os.environ.get("PILOT_DEVICE_ID"):
        headers["Device-Id"] = device_id
    if client_id := os.environ.get("PILOT_CLIENT_ID"):
        headers["Client-Id"] = client_id
    headers["Protocol-Version"] = "1"
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(url, headers=headers, timeout=15) as ws:
            await ws.send_json({
                "type": "hello", "version": 1, "transport": "websocket",
                "audio_params": {"format": "opus", "sample_rate": 16000,
                                 "channels": 1, "frame_duration": 60},
            })
            hello = await ws.receive_json(timeout=10)
            assert hello["type"] == "hello", hello.get("type")
            await ws.send_json({"type": "listen", "state": "start"})
            for offset in range(0, len(pcm), frame_bytes):
                frame = pcm[offset:offset + frame_bytes].ljust(frame_bytes, b"\0")
                await ws.send_bytes(encoder.encode(frame, 960))
                await asyncio.sleep(0.06)
            ended_at = time.monotonic()
            if os.environ.get("PILOT_AUTO_TURN") == "1":
                silence = encoder.encode(bytes(frame_bytes), 960)
                for _ in range(20):
                    await ws.send_bytes(silence)
                    await asyncio.sleep(0.06)
            else:
                await ws.send_json({"type": "listen", "state": "stop"})
            frames = 0
            first_audio_ms = None
            assistant_transcript_chars = 0
            previous_audio_at = None
            max_audio_gap_ms = 0
            async with asyncio.timeout(40):
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.BINARY:
                        frames += 1
                        now = time.monotonic()
                        if first_audio_ms is None:
                            first_audio_ms = round((now - ended_at) * 1000)
                        if previous_audio_at is not None:
                            max_audio_gap_ms = max(max_audio_gap_ms,
                                                   round((now - previous_audio_at) * 1000))
                        previous_audio_at = now
                    elif message.type == aiohttp.WSMsgType.TEXT:
                        data = message.json()
                        if data.get("type") == "tts" and data.get("state") == "sentence_start":
                            assistant_transcript_chars += len(data.get("text", ""))
                        if data.get("type") == "tts" and data.get("state") == "stop":
                            break
                    else:
                        break
            print(f"response_opus_frames={frames} first_audio_ms={first_audio_ms} "
                  f"assistant_transcript_chars={assistant_transcript_chars} "
                  f"max_audio_gap_ms={max_audio_gap_ms}")
            if not frames:
                raise RuntimeError("no response audio arrived")


if __name__ == "__main__":
    asyncio.run(main())
