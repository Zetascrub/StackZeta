# Realtime conversation pilot

The OpenAI Realtime bridge is staged on Unraid for short, spoken coding
conversations. The pilot exposed a speech-turn mismatch and then a speaker
echo loop on the physical device, so the OTA service has been restored to the
original direct desktop voice URL, `ws://192.168.8.10:8000/xiaozhi/v1/`.
The desktop forwarder remains available at `:8012` but is no longer the OTA
route. When configured with `VOICE_ROUTE=realtime`, it adds a server-held
device token and connects to the OpenAI Realtime bridge on Unraid.
The bridge converts 16 kHz Opus from Xiaozhi to 24 kHz PCM and returns 24 kHz
Opus with the Xiaozhi `tts` and `stt` messages. No firmware was changed for
this pilot.

## Live topology

| Component | Host and port | Role |
| --- | --- | --- |
| Xiaozhi OTA and desktop voice service | desktop `:8003` and `:8000` | Supplies the voice URL and remains a fallback |
| `stackzeta-voice-forwarder` | desktop `192.168.8.10:8012` | Staged; currently routes to desktop if used |
| `stackzeta-privacy-gate` | desktop `192.168.8.10:8011` | Authenticated, read-only privacy state |
| `stackzeta-realtime-pilot` | Unraid `192.168.8.239:8010` | OpenAI Realtime conversation bridge |

The OTA `server.websocket` setting is in
`backend/xiaozhi-server/data/.config.yaml`, which is intentionally ignored by
Git. Its current value is the direct desktop `:8000` URL above. The original
config was copied to
`~/.local/share/stackzeta-realtime/xiaozhi.config.before-pilot.yaml` before
this change. A full device flash backup is at
`backups/stackzeta_pre_realtime_20261013.bin`.

The desktop holds the device and privacy token files under
`~/.local/share/stackzeta-realtime/`. Unraid holds its copies under
`/mnt/user/appdata/stackzeta-realtime/secrets/`; the API key stays in a private
read-only file there. Never place a token or API key in firmware or Git. Keep
these ports on the trusted LAN; do not expose them to the internet.

## Behavior and limits

- A failed Unraid bridge connection sends the forwarder to the unchanged
  desktop voice service. If OpenAI cannot be configured at connection time,
  the Unraid bridge can also proxy to that service. A connection lost during a
  conversation ends that session; the next conversation can retry.
- The Realtime path fails closed if the desktop privacy state is enabled,
  missing, or unreadable. It checks before connecting and about every 250 ms
  during a conversation. The desktop service enforces its own privacy state.
- The bridge uses OpenAI server speech detection to end a spoken turn after a
  short pause; it also accepts an explicit device `listen stop`. It waits for
  transcription to check whether a new turn resembles Zeta's previous answer,
  and ignores audio for 1.25 seconds after automatic relistening. It logs a
  numeric time from detected speech end to first returned audio. These echo
  controls are implemented, but echo rejection still needs a physical retest.
  It does not log audio or transcripts. The existing desktop Xiaozhi service
  may have its own transcript logging.
- This path supports conversation only. Home Assistant tools, device MCP
  tools, camera, persistent memory, and desktop personality controls remain
  on the desktop service. They are not available in a successful Realtime
  session. The desktop is still needed for OTA, forwarding, and privacy state,
  so this pilot reduces desktop voice processing but does not make the device
  independent of the desktop.
- Synthetic 16 kHz PCM tests confirmed the transport, automatic turn ending
  without `listen stop`, and desktop routing. The first physical Realtime test
  answered aloud but repeated its own reply, prompting the current desktop
  route and echo guard work. Synthetic tests do
  not prove wake word, speech capture, speaker playback, interruption,
  animation, or perceived latency on the physical device.

## Operate and roll back

Check the local route and privacy gate with `docker ps`, and check the Unraid
container with `ssh root@tower.local docker ps`. The Unraid `/health` endpoint
reports whether its key, token, and privacy configuration are present; it is
not an end-to-end audio test. The smoke client accepts raw signed 16-bit mono
PCM at 16 kHz and reports first returned audio after `listen stop`.

The original OTA voice URL has already been restored and verified through an
OTA response. Reboot the device so it requests OTA configuration again. The
backup at `~/.local/share/stackzeta-realtime/xiaozhi.config.before-pilot.yaml`
remains available. No firmware flash is needed for this rollback.
