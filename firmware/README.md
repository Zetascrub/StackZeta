# Firmware

The StackZeta firmware is a fork of [`m5stack/StackChan`](https://github.com/m5stack/StackChan)
(MIT, © M5Stack Technology), kept here as one patch rather than a separate fork repository:

| File | Purpose |
|---|---|
| `stackzeta-firmware.patch` | Every StackZeta change (code, config, artwork, and `patches/xiaozhi-esp32.patch` for the fetched voice client) against the pinned upstream commit |
| `setup.sh` | Clones upstream at the pinned commit into `upstream/StackChan/` and applies the patch on a `stackzeta` branch |
| `export-patch.sh` | Regenerates the patch from `upstream/StackChan/` after firmware changes |
| `sdkconfig.defaults.local.example` | Template for your backend's LAN addresses (copied into the tree, git-ignored there) |

Pinned upstream commit: `1b5765599fba8aaad1811d9a79358ccc7051f5f3` (see `UPSTREAM_COMMIT` in `setup.sh`).

## Build

```bash
firmware/setup.sh                    # creates upstream/StackChan/
# edit upstream/StackChan/firmware/sdkconfig.defaults.local: your Docker host's LAN IP
```

Then fetch dependencies, build and flash as in [`docs/toolchain.md`](../docs/toolchain.md).

## Changing the firmware

Work in `upstream/StackChan/` as a normal git tree, commit there, then:

```bash
firmware/export-patch.sh
```

and commit the updated `stackzeta-firmware.patch` here. If you edited the fetched
`firmware/xiaozhi-esp32/` tree, regenerate its patch first (the script warns if it is stale):
`git -C upstream/StackChan/firmware/xiaozhi-esp32 diff > upstream/StackChan/firmware/patches/xiaozhi-esp32.patch`.

To move to a newer upstream, rebase your `upstream/StackChan` branch onto it, update
`UPSTREAM_COMMIT` in `setup.sh`, and re-export.
