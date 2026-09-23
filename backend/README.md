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
  `image_url`, `urgent`) to the device over its own dedicated WebSocket at `:8090/ws` — separate from the
  voice channel above, so it works independently of whatever the voice conversation is doing. If an
  `image_url` is given, the bridge fetches it, resizes it to fit the 320×240 screen, and serves it
  back over plain HTTP for the device to fetch and decode itself (auto-attaches the HA bearer token
  when the URL points back at `HA_BASE_URL`, so an HA camera-snapshot URL just works). Unless the
  payload sets `"speak": false`, it also calls Piper directly (the same instance
  `xiaozhi-esp32-server` uses) to synthesize the title/body, resamples that via `ffmpeg` to
  mono/16-bit/24kHz PCM WAV (the device's codec's native format — see "Notification audio" below),
  and serves that alongside the image too. The device itself decides when it's safe to actually
  show/speak a queued notification (not mid-conversation) — see
  `firmware/main/stackchan/notify/notify_client.cpp`.

## Local control panel

Open `http://<StackZeta-host>:8090/` from the LAN. The control panel stores its configuration and
the most recent 100 notifications in the `stackzeta-state` Docker volume, then pushes device
settings over the existing notification WebSocket. It controls home geolocation, personality and
idle activity, volume, brightness, sleep timeout, privacy mode, DND/quiet hours, notification
category policy, and LED state colors.

The **Import from Home Assistant** action reads HA's configured home name, coordinates, and
timezone from `/api/config` using the bridge's server-side token. It does not use browser
geolocation, IP geolocation, or any external lookup. Set the preferred HA weather entity after
import if it is not `weather.home`.

Notification payloads may include `category` (`general`, `security`, `doorbell`, `reminder`, or
`household`). Category defaults decide color, speech, and urgency unless the payload explicitly
provides boolean `speak` or `urgent` values. Quiet hours mute routine speech; urgent alerts still
sound. DND records history but suppresses delivery. On the robot, swipe forward across the head
touch strip to acknowledge the last notification or backward to repeat it.

## Privacy mode (v0.4)

Toggled from the control panel. Enforced in two independent layers:

1. **On the device** (`firmware/patches/xiaozhi-esp32.patch` + `notify_client.cpp`): wake word,
   push-to-talk, screen-tap chat, proximity wake and camera capture are refused; any transition
   into listening is blocked; a server reply that arrives after privacy turns on is ignored; turning
   privacy on mid-conversation aborts speech and drops the session. The setting is saved in NVS, so
   it holds from boot before the backend reconnects. The LED ring shows the privacy colour (default
   `#FF0000`) and never goes dark in standby while privacy is on.
2. **On the voice server** (`xiaozhi-server/overrides/stackzeta_privacy.py`, wired in by
   `patch_privacy.py`): reads `privacy_mode` from the control panel's saved state (the
   `stackzeta-state` volume, mounted read-only), and while it is on refuses new voice connections,
   drops device audio and `listen` messages, discards buffered audio, and closes any open voice
   connection within ~0.5 s. The patch **fails closed**: if an upstream image change breaks it, the
   voice server does not start.

Layer 2 exists because the device side is not fully observable (no serial logging after boot, and
its voice socket was seen to stay open after privacy-on). Verified end to end on hardware: toggling
privacy on mid-conversation, nothing spoken while the ring was red reached ASR, and the wake word
worked again after privacy was turned off.

Known limit: audio captured in the instant *before* privacy turns on can still be transcribed as
the toggle lands (the device's final `listen stop` races the server's ≤0.25 s state check). Audio
captured after it cannot.

## Triggering notifications from Home Assistant

Any HA automation can trigger one by publishing a JSON payload to the MQTT topic in `.env`
(`MQTT_TOPIC`, default `stackchan/notify`) on your existing Mosquitto broker. Fields: `title`
and/or `body` (plain text, both optional but at least one should be set), an optional `image_url`,
and optional `speak` and `urgent` booleans. `speak` defaults to `true`; set it to `false` to show
the notification silently. `urgent` defaults to `false`; when `true`, the notification moves to
the front of the device queue and interrupts an active listening or speaking session.

