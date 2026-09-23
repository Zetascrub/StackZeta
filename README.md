# StackZeta

Custom firmware + self-hosted backend for an M5Stack StackChan desktop robot.

## Status: v0.4 — privacy release

A privacy-conscious voice assistant, confirmed working end to end:

- **Local ASR/TTS** — FunASR + Piper, both self-hosted; only transcribed text (not audio) leaves
  the LAN, to the LLM.
- **OpenAI LLM** — pluggable backend, config-driven, no firmware changes needed to swap providers.
- **Home Assistant control** — real device control via natural conversation (confirmed: lights on/
  off by area and by name), via HA's own MCP Server integration — no custom integration code.
- **HA-triggered notifications, with images and spoken audio** — an HA automation can publish to
  MQTT and have the robot speak and display a notification (with an optional image) on screen,
  held back until any active conversation finishes. Notification audio is written straight to the
  speaker codec by the firmware itself, bypassing the voice pipeline's Ogg/Opus decoder entirely —
  that decoder reliably corrupted the heap and rebooted the device on this kind of
  dynamically-synthesized speech (see `backend/README.md`'s "Notification audio" section).
- **Urgent notification priority** — an `urgent` MQTT flag moves an alert to the front of the
  device queue and safely interrupts an active listening or speaking session.
- **Zeta visual identity** — mascot boot artwork, a mascot launcher portrait, and a dark
  cyan/amber UI palette carried through the face, speech bubbles, status bar, and home indicator.
- **LAN control panel** — browser-based configuration for home geolocation, personality, volume,
  brightness, sleep, privacy, quiet hours, notification categories, and state-aware LED colors.
- **Contextual home location** — local questions resolve against a configured Home Assistant home
  location and weather entity, never an IP-geolocation service.
- **Interaction profiles** — quiet, balanced, and lively modes control idle behavior; head swipes
  acknowledge or repeat notifications; a sleepy transition precedes quiet-mode screen-off.
- **Privacy mode** — visibly indicated by the LED ring and blocks microphone processing, wake-word
  and proximity activation, screen-tap conversations, and camera capture. Enforced twice: inside the
  voice client's state machine (saved on the device, so it holds across reboots before the backend
  reconnects) and on the voice server, which drops device audio and closes the voice connection
  while privacy is on — see `backend/README.md`'s "Privacy mode" section.
- **Device network policy** — an allow/block host list, pushed from the control panel and saved on
  the device, checked before every OTA, asset, voice, notification-media, and camera request.
- **Do Not Disturb** — a spoken command toggles whether notifications get shown/spoken at all,
  without needing to touch Home Assistant.
- **Chatbot with expressions** — English persona, emoji-driven face expressions, wake-word or
  press-to-talk activation, audio-reactive mouth (real lip-sync, driven by live speaker output
  level, not random flapping), and no unexpected Chinese output or unexpected external
  communication — see "Privacy" below.
- **Persistent memory** — conversations are summarized and remembered across sessions, kept on
  this server only (no cloud memory service).
- **Proximity wake** — walking up to the robot triggers a full wake (screen, servos, wake sound),
  same as saying the wake word, via a proximity sensor with no upstream driver to build on.
- **Idle sleep** — homes the servos and turns the screen off when idle, wakes on the next wake-word,
  proximity trigger, or notification.
- **Conversation motion** — small, natural head movement (nods/turns) while actively listening or
  speaking, not just static.
- **Weather** — via Home Assistant's own live-context tool, reading whatever weather integration
  you already have there (confirmed with PirateWeather) — no separate weather service.

## Privacy

The explicit design goal, not just a side effect: this device talks to OpenAI (the one approved
external service) and this LAN — nothing else. A full audit of both the firmware and backend
found and closed several violations of that beyond the Chinese-language content already mentioned
above, including a live outbound call to a Chinese IP-geolocation service firing on every single
conversation, a vision/camera feature that defaulted to a Chinese cloud AI, a hardcoded Chinese
NTP server queried every boot, and four M5Stack-cloud-only apps removed from the on-device
launcher entirely. Full findings and fixes: `backend/README.md`'s "Privacy / network audit"
section.

v0.4 also fixed a leak the v0.2 audit missed: conversation-memory summaries were routed to
Zhipu AI's cloud (`open.bigmodel.cn`) by an upstream default, and now go to OpenAI; bridge logs no
longer record home coordinates or notification text. Known issues, including a warm-reset boot
loop on this CoreS3: `backend/README.md`'s "Known issues (v0.4)".

