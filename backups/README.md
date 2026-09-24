# Firmware backups

Full raw flash dumps taken with `esptool` before any custom firmware is flashed to the device.
Always take a fresh one of these before flashing anything new — it's the only way back to
stock/known-good if a custom build bricks WiFi provisioning, OTA, or anything else stock firmware
depended on.

## Current backup

- `stackchan_firmware_backup_20260922.bin` — full 16MB flash dump, taken 2026-09-22 from the
  as-purchased device (stock M5Stack firmware, never flashed) over `/dev/ttyACM0`.
  - Chip: ESP32-S3
  - SHA-256: `6aa988a8bb4f618b73475457d4fc2f1312be56ad196f26f245ce1a693297d9ef`
  - Taken with: `esptool.py --port /dev/ttyACM0 --baud 921600 read_flash 0 0x1000000 <file>`

This file is **not committed to git** (see `.gitignore`) — it's 16MB of binary and belongs on disk,
not in version-control history. Keep a copy somewhere durable outside this repo too (it's the only
copy of the factory-provisioned state, including any per-device secrets baked into the stock image).

## How to restore

```bash
esptool.py --port /dev/ttyACM0 write_flash 0x0 backups/stackchan_firmware_backup_20260922.bin
```

## How to take a new backup

```bash
esptool.py --port /dev/ttyACM0 --baud 921600 read_flash 0 0x1000000 \
  backups/stackchan_firmware_backup_$(date +%Y%m%d).bin
sha256sum backups/stackchan_firmware_backup_$(date +%Y%m%d).bin
```

Flash size was confirmed via `esptool.py --port /dev/ttyACM0 flash_id` (16MB, quad-mode). Re-check
this if you ever point the same command at a different StackChan unit.