**Text-only**, e.g. on a door sensor:

```yaml
alias: Notify StackChan — front door opened
trigger:
  - platform: state
    entity_id: binary_sensor.front_door
    to: "on"
action:
  - service: mqtt.publish
    data:
      topic: stackchan/notify
      payload: >-
        {"title": "Front Door", "body": "Someone just opened the front door"}
```

**With an image**, e.g. a camera snapshot — HA's `entity_picture` attribute is a relative path, so
prefix it with your HA base URL (the bridge auto-attaches your HA token for any `image_url` under
that base, so an authenticated camera-proxy URL just works without extra setup):

```yaml
alias: Notify StackChan — front door camera
trigger:
  - platform: state
    entity_id: binary_sensor.front_door
    to: "on"
action:
  - service: mqtt.publish
    data:
      topic: stackchan/notify
      payload: >-
        {"title": "Front Door", "body": "Motion detected",
         "image_url": "http://192.168.8.135:8123{{ state_attr('camera.front_door', 'entity_picture') }}"}
```

Both examples use YAML mode (Settings → Automations → ⋮ → Edit in YAML), since the templated
payload is easier to write correctly there than in the visual editor — the visual editor's
"Call a service" action works too, just paste the same `mqtt.publish` data into its fields.

To test manually without waiting for a trigger: Developer Tools → Actions → search
`mqtt.publish`, paste the same `data:` block, and run it — the robot should speak the
title/body and show the image within a couple of seconds, or queue silently until any active
conversation finishes (see "Idle sleep" below for what happens if the screen is currently off).

For a time-critical alert, add `"urgent": true` to either payload. Use this sparingly: it ends the
current voice turn and discards any buffered assistant speech before announcing the alert.

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

## Notification audio (firmware)

