# Visual design

StackZeta's device UI follows the Zeta mascot artwork in `/mnt/Storage/Coding/Misc/Mascot/`.
The intentionally small palette keeps the 320×240 display legible:

| Role | Hex | Use |
|---|---:|---|
| Ink | `#03131D` | Screen and avatar background |
| Electric cyan | `#00E5F0` | Face, boot status, system copy |
| Cyan | `#00B8D4` | Borders, status and launcher accent |
| Deep cyan | `#06384A` | Assistant speech bubble |
| Blue | `#0A799B` | User speech bubble |
| Warm white | `#F4F0E4` | Primary text and status icons |
| Amber | `#FFAA24` | Warnings and low battery |

## Assets

- `docs/artwork/stackzeta-boot-source.png` is the editable/high-resolution cold-boot artwork.
- `firmware/main/assets/assets_bin/stackzeta_boot.png` is its 320×240 device derivative.
- `firmware/main/assets/assets_bin/icon_stackzeta.png` is a 112×112 transparent launcher portrait
  derived from `Zeta_Mascot_Headshot_transparent.png`.

The cold-boot code retains a text-only fallback so an application image can still start cleanly
if it is accidentally flashed alongside an older assets partition. A complete flash must include
both `stack-chan.bin` and `generated_assets.bin` for the mascot imagery to appear.

The boot artwork was produced with the built-in image-generation workflow using the supplied
landscape Zeta splash as its visual reference. The launcher portrait is a mechanical resize of the
supplied transparent headshot so the mascot identity remains exact.