Device: M5Stack **CoreS3** (ESP32-S3, 16MB flash, 8MB PSRAM) in the StackChan body kit. Full spec
sheet and pinout: [`docs/hardware.md`](docs/hardware.md). Full flash backup taken before any
changes: [`backups/`](backups/README.md).

## Repo layout

```
StackZeta/
├── backend/              Self-hosted voice/notification backend (Docker Compose) — see backend/README.md
├── backups/              Full flash dump taken before flashing anything custom
├── docs/                 Research notes: hardware, toolchain, architecture, references
└── upstream/StackChan/   Clone of m5stack/StackChan, on branch `stackzeta-v0.1` — the firmware fork
```

## Architecture

The firmware is a light fork of [`m5stack/StackChan`](https://github.com/m5stack/StackChan) (ESP-IDF
C++, bundles [`xiaozhi-esp32`](https://github.com/78/xiaozhi-esp32) as the voice client) — see
[`docs/architecture-notes.md`](docs/architecture-notes.md) for how the upstream code is organized,
and [`docs/toolchain.md`](docs/toolchain.md) for the build/flash flow. Firmware changes live in
`firmware/main/`, with one deliberate exception: `firmware/patches/xiaozhi-esp32.patch` (applied by
`fetch_repos.py`) carries small edits to the fetched `xiaozhi-esp32` dependency that cannot be made
from outside it — see the last bullet below:

- `firmware/sdkconfig.defaults` — `CONFIG_OTA_URL` and `CONFIG_NOTIFY_WS_URL` point at the
  self-hosted backend instead of M5Stack's cloud; `CONFIG_STACKCHAN_SERVER_URL` overridden to an
  inert value (defense-in-depth — see "Privacy" above).
- `firmware/main/stackchan/notify/` — a small WebSocket client (independent of the voice
  connection) for the notification feature; also fetches/plays notification images and audio
  (writing PCM straight to the codec, not via the voice pipeline's decoder — see
  `backend/README.md`), and holds the Do Not Disturb state.
- `firmware/main/hal/board/stackchan_display.cc` — idle-sleep behavior, hooked into the existing
  `SetStatus()` transitions.
- `firmware/main/stackchan/modifiers/listening.h` — new ambient head-motion modifier for the
  listening state; `speaking.h`'s equivalent already existed upstream, just shipped disabled.
- `firmware/main/hal/board/audio_level.h` — live speaker-output level tracking, feeding an
  audio-reactive mouth animation instead of the stock random one.
- `firmware/main/hal/drivers/LTR553/` + `firmware/main/stackchan/proximity/` — proximity sensor
  driver (no upstream equivalent existed) and the wake-on-approach task built on it.
- `firmware/main/hal/hal_network.cpp` — SNTP restricted to `pool.ntp.org` only (upstream default
  also queried a Chinese NTP pool on every boot, unconditionally).
- `firmware/main/main.cpp`, `firmware/main/apps/app_setup/app_setup.cpp` — three M5Stack-cloud-only
  apps and the Setup app's Account/unbind menu removed from the on-device launcher (see "Privacy").
- `firmware/patches/xiaozhi-esp32.patch` — on top of upstream M5Stack's own edits: the privacy-mode
  gate in `Application` (wake word, push-to-talk, chat toggle, and any transition into listening are
  refused while privacy mode is on; the stock idle handler would otherwise re-enable the wake word),
  network-policy checks on OTA, asset, WebSocket and MQTT URLs, and a raw-PCM playback entry point
  used for the settings acknowledgement tone. Regenerate it with `git -C firmware/xiaozhi-esp32 diff`
  after editing the fetched tree, or a fresh fetch will silently drop those changes.

The backend ([`backend/`](backend/README.md)) is a Docker Compose stack on this machine:
`xiaozhi-esp32-server` (voice/OTA, ASR/LLM/VLLM/TTS routing — all pointed at either local providers
or OpenAI, see "Privacy" above), a `piper-tts` sidecar, and a small custom `notify-bridge` service
(MQTT → device WebSocket relay for notifications, including synthesizing and resampling
notification audio). A startup patch (`xiaozhi-server/overrides/patch_chinese_strings.py`) fixes
hardcoded Chinese text and one outbound Chinese network call in core files too large to safely
mirror as whole-file overrides. Home Assistant itself runs externally, reached via its own MCP
Server integration.

The community project [BrettKinny/dotty-stackchan](https://github.com/BrettKinny/dotty-stackchan)
(same upstream, self-hosted voice backend) was useful reference material during planning — see
[`docs/references.md`](docs/references.md) — but wasn't cloned or built on directly.

## Deferred

- Local LLM option (OpenAI is the only backend wired up so far).