Notification audio used to go through the firmware's built-in `Application::PlaySound()` (the
same Ogg/Opus decode pipeline the built-in chimes use), but that vendored decoder reliably
corrupted the heap and rebooted the device when fed this dynamically-synthesized speech —
reproduced repeatedly in testing (see git history on `stackchan/notify/notify_client.cpp` for the
investigation), independent of timing relative to a conversation. The device now bypasses that
decoder entirely for notification audio: the notify-bridge resamples Piper's WAV output to exactly
mono/16-bit/24kHz PCM (the codec's own native output format —
`firmware/main/hal/board/config.h`'s `AUDIO_OUTPUT_SAMPLE_RATE`), and the device parses that WAV
itself and writes the PCM straight to the codec (`AudioCodec::OutputData()`), never touching the
Ogg/Opus path. This is only safe when the normal voice pipeline isn't also using the codec —
`isDeviceBusy()` already rules out an active conversation, and the device additionally waits for
the voice pipeline's own playback queue to drain first, in case one just finished.

## Conversation motion (firmware)

Small, slow head movements (a nod or slight turn, every couple of seconds) during active
listening/speaking — not the LLM-driven deliberate gestures (`set_head_angles`), an ambient "it's
alive" animation. Speaking motion already existed in the upstream codebase
(`stackchan/modifiers/speaking.h`'s `SpeakingModifier`) but shipped with it disabled; listening
motion is new (`stackchan/modifiers/listening.h`), modeled on the same tuning. Both needed one
non-obvious fix: the natural gate for "don't start a new move while one's still in flight" is
`Motion::isMoving()`, which reads the feedback servo's own hardware "moving" status bit — but for
these small, slow moves that bit was observed staying stuck `true` long after the move had
visibly finished (a servo-feedback quirk, not a real ongoing move), silently blocking every tick
after the first. Both modifiers gate on a fixed cooldown since their own last commanded move
instead.

## Weather

There's no dedicated weather tool — the upstream `get_weather` plugin scrapes a Chinese-language
weather webpage, defaults to Guangzhou when it can't resolve a location, and hands the LLM a
Chinese-language report to translate on the fly, which was unreliable enough (and against the
"avoid Chinese services" goal) to just turn off. Instead, weather comes from Home Assistant's own
`homeassistant__GetLiveContext` tool (already available via the MCP connection) reading whatever
weather entity you have configured in HA — confirmed working with a PirateWeather entity. Two
things needed to be true for this to work: the entity exposed to HA's Assist feature (Settings →
Voice assistants → Expose), and the persona prompt explicitly told to use that tool for weather
questions (an LLM won't necessarily infer that a generic "read house state" tool answers a weather
question without being told — see the `prompt:` block in `.config.yaml`).

## Persistent memory

`Memory: mem_local_short` (in `.config.yaml`) summarizes each conversation and keeps the summaries
on this server only. The summarizer LLM **must** be set explicitly (`Memory.mem_local_short.llm:
OpenAILLM`): upstream's built-in default is `ChatGLMLLM` (Zhipu AI, `open.bigmodel.cn`), and the
earlier assumption that it falls back to the main LLM was wrong. Until v0.4 every summary attempt
was routed there and failed only because the placeholder API key can't be encoded into an HTTP
header — so no memory was ever actually saved before v0.4. Chosen specifically over cloud options like
`mem0ai`, which the project's own config comments recommend against for privacy-focused
deployments — this keeps conversation history from ever leaving the LAN, matching the same
LAN/OpenAI-only boundary as everything else in this stack.

## Proximity wake (firmware)

An LTR-553ALS-WA proximity sensor (I2C, address `0x23`) triggers a full wake — same as saying the
wake word — when a hand approaches within roughly arm's length, without needing a hardware driver
that existed anywhere in the upstream codebase already (unlike touch/IMU/RTC, all of which had one
to model this on). New files: `firmware/main/hal/drivers/LTR553/` (the driver itself,
register map from the official datasheet) and `firmware/main/stackchan/proximity/proximity_wake.h`
(a dedicated FreeRTOS task, calls `Application::WakeWordInvoke("proximity")` on the idle→near
transition). Runs on its own task rather than the shared UI/update loop, matching the established
pattern in this codebase for any polling/I2C work that could block. Calibrated against real
hardware: baseline (nothing nearby) sits stable around 40-49, climbing to 200+ as a hand
approaches — threshold of 200 confirmed triggering a real wake (screen, servos, wake sound) on
first attempt, with hysteresis (re-arms only below 120) to avoid chattering right at the edge.

## Do Not Disturb

`self.notifications.set_do_not_disturb` / `get_do_not_disturb` — new MCP tools
(`firmware/main/hal/hal_mcp.cpp`) so a spoken command ("turn on do not disturb") can toggle
whether incoming HA-triggered notifications get shown/spoken at all. While enabled, notifications
are silently dropped (logged, not queued for later) rather than held back and shown once free —
deliberately not persisted across reboots, since a DND that's stuck on and survives a power cycle
silently seemed like a worse footgun than just having to say it again. State lives in
`NotifyClient` (`firmware/main/stackchan/notify/notify_client.cpp`), a plain atomic flag checked in
`drainIncoming()` before a notification is even queued.

## Removing Chinese output (backend)

Beyond the persona/language overrides above, several more sources of hardcoded Chinese text were
found and neutralized — none of them go through the LLM's own (English-instructed) response
generation, so the persona fix alone didn't catch them:

- **`end_prompt`** — a scripted farewell spoken verbatim when a session times out. Disabled
  (`end_prompt.enable: false`) rather than translated — see the comment in `.config.yaml`.
- **`handle_exit_intent`** — the plugin's tool description and fallback farewell were Chinese;
  overridden with an English version, mounted over the built-in file (see
  `xiaozhi-server/overrides/README.md`).
- **`play_music`** — several more hardcoded Chinese strings, and expects a local music library we
  don't have. Replaced with an English stub, same mounting mechanism.
- **`change_role`** — can switch the entire system prompt to one of three hardcoded Chinese
  personas.
- **`get_weather`** — see "Weather" above.
- **`web_search`** — no API key configured (would need a Tavily account), and without one it
  returns a hardcoded Chinese error message when called.
- **`get_news_from_newsnow`** — defaults to Chinese news sources (English ones like Hacker
  News/GitHub Trending exist in its channel list but aren't the default).

The last four are simply left out of `Intent.function_call.functions` in `.config.yaml` (currently
empty) rather than patched — none were things we actually needed, and disabling was the lower-risk
fix. Re-enable individually if you want one badly enough to fix its Chinese-language issues
properly (`web_search` just needs a Tavily key; `get_news_from_newsnow` needs its default sources
changed to English ones).

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

Showing a notification wakes the screen directly (not via the normal conversation state machine),
so nothing would otherwise put it back to sleep afterward if the device stayed idle — the
`STANDBY` transition that normally triggers `EnterIdleSleep()` only fires on real conversation
state changes, and a notification isn't one. `notify_client.cpp`'s `maybeResleep()` puts it back
to sleep itself, ~10s after showing, if the device is still idle by then.

## Audio-reactive mouth (firmware)

The mouth's openness during speech is driven by the actual live speaker output level, not the
stock random open/close alternation. `CoreS3AudioCodec::Write()`
(`firmware/main/hal/board/cores3_audio_codec.cc`) — already a StackChan-owned override, not
dependency code — computes the peak sample magnitude of each chunk actually sent to the speaker
and stores it in a small shared atomic (`firmware/main/hal/board/audio_level.h`).
`SpeakingModifier::animate_mouth()` (`stackchan/modifiers/speaking.h`) polls that value, smooths it
slightly, and maps it to mouth weight — real (if simple) lip-sync. Confirmed working with live
data: levels swinging from near-zero (silence) up to ~30000 (loud words) in step with actual
speech, weight correctly tracking 0-100 accordingly.

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

## Privacy / network audit (v0.2)

The explicit goal, stated directly: this device should never talk to anything except OpenAI (the
one approved external service) and this LAN — nothing else, especially not Chinese cloud
endpoints. A full sweep of both the firmware and this backend found several things that violated
that, beyond the plugin-level Chinese-output fixes already covered above. All fixed as of v0.2:

- **A live outbound call to a Chinese IP-geolocation service, on every single conversation** —
  `core/utils/util.py`'s `get_ip_info()` was posting the client's IP to
  `https://whois.pconline.com.cn/ipJson.jsp` unconditionally, wired in via
  `agent-base-prompt.txt`'s `{{local_address}}`/`{{weather_info}}` template variables
  (`core/utils/prompt_manager.py`) — a mechanism completely separate from the `get_weather`
  *plugin* already disabled above via the empty functions list. Disabling that plugin turned out
  to be necessary but not sufficient: this was a second, independent path to the same kind of
  data leaving the LAN, firing on every conversation rather than only when a weather question was
  actually asked, and it was missed in the first pass specifically because it isn't a plugin or a
  `selected_module` — it's core connection-setup logic. See `xiaozhi-server/overrides/README.md`
  and `patch_chinese_strings.py` for the fix and the rest of what that patch covers (a further ~20
  hardcoded Chinese strings across core files that get spoken via TTS or injected into the LLM's
  own conversation context, e.g. a tool-call-timeout message and the few-shot examples that teach
  the model the tool-calling pattern).
- **Vision/camera defaults to a Chinese cloud AI, and it's actually wired up** — the `VLLM`
  (vision) module was never configured, so it silently fell back to upstream's default
  (`ChatGLMVLLM` → `open.bigmodel.cn`, Zhipu AI). The firmware's camera `Explain()` feature
  (triggered by the device's own `self.camera.take_photo` MCP tool, which the LLM can call anytime
  — it isn't gated by `Intent.function_call.functions` the way server-side plugins are) genuinely
  posts captured photos there. Fixed by adding `VLLM.OpenAIVLLM` to `.config.yaml`, routed through
  OpenAI like the LLM. The provider code itself also hardcoded `"(请使用中文回复)"`
  ("please reply in Chinese") onto every vision question regardless of persona/language config —
  see `xiaozhi-server/overrides/vllm_openai.py`.
- **Firmware-side findings** (see `upstream/StackChan/firmware`, not this directory): a hardcoded
  Chinese NTP server (`cn.pool.ntp.org`, alongside `pool.ntp.org`/`time.google.com`) queried on
  every boot with no Kconfig override possible — narrowed to `pool.ntp.org` only
  (`main/hal/hal_network.cpp`). Four M5Stack-cloud-only apps/menus (Avatar/video-call, App Center,
  EzData, and the Setup app's Account/unbind menu) removed from the launcher entirely
  (`main/main.cpp`, `main/apps/app_setup/app_setup.cpp`) rather than just neutered — they only
  talked to M5Stack's own servers (`api.tenclass.net`, `47.113.125.164:12800`,
  `ezdata2.m5stack.com`), had nothing to do with this project's self-hosted backend, and App
  Center specifically could install a firmware update from that cloud. `CONFIG_STACKCHAN_SERVER_URL`
  also overridden to an inert value in `sdkconfig.defaults` as defense-in-depth, though nothing can
  reach it anymore regardless.

Camera vision itself (separately from where it points) exposed a pre-existing firmware hang once
the VLLM fix made it reachable: `StackChanCamera::Explain()` could wait indefinitely for a slow or
stalled response, stopping voice interaction until power-cycled. The firmware now applies a
20-second HTTP timeout and reads the response incrementally, returning a tool error instead of
wedging the device. This still needs a live slow-response/failure-path test on hardware.
- FunASR (local ASR) occasionally mishears place names / low-frequency words in English speech —
  not blocking, but worth watching. `sherpa_onnx_local` is a lighter alternative if this becomes a
  problem.
- `startAiAgentOnBoot` needs to be enabled once, on the device itself (Setup → AI.Agent → General →
  "Start AI Agent on boot" switch) — it's a persisted device-side setting, not something this repo
  can set from the backend. Until it's on, the device boots to the app launcher instead of straight
  into the assistant.

## Known issues (v0.4)

- **Warm reset boot-loops the CoreS3** (`PSRAM chip is not connected`), on v0.3 firmware too, so
  not caused by v0.4. Any reset other than a full power-off (after flashing, and presumably after
  an OTA update) needs a power cycle: hold the side button ~6 s, then press. Flash with
  `esptool ... --after no_reset write_flash @flash_args` from `firmware/build` and power-cycle.
- **Speaker crackle** was heard once on v0.4 after a privacy toggle and could not be reproduced
  afterwards (bisected across LEDs, activity profile, standby and privacy-on boot; v0.3 was clean).
- **Device event reporting** (`NotifyClient::ReportEvent` → `device_event` on the notify socket)
  is compiled in and verified present in the binary, but no event frame ever leaves the device —
  unexplained. The device's `listen stop` on privacy-on is similarly unexplained.
- **App logs are not visible over USB** after boot (likely the USB host component taking the port).
- **DND set by voice is overwritten** by the next settings push from the control panel.
- The control panel and its API are **unauthenticated** on the LAN.
- **Memory summaries are written in Chinese** (upstream's `mem_local_short` summarizer prompt is
  Chinese), and are injected into the LLM context — a risk to the English-only output goal. Only
  surfaced in v0.4, since memory never saved before. Stored in `data/.memory.yaml` (gitignored).

## Deferred

- Local LLM option — OpenAI is the only backend wired up so far.
