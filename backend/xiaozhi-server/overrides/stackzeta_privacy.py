"""StackZeta privacy mode, enforced on the voice server.

The robot enforces privacy mode itself, but its firmware is not fully
observable (see backend/README.md, "Privacy mode"). This is the second line:
while the control panel's privacy_mode is on, the voice server refuses new
voice connections, ignores listen messages, discards buffered audio, and
closes any open voice connection — so no audio reaches ASR or the LLM even
if the device-side gate slips.

The state comes from the notify-bridge's config.json on the shared
stackzeta-state volume (mounted read-only). Reads are cached briefly and
only re-parsed when the file changes. If the file cannot be read, the last
known value is kept.
"""

import asyncio
import json
import os
import time

STATE_PATH = os.environ.get("STACKZETA_STATE_PATH", "/opt/stackzeta-state/config.json")
_RECHECK_SECONDS = 0.25

_checked_at = 0.0
_mtime = None
_active = False


def privacy_active() -> bool:
    global _checked_at, _mtime, _active
    now = time.monotonic()
    if now - _checked_at < _RECHECK_SECONDS:
        return _active
    _checked_at = now
    try:
        mtime = os.stat(STATE_PATH).st_mtime
        if mtime != _mtime:
            with open(STATE_PATH, encoding="utf-8") as f:
                config = json.load(f)
            _active = bool(config.get("device", {}).get("privacy_mode", False))
            _mtime = mtime
    except (OSError, ValueError):
        # Fail closed when the state file exists but can't be read or parsed:
        # a corrupt file must not silently disable privacy enforcement. A
        # genuinely absent file (fresh install, privacy never set) keeps the
        # last value, which starts off.
        if os.path.exists(STATE_PATH):
            _active = True
    return _active


async def watch(conn) -> None:
    """Closes the connection as soon as privacy mode turns on, without
    waiting for the device to send anything (the device can hold an idle
    session open after its own privacy handling)."""
    while getattr(conn.websocket, "close_code", None) is None:
        await asyncio.sleep(0.5)
        if await enforce(conn, "privacy mode switched on"):
            return


async def enforce(conn, reason: str) -> bool:
    """Returns True (after discarding audio and closing the connection) when
    privacy mode is on; callers then drop whatever they were handling."""
    if not privacy_active():
        return False
    if not getattr(conn, "_stackzeta_privacy_closed", False):
        conn._stackzeta_privacy_closed = True
        conn.logger.bind(tag=__name__).info(f"privacy mode: {reason}; closing voice connection")
        conn.reset_audio_states()
        try:
            await conn.websocket.close()
        except Exception:
            pass
    return True
