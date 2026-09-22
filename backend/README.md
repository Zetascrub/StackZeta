# StackZeta backend

Self-hosted voice-assistant backend for the StackChan, running on this machine via Docker Compose.

## Services

- **xiaozhi-esp32-server** (`ghcr.io/xinnan-tech/xiaozhi-esp32-server:server_latest`) — the
  voice/OTA server the firmware talks to. ASR (FunASR, local), Intent (`function_call`), and LLM
  (OpenAI) all run/are called from here. Config: `xiaozhi-server/data/.config.yaml` (gitignored —
  copy `.config.yaml.example` and fill in your own OpenAI key + LAN IP).
- **piper-tts** — Piper's own official HTTP server (`python -m piper.http_server`), wrapped in a
  small Dockerfile. Not exposed to the host; only `xiaozhi-esp32-server` talks to it, over
  `http://piper-tts:5000/synthesize`. Configured as xiaozhi's `CustomTTS` provider — no server-side
  code changes needed, `custom.py` is a generic HTTP client.
- **Home Assistant** — not part of this stack, runs externally at `http://192.168.8.135:8123`.
  Reached via its own **Model Context Protocol Server** integration (Settings → Devices & Services
  → Add Integration), which `xiaozhi-esp32-server` connects to as an MCP client
  (`xiaozhi-server/data/.mcp_server_settings.json`, gitignored). This gives the LLM real HA tools
  (`intent__HassTurnOn`, `light__HassLightSet`, `media_player__*`, `vacuum__*`, etc.) without any
  custom integration code — confirmed working (lights on/off by area and by name).
- **notify-bridge** — a small custom Python/aiohttp service. Subscribes to HA's existing Mosquitto
  broker (topic `stackchan/notify`, see `.env`), and relays JSON payloads (`title`, `body`, optional
  `image_url`) to the device over its own dedicated WebSocket at `:8090/ws` — separate from the
  voice channel above, so it works independently of whatever the voice conversation is doing. If an
  `image_url` is given, the bridge fetches it, resizes it to fit the 320×240 screen, and serves it
  back over plain HTTP for the device to fetch and decode itself (auto-attaches the HA bearer token
  when the URL points back at `HA_BASE_URL`, so an HA camera-snapshot URL just works). The device
  itself decides when it's safe to actually show a queued notification (not mid-conversation) —
  see `firmware/main/stackchan/notify/notify_client.cpp`.

## Setup

```bash
cp xiaozhi-server/data/.config.yaml.example xiaozhi-server/data/.config.yaml
cp xiaozhi-server/data/.mcp_server_settings.json.example xiaozhi-server/data/.mcp_server_settings.json
cp .env.example .env
# edit all three: OpenAI API key, HA long-lived access token, MQTT credentials, this machine's LAN IP

mkdir -p xiaozhi-server/models/SenseVoiceSmall
curl -L -o xiaozhi-server/models/SenseVoiceSmall/model.pt \
  https://modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt

docker compose up -d --build
docker logs -f xiaozhi-esp32-server
```

OTA endpoint: `http://<LAN-IP>:8003/xiaozhi/ota/` — this is what firmware's `CONFIG_OTA_URL`
(`upstream/StackChan/firmware/sdkconfig.defaults`) points at.

## Persona / language

The upstream project's default `prompt:` is a Chinese-language persona, and the reply language is
driven by `TTS.<provider>.language` (defaults to Chinese if unset — this bit us on first boot: the
very first reply after wake-word uses the raw persona text verbatim with no language wrapper, so it
was in Chinese even though the LLM itself is fully capable of English). Both are overridden in
`.config.yaml`: an English "Zeta" persona under `prompt:`, and `TTS.PiperTTS.language: en_us`.

## Idle sleep (firmware)

When the device goes idle (waiting for the wake word), it homes both servos, stops the stock
"wander while idle" animation, and dims the screen off — then wakes (servos free, screen back on)
on the next wake-word trigger *or* an incoming notification. Implemented in
`firmware/main/hal/board/stackchan_display.cc` (`EnterIdleSleep()`/`WakeFromIdleSleep()`, hooked
into the existing `SetStatus()` idle/listening transitions) — see
`firmware/main/stackchan/notify/notify_client.cpp`'s `show()` for the notification-wakes-screen
side. The screen-off step is debounced by 2s: the `idle` status fires briefly and transiently
during the wake-word handshake itself (before the real `listening` status follows), and without
the debounce that blip alone was enough to flash the screen off and immediately back on.

## Idle timeout

`close_connection_no_voice_time` (in `.config.yaml`) controls how long the server waits with no
voice input before hanging up the session — but `xiaozhi-esp32-server`'s own code always adds a
**fixed 60s grace period on top** of whatever this is set to, so it's not a true floor-to-zero
knob. We tried `0` (in principle a ~60s effective timeout) and it broke something else: the same
value also governs the "give the user a moment to actually start talking" window right after
wake-word, so at `0` the device was reverting from `listening` back to `idle` in well under a
second — visible on the firmware side as the screen flashing on then straight back off. Settled on
`15` (~75s effective) as a value that shortens the original 120-default meaningfully without
breaking that window. If a shorter session tail matters more than a snappier wake, revisit this —
but changing it again means retesting the wake-to-first-word timing, not just the tail end.

## Known rough edges (v0.1)

- FunASR (local ASR) occasionally mishears place names / low-frequency words in English speech —
  not blocking, but worth watching. `sherpa_onnx_local` is a lighter alternative if this becomes a
  problem.
- `startAiAgentOnBoot` needs to be enabled once, on the device itself (Setup → AI.Agent → General →
  "Start AI Agent on boot" switch) — it's a persisted device-side setting, not something this repo
  can set from the backend. Until it's on, the device boots to the app launcher instead of straight
  into the assistant.

## Deferred to v0.2

- Natural head motion *during* active conversation (distinct from the idle-sleep behavior below,
  which only affects the fully-idle state) — currently the head only moves when the LLM explicitly
  calls the `set_head_angles` tool as a deliberate gesture, there's no continuous "alive" motion
  while listening/speaking.
