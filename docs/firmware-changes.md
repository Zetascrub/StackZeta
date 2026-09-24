# Firmware and backend changes, in detail

How StackZeta differs from upstream, file by file. For the big picture, see the
[README](../README.md); for building, [`toolchain.md`](toolchain.md).

The firmware is a light fork of [`m5stack/StackChan`](https://github.com/m5stack/StackChan) (ESP-IDF
C++, bundles [`xiaozhi-esp32`](https://github.com/78/xiaozhi-esp32) as the voice client) — see
[`docs/architecture-notes.md`](architecture-notes.md) for how the upstream code is organized,
and [`docs/toolchain.md`](toolchain.md) for the build/flash flow. This repo carries the firmware
as [`firmware/stackzeta-firmware.patch`](../firmware/README.md) against a pinned upstream commit;
`firmware/setup.sh` recreates the tree in `upstream/StackChan/`, and the paths below are relative
to that tree. Firmware changes live in `firmware/main/`, with one deliberate exception: `firmware/patches/xiaozhi-esp32.patch` (applied by
`fetch_repos.py`) carries small edits to the fetched `xiaozhi-esp32` dependency that cannot be made
from outside it — see the last bullet below:

- `firmware/sdkconfig.defaults` — `CONFIG_OTA_URL` and `CONFIG_NOTIFY_WS_URL` point at the
  self-hosted backend instead of M5Stack's cloud; `CONFIG_STACKCHAN_SERVER_URL` overridden to an
  inert value (defense-in-depth — see the README's privacy section).
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
  apps and the Setup app's Account/unbind menu removed from the on-device launcher (see the README's privacy section).
- `firmware/patches/xiaozhi-esp32.patch` — on top of upstream M5Stack's own edits: the privacy-mode
  gate in `Application` (wake word, push-to-talk, chat toggle, and any transition into listening are
  refused while privacy mode is on; the stock idle handler would otherwise re-enable the wake word),
  network-policy checks on OTA, asset, WebSocket and MQTT URLs, and a raw-PCM playback entry point
  used for the settings acknowledgement tone. Regenerate it with `git -C firmware/xiaozhi-esp32 diff`
  after editing the fetched tree, or a fresh fetch will silently drop those changes.

The backend ([`backend/`](../backend/README.md)) is a Docker Compose stack on this machine:
`xiaozhi-esp32-server` (voice/OTA, ASR/LLM/VLLM/TTS routing — all pointed at either local providers
or OpenAI, see the README's privacy section), a `piper-tts` sidecar, and a small custom `notify-bridge` service
(MQTT → device WebSocket relay for notifications, including synthesizing and resampling
notification audio). A startup patch (`xiaozhi-server/overrides/patch_chinese_strings.py`) fixes
hardcoded Chinese text and one outbound Chinese network call in core files too large to safely
mirror as whole-file overrides. Home Assistant itself runs externally, reached via its own MCP
Server integration.

The community project [BrettKinny/dotty-stackchan](https://github.com/BrettKinny/dotty-stackchan)
(same upstream, self-hosted voice backend) was useful reference material during planning — see
[`docs/references.md`](references.md) — but wasn't cloned or built on directly.
