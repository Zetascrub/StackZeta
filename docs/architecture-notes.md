# Architecture notes (upstream/StackChan/firmware)

Based on browsing `upstream/StackChan/firmware/main/` after cloning. Not exhaustive — a map for
finding your way around before making changes, not a substitute for reading the actual code.

## Dependencies (`firmware/repos.json`)

Pulled by `fetch_repos.py`, not vendored in git history:

| Dependency | Branch/pin | Role |
|---|---|---|
| `Forairaaaaa/mooncake` | v2.3.3 | App/window manager framework — this is what the `app_*` modules below plug into |
| `Forairaaaaa/mooncake_log` | v1.5.0 | Logging |
| `Forairaaaaa/smooth_ui_toolkit` | v2.12.0 | UI/animation helpers |
| `78/xiaozhi-esp32` | v2.2.4 (+ local patch) | The voice-assistant client: WebSocket protocol, ASR/TTS plumbing, MCP tool server |
| `bblanchon/ArduinoJson` | v7.4.2 | JSON |
| `espressif/esp-now` | pinned commit | ESP-NOW (remote control) |

## `firmware/main/apps/` — Mooncake apps (think: screens/modes)

- `app_ai_agent` — the xiaozhi voice-assistant integration; probably the main entry point for
  anything related to conversation/voice behavior.
- `app_avatar` — face/avatar rendering.
- `app_dance` — choreographed LED/servo dance routine.
- `app_espnow_ctrl` — handling for the bundled ESP-NOW remote.
- `app_ezdata` — likely local data/settings storage.
- `app_launcher` — the on-device app switcher/home screen.
- `app_setup` — first-boot / provisioning flow (BLE pairing, WiFi setup per `docs/references.md`
  notes on stock firmware behavior).
- `app_template` — presumably a scaffold to copy when adding a new app. **Worth reading first** if
  the plan is "add a new mode/screen" rather than editing an existing one.
- `app_app_center` — app store / online app downloads (factory-firmware feature, may or may not be
  wanted in a custom build).
- `common/` — shared UI bits: status bar, toast, reminder, home indicator, loading page.

## `firmware/main/hal/` — Hardware abstraction

- `hal.cpp` / `hal.h` — top-level HAL surface.
- `hal_servo.cpp` — servo control (the yaw/pitch motors) — **this is where the 5°–85° pitch clamp
  from `docs/hardware.md` should live, if it isn't already enforced here**.
- `hal_imu.cpp`, `hal_head_touch.cpp`, `hal_io_expander.cpp`, `hal_rtc.cpp`, `hal_network.cpp`,
  `hal_ble.cpp`, `hal_espnow.cpp`, `hal_ota.cpp`, `hal_mcp.cpp`, `hal_account.cpp`,
  `hal_app_center.cpp`, `hal_ws_avatar.cpp` — one file per subsystem, does what it says.
- `board/` — board-specific config and drivers: `config.h` (pin definitions — cross-check against
  the pin map in `docs/hardware.md`), `cores3_audio_codec.*`, `stackchan_camera.*`,
  `stackchan_display.*`, `stackchan.cc`.
- `drivers/` — vendored drivers for parts not covered by ESP-IDF or the mooncake stack: BMI270 IMU,
  FTServo (feedback servo protocol), PCF8563 (RTC), PY32IOExpander, Si12T (touch panel).
- `utils/` — `wifi_connect`, `ota`, `motion_detector`, `jpeg_to_image`, `bleprph` (BLE peripheral
  role), `secret_logic` (paired with `firmware/scan_secrets.py` at the repo root — check this
  before committing anything, it suggests there's tooling to catch accidentally-committed secrets
  like WiFi credentials).

## `firmware/main/stackchan/` — Core robot behavior (separate from the app layer)

- `stackchan.cpp`/`.h` — looks like the central orchestrator tying avatar + motion + modifiers
  together.
- `avatar/` — the face rendering itself (skins, decorators) — distinct from `apps/app_avatar`,
  which is presumably the mooncake-app wrapper around this.
- `motion/` — `motion.cpp`, `motion_math.cpp`, `servo.cpp` — the actual kinematics/servo driving
  logic, one layer above `hal/hal_servo.cpp`.
- `modifiers/` — composable behavior modifiers: `blink`, `breath`, `dance`, `head_pet`,
  `idle_expression`, `idle_motion`, `imu`, `speaking`, `timed`. This looks like the natural
  extension point for new idle/reactive behaviors without touching the core state machine.
- `addons/neon_light` — LED ring control.
- `json/`, `utils/` — helpers.

## Other top-level pieces of `m5stack/StackChan` (outside `firmware/`)

- `app/` — the companion mobile app (Flutter — has `pubspec.yaml`, `android/`, `ios/`). Only
  relevant if custom firmware needs to interoperate with BLE provisioning / the phone app.
- `server/` — a Go backend (`server/main.go`, `go.mod`) — M5Stack's own cloud service
  counterpart. Not needed for a self-hosted setup (this is what gets replaced by something like
  `xiaozhi-esp32-server` in the `dotty-stackchan` reference project).
- `remote/` — firmware for the bundled ESP-NOW handheld remote, separate build target.

## Where to point OTA / server config

`firmware/sdkconfig.defaults` is the place to override `CONFIG_OTA_URL` (and similar) at build
time without touching source — see `docs/toolchain.md` and upstream `SETUP.md` reference in
`docs/references.md` for the exact key.
