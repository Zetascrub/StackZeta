# StackZeta

Custom firmware + self-hosted backend for an M5Stack StackChan desktop robot.

## Status: v0.1 complete

A privacy-conscious voice assistant, confirmed working end to end:

- **Local ASR/TTS** — FunASR + Piper, both self-hosted; only transcribed text (not audio) leaves
  the LAN, to the LLM.
- **OpenAI LLM** — pluggable backend, config-driven, no firmware changes needed to swap providers.
- **Home Assistant control** — real device control via natural conversation (confirmed: lights on/
  off by area and by name), via HA's own MCP Server integration — no custom integration code.
- **HA-triggered notifications with images** — an HA automation can publish to MQTT and have the
  robot speak and display a notification (with an optional image) on screen, held back until any
  active conversation finishes.
- **Chatbot with expressions** — English persona, emoji-driven face expressions, wake-word or
  press-to-talk activation.
- **Idle sleep** — homes the servos and turns the screen off when idle, wakes on the next wake-word
  or notification.

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
and [`docs/toolchain.md`](docs/toolchain.md) for the build/flash flow. Firmware changes are kept to
`firmware/main/` only (nothing patched in the fetched `xiaozhi-esp32` dependency):

- `firmware/sdkconfig.defaults` — `CONFIG_OTA_URL` and `CONFIG_NOTIFY_WS_URL` point at the
  self-hosted backend instead of M5Stack's cloud.
- `firmware/main/stackchan/notify/` — new: a small WebSocket client (independent of the voice
  connection) for the notification feature.
- `firmware/main/hal/board/stackchan_display.cc` — idle-sleep behavior, hooked into the existing
  `SetStatus()` transitions.

The backend ([`backend/`](backend/README.md)) is a Docker Compose stack on this machine:
`xiaozhi-esp32-server` (voice/OTA, ASR/LLM/TTS routing), a `piper-tts` sidecar, and a small custom
`notify-bridge` service (MQTT → device WebSocket relay for notifications). Home Assistant itself
runs externally, reached via its own MCP Server integration.

The community project [BrettKinny/dotty-stackchan](https://github.com/BrettKinny/dotty-stackchan)
(same upstream, self-hosted voice backend) was useful reference material during planning — see
[`docs/references.md`](docs/references.md) — but wasn't cloned or built on directly.

## Deferred to v0.2

- Natural head motion during active conversation (currently only moves via explicit LLM tool
  calls, no continuous "alive" motion while listening/speaking).
- Local LLM option (OpenAI is the only backend wired up for v0.1).
