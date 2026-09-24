"""Keys set in the StackZeta control panel (Keys tab), applied over the
voice server's own config files.

The notify-bridge stores secrets in secrets.json on the stackzeta-state
volume (mounted read-only here). When a value is present it replaces:
- openai_api_key: the api_key of the selected LLM and VLLM modules, when
  they are OpenAI-type providers (read once at startup, so a new key needs
  a voice-server restart);
- ha_token: the Home Assistant MCP server's token in
  .mcp_server_settings.json (re-read per connection, so it applies live).
Values in .config.yaml / .mcp_server_settings.json remain the fallback.
"""

import json
import os

SECRETS_PATH = os.environ.get("STACKZETA_SECRETS_PATH", "/opt/stackzeta-state/secrets.json")
HA_MCP_SERVER_NAME = os.environ.get("STACKZETA_HA_MCP_SERVER", "Home Assistant")


def _secrets() -> dict:
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def overlay_config(config: dict) -> dict:
    key = _secrets().get("openai_api_key")
    if not key:
        return config
    selected = config.get("selected_module", {})
    for section in ("LLM", "VLLM"):
        entry = config.get(section, {}).get(selected.get(section, ""), {})
        if isinstance(entry, dict) and entry.get("type") == "openai":
            entry["api_key"] = key
    return config


def overlay_mcp_servers(servers: dict) -> dict:
    token = _secrets().get("ha_token")
    server = servers.get(HA_MCP_SERVER_NAME) if token else None
    if not isinstance(server, dict):
        return servers
    if isinstance(server.get("env"), dict):
        server["env"]["API_ACCESS_TOKEN"] = token
    if "API_ACCESS_TOKEN" in server:
        server["API_ACCESS_TOKEN"] = token
    if "url" in server:
        server.setdefault("headers", {})["Authorization"] = f"Bearer {token}"
    return servers
