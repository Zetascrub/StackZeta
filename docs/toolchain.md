# Toolchain

The StackChan firmware is an **ESP-IDF** project (CMake-based), not Arduino IDE or PlatformIO. It
requires a specific ESP-IDF version, pinned in `upstream/StackChan/firmware/README.md` and
reflected in `sdkconfig.defaults`:

> **ESP-IDF v5.5.4**

## What's already on this machine

- `esptool` (v5.4.0) — installed at `~/.local/bin/`, used for the flash backup/restore.
- `platformio` / `pio` — installed but **not the right fit** for this project (StackChan is plain
  ESP-IDF + CMake, not a PlatformIO project). Keep in mind in case it's useful for something else.
- If another ESP-IDF version is installed locally for other projects, don't `. export.sh` it for
  StackChan builds — StackChan needs 5.5.4 and may silently build against the wrong SDK.
- Docker image `espressif/idf:v5.5.4` — pulled locally as part of this prep. This is the
  recommended way to build, per upstream's own README, since it sidesteps the version-pinning
  problem above entirely.

## Build flow (Docker-based, matches upstream instructions)

From the repo root:

```bash
# Fetch pinned dependencies (mooncake UI lib, xiaozhi-esp32, ArduinoJson, esp-now, ...)
docker run --rm -it -v "$PWD/upstream/StackChan":/project -w /project/firmware \
  espressif/idf:v5.5.4 \
  python3 fetch_repos.py

# Build
docker run --rm -it -v "$PWD/upstream/StackChan":/project -w /project/firmware \
  espressif/idf:v5.5.4 \
  idf.py build

# Flash (device must be plugged in and container given device passthrough)
docker run --rm -it --device=/dev/ttyACM0 \
  -v "$PWD/upstream/StackChan":/project -w /project/firmware \
  espressif/idf:v5.5.4 \
  idf.py -p /dev/ttyACM0 flash
```

`fetch_repos.py` reads `firmware/repos.json` and clones each pinned dependency into
`firmware/components/` / `firmware/xiaozhi-esp32/`, then applies
`firmware/patches/xiaozhi-esp32.patch`. Re-run it after any change to `repos.json`, or after a
clean clone.

## Native (non-Docker) alternative

Possible via the [ESP-IDF installer](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/get-started/)
targeting v5.5.4 specifically, installed alongside (not replacing) the existing 5.4.2 install —
ESP-IDF supports multiple side-by-side versions via `idf-env`/separate install dirs, each with its
own `export.sh`. Docker is simpler here since it avoids touching the existing 5.4.2 setup at all;
switch to native only if build performance or IDE integration (e.g. VS Code ESP-IDF extension)
becomes a priority.

## Flashing target

- Port: `/dev/ttyACM0` (native USB-Serial/JTAG on ESP32-S3 — no separate USB-UART bridge chip, no
  driver install needed on Linux).
- Your user needs serial-port access (on most Linux distros, membership of the `dialout` group).
- Flash size: 16MB (`CONFIG_ESPTOOLPY_FLASHSIZE_16MB` in `sdkconfig.defaults` — matches what
  `esptool flash_id` reported).

## Before touching real firmware

Do one build+flash of the **unmodified** upstream tree first (`upstream/StackChan/firmware` as
cloned, no edits) to confirm the whole toolchain works end to end, before making any custom
changes. A full flash backup already exists in [`backups/`](../backups/README.md) as a fallback if
anything goes wrong.

## `sdkconfig` drift

`sdkconfig.defaults` only seeds keys that are **missing** from `firmware/sdkconfig`; it never
overrides a value an existing `sdkconfig` already has. A local `sdkconfig` generated before a
default was added keeps the old value silently. This happened with `CONFIG_STACKCHAN_SERVER_URL`,
which stayed at M5Stack's `http://47.113.125.164:12800` (China) despite the inert override in
`sdkconfig.defaults` (unused code at the time, so never actually called). After changing
`sdkconfig.defaults`, check that the value really took:

```bash
grep -E "OTA_URL|NOTIFY_WS_URL|STACKCHAN_SERVER_URL" upstream/StackChan/firmware/sdkconfig
```

and audit the built binary itself for hosts, which is the ground truth for what can be contacted:

```bash
strings -n 6 upstream/StackChan/firmware/build/stack-chan.bin | grep -oE "(https?|wss?|mqtts?)://[^ \"]+" | sort -u
```

