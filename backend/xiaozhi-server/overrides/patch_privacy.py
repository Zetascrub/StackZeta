#!/usr/bin/env python3
"""StackZeta startup patch: wires server-side privacy enforcement
(core/utils/stackzeta_privacy.py, mounted separately) into the voice
server's three entry points for device audio.

Unlike patch_chinese_strings.py, this fails closed: if any pattern no
longer matches (an upstream image update changed the code), it exits
non-zero and the container does not start, rather than silently running
without privacy enforcement.
"""

import sys

ROOT = "/opt/xiaozhi-esp32-server"
IMPORT = (
    "from core.utils.stackzeta_privacy import enforce as stackzeta_privacy_enforce\n"
    "from core.utils.stackzeta_privacy import watch as stackzeta_privacy_watch\n"
)

PATCHES = [
    # New voice connections are refused outright while privacy is on.
    (
        "core/connection.py",
        "            # 认证通过,继续处理\n"
        "            self.websocket = ws\n",
        "            # 认证通过,继续处理\n"
        "            self.websocket = ws\n"
        "            if await stackzeta_privacy_enforce(self, \"refusing new connection\"):\n"
        "                return\n"
        "            asyncio.create_task(stackzeta_privacy_watch(self))\n",
    ),
    # Device audio frames are dropped (and the connection closed).
    (
        "core/connection.py",
        "        elif isinstance(message, bytes):\n"
        "            if self.vad is None or self.asr is None:\n"
        "                return\n",
        "        elif isinstance(message, bytes):\n"
        "            if await stackzeta_privacy_enforce(self, \"dropping device audio\"):\n"
        "                return\n"
        "            if self.vad is None or self.asr is None:\n"
        "                return\n",
    ),
    # listen start/stop are ignored, so buffered audio is never transcribed.
    (
        "core/handle/textHandler/listenMessageHandler.py",
        "    async def handle(self, conn: \"ConnectionHandler\", msg_json: Dict[str, Any]) -> None:\n",
        "    async def handle(self, conn: \"ConnectionHandler\", msg_json: Dict[str, Any]) -> None:\n"
        "        if await stackzeta_privacy_enforce(conn, \"ignoring listen message\"):\n"
        "            return\n",
    ),
]

IMPORT_ANCHORS = {
    "core/connection.py": "import opuslib_next\n",
    "core/handle/textHandler/listenMessageHandler.py": "import asyncio\n",
}


def main() -> int:
    contents = {}
    for rel_path, old, new in PATCHES:
        path = f"{ROOT}/{rel_path}"
        content = contents.get(rel_path)
        if content is None:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            # Idempotent: `docker compose restart` (and a host reboot) reuse
            # the container, whose files were already patched last start.
            if IMPORT not in content:
                anchor = IMPORT_ANCHORS[rel_path]
                if content.count(anchor) != 1:
                    print(f"[privacy] FAIL {rel_path}: import anchor not found", file=sys.stderr)
                    return 1
                content = content.replace(anchor, anchor + IMPORT)
        if content.count(new) == 1:
            contents[rel_path] = content
            continue
        if content.count(old) != 1:
            print(f"[privacy] FAIL {rel_path}: pattern not found exactly once", file=sys.stderr)
            return 1
        contents[rel_path] = content.replace(old, new)

    for rel_path, content in contents.items():
        with open(f"{ROOT}/{rel_path}", "w", encoding="utf-8") as f:
            f.write(content)
    print(f"[privacy] applied {len(PATCHES)} privacy enforcement patches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
