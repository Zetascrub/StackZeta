# Hardware

## This device

Confirmed by connecting with `esptool` on 2026-09-22:

| | |
|---|---|
| Chip | ESP32-S3 (QFN56, revision v0.2) |
| Flash | 16MB, quad mode |
| PSRAM | 8MB (per CoreS3 spec, not independently verified over USB) |
| USB | Native USB-Serial/JTAG, enumerates as `/dev/ttyACM0` on Linux |
| MAC | `80:45:6b:56:29:28` |

This matches the **M5Stack CoreS3** head unit that the StackChan kit is built on (not the older
Core2, which uses a plain ESP32, not S3).

## CoreS3 head unit

| Component | Spec |
|---|---|
| SoC | ESP32-S3, dual-core Xtensa LX7 @ 240 MHz |
| Flash | 16 MB |
| PSRAM | 8 MB Quad |
| Display | 2.0″ IPS, 320×240, ILI9342C, capacitive touch |
| Camera | GC0308, 0.3 MP |
| Proximity / ambient light | LTR-553ALS-WA |
| IMU | BMI270 (6-axis) + BMM150 (magnetometer, 9-axis combined) |
| Mic codec | ES7210, dual-mic |
| Speaker amp | AW88298, I2S, 1W |
| PMU | AXP2101 |
| Battery (internal) | 500 mAh Li-ion |
| RTC | BM8563 |
| microSD | up to 16GB |
| Wi-Fi | 2.4 GHz only — no 5 GHz |
| BLE | Bluetooth 5 LE |

## StackChan body kit (added on top of CoreS3)

| Component | Spec |
|---|---|
| Head-yaw servo | Feedback servo, 360° continuous |
| Head-pitch servo | SCS0009 feedback servo, 90° range — **clamp to 5°–85° in firmware**, see below |
| LEDs | 12× WS2812C RGB, two rows |
| Touch panel | Si12T driver, 3 zones (separate from CoreS3 display touch) |
| NFC | ST25R3916, I2C `0x50` |
| IR | IRM56384 tx/rx pair |
| Battery monitor | INA226AIDGSR, I2C `0x41` |
| IO expander | PY32L020, I2C `0x6F`/`0x71` — drives IO1, IO14, VM_EN, RGB power |
| Supplementary battery | 550 mAh |
| Remote | ESP-NOW handheld remote, ships in box |

**Pin map (CoreS3 → body):**

| Function | Pins |
|---|---|
| Servo bus (UART) | G6 TX, G7 RX |
| IR | G5 TX, G10 RX |
| I2C (NFC, touch, battery monitor, IO expander) | G11 SCL, G12 SDA |

## Safety constraints for any custom firmware

- **Pitch servo: hard-clamp to 5°–85°.** M5Stack explicitly warns against 0° or 90° — risks gear
  bind/damage on the SCS0009. This must be enforced in software; there's no mechanical stop.
  Check any "park"/"sleep" pose against this before commanding it.
- **No hardware mic mute.** The ES7210 is I2S-connected; muting is a firmware decision, not a
  hardware switch. If adding any always-listening feature, consider a visible LED indicator.
- **Camera has no shutter.** Same story — any capture-on-demand feature should visibly indicate
  when it fires.
- **Do not manually rotate the servos while powered / unsure of servo state** — M5Stack's own
  warning, printed in the upstream README.

## Firmware lineage (don't confuse these)

| Repo | Language | Runs on this hardware? |
|---|---|---|
| [`meganetaaan/stack-chan`](https://github.com/meganetaaan/stack-chan) | TypeScript/JS on Moddable SDK | Yes, but a different, older/original project |
| [`m5stack/StackChan`](https://github.com/m5stack/StackChan) | ESP-IDF C++ | **Yes — this is what's cloned in `upstream/`** |
| [`78/xiaozhi-esp32`](https://github.com/78/xiaozhi-esp32) | ESP-IDF C++ | Runs on the same silicon, but is a generic multi-board voice assistant, not StackChan-specific. `m5stack/StackChan` pulls this in as a pinned dependency (see `firmware/repos.json`) rather than being built on it directly. |

Sources: [docs.m5stack.com/en/StackChan](https://docs.m5stack.com/en/StackChan),
[docs.m5stack.com/en/core/CoreS3](https://docs.m5stack.com/en/core/CoreS3), and
`BrettKinny/dotty-stackchan`'s hardware notes (cross-checked against the above).
