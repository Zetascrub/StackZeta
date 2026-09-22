# References

## Primary

- [`m5stack/StackChan`](https://github.com/m5stack/StackChan) — official open-source firmware,
  cloned into `upstream/StackChan/`. This is the base to fork/modify.
- [docs.m5stack.com/en/StackChan](https://docs.m5stack.com/en/StackChan) — kit-level hardware docs.
- [docs.m5stack.com/en/core/CoreS3](https://docs.m5stack.com/en/core/CoreS3) — head-unit hardware
  docs.
- [`m5stack/StackChan-BSP`](https://github.com/m5stack/StackChan-BSP) — board support package,
  referenced from the main repo's README, not yet reviewed.
- [ESP-IDF v5.5.4 docs](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html) —
  toolchain reference for the exact pinned version this firmware needs.

## Protocol / voice-assistant layer

- [`78/xiaozhi-esp32`](https://github.com/78/xiaozhi-esp32) — the generic voice-assistant firmware
  StackChan pulls in as a dependency. Useful for understanding the WebSocket protocol, MCP tool
  registration (`McpServer::AddTool`), and emotion/expression channel independent of the
  StackChan-specific app layer.
- [`xinnan-tech/xiaozhi-esp32-server`](https://github.com/xinnan-tech/xiaozhi-esp32-server) — a
  self-hostable server implementation of the counterpart backend (OTA endpoint, WebSocket voice
  I/O) — relevant if the goal is to stop depending on M5Stack's cloud.
- [xiaozhi.dev emotion protocol docs](https://xiaozhi.dev/en/docs/development/emotion/)

## Community reference build (not cloned — read-only reference)

[`BrettKinny/dotty-stackchan`](https://github.com/BrettKinny/dotty-stackchan) — "Dotty": a
self-hosted voice-assistant stack built around a fork of `m5stack/StackChan`
(`BrettKinny/StackChan`, `dotty` branch). Explicitly **not cloned in full** — it's a large
multi-service project (Docker Compose stack: xiaozhi-esp32-server, a local LLM agent, a
"behaviour" FastAPI service, an admin dashboard) well beyond "custom firmware." Worth reading for
ideas, not for reuse wholesale:

- Their `docs/hardware.md` corroborates the pin map and safety limits now in this repo's
  `docs/hardware.md` (independently cross-checked against M5Stack's own docs, not just copied).
- Their `SETUP.md` documents the real-world build/flash flow (Docker + ESP-IDF v5.5.4 container,
  `fetch_repos.py`, `idf.py build`, `idf.py -p /dev/ttyACM0 flash`) — this is what
  `docs/toolchain.md` here is based on.
- Their README explains **why reflashing is necessary at all**: stock StackChan firmware only
  supports BLE provisioning via M5Stack's phone app and registers to M5Stack's cloud — there's no
  SoftAP/captive-portal fallback in the shipped firmware. Anything self-hosted requires flashing
  firmware built from the open-source tree.
- `docs/modes.md`, `docs/protocols.md`, `docs/architecture.md` in that repo go deep on their
  specific state machine and LED contract — that's *their* customization, not stock StackChan
  behavior, so treat it as inspiration rather than documentation of what's currently on this
  device.
- Their firmware fork lags their own "active" branch in places (per their README caveats) — if
  ever pulling from `BrettKinny/StackChan` directly instead of `m5stack/StackChan`, check which
  commit/branch actually has the features referenced in their docs.

## Original (different) project — don't confuse with the above

- [`meganetaaan/stack-chan`](https://github.com/meganetaaan/stack-chan) — the original Stack-chan
  project (Shinya Ishikawa), TypeScript/JS on Moddable SDK. Predates and is unrelated in codebase
  to `m5stack/StackChan`, despite the similar name and same physical hardware target.
