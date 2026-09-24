#!/usr/bin/env python3
"""StackZeta startup patch: applies keys from the control panel
(core/utils/stackzeta_secrets.py, mounted separately) over the voice
server's config. Fails open with a loud warning: if a pattern no longer
matches, the keys in .config.yaml / .mcp_server_settings.json still apply.
"""

import sys

ROOT = "/opt/xiaozhi-esp32-server"

PATCHES = [
    (
        "config/config_loader.py",
        "        config = merge_configs(default_config, custom_config)\n",
        "        config = merge_configs(default_config, custom_config)\n"
        "        from core.utils.stackzeta_secrets import overlay_config\n"
        "        config = overlay_config(config)\n",
    ),
    (
        "core/providers/tools/server_mcp/mcp_manager.py",
        '            return config.get("mcpServers", {})\n',
        "            from core.utils.stackzeta_secrets import overlay_mcp_servers\n"
        '            return overlay_mcp_servers(config.get("mcpServers", {}))\n',
    ),
]


def main() -> int:
    applied = 0
    for rel_path, old, new in PATCHES:
        path = f"{ROOT}/{rel_path}"
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print(f"[secrets] WARNING {rel_path}: {e}; panel keys not applied here", file=sys.stderr)
            continue
        if content.count(new) == 1:
            applied += 1  # already patched (container restarted, not recreated)
            continue
        if content.count(old) != 1:
            print(f"[secrets] WARNING {rel_path}: pattern not found; panel keys not applied here",
                  file=sys.stderr)
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.replace(old, new))
        applied += 1
    print(f"[secrets] applied {applied}/{len(PATCHES)} control-panel key patches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
