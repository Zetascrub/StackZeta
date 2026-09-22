#!/usr/bin/env python3
"""StackZeta startup patch: replaces hardcoded Chinese text and one outbound
Chinese network call in a handful of core xiaozhi-esp32-server files that
aren't practical to mirror as whole-file overrides (too large/central to
safely pin — see overrides/README.md for the small plugin/provider files
that ARE handled that way instead).

Run once at container startup, before app.py, against the image's own
files — never against a persisted volume, so this is safe to re-run on
every start and doesn't need to be idempotent against its own prior runs.
Each patch is a single exact (old, new) string match; if an upstream image
update changes any of this text, that patch is skipped (with a loud
warning) rather than corrupting the file — the container still starts.

Two categories:
1. An actual outbound network call: get_ip_info() unconditionally posts the
   client's IP to a Chinese IP-geolocation service (whois.pconline.com.cn)
   on every conversation's startup, wired in via a "local_address"/
   "weather_info" prompt-template mechanism that's completely separate
   from (and not covered by) the Intent.function_call allowlist that
   disables the get_weather plugin elsewhere in this config.
2. Hardcoded Chinese strings that get spoken to the user (via TTS) or
   injected into the LLM's own conversation context, found by grepping the
   whole core/ and plugins_func/ tree for non-log, non-comment lines
   containing Chinese characters in result=/response=/content= patterns,
   then keeping only the ones reachable given this deployment's config
   (Intent.function_call.functions is empty, so most plugin-specific
   strings are dead code and are NOT included here — only core
   infrastructure that runs regardless, plus get_lunar/handle_exit_intent,
   the two plugins that force-load regardless of that allowlist).
"""

import sys

PATCHES = [
    (
        "core/utils/util.py",
        '        url = f"https://whois.pconline.com.cn/ipJson.jsp?json=true&ip={ip_addr}"\n'
        "        resp = requests.get(url).json()\n"
        '        ip_info = {"city": resp.get("city")}\n',
        "        # StackZeta: never call out to a Chinese IP-geolocation\n"
        "        # service. No local replacement configured, so this is a\n"
        "        # deliberate no-op rather than a redirect.\n"
        "        ip_info = {}\n",
    ),
    (
        "core/utils/prompt_manager.py",
        'city = ip_info.get("city", "未知位置")',
        'city = ip_info.get("city", "")',
    ),
    (
        "core/utils/prompt_manager.py",
        '        except Exception as e:\n'
        '            self.logger.bind(tag=TAG).error(f"获取位置信息失败: {e}")\n'
        '            return "未知位置"\n',
        '        except Exception as e:\n'
        '            self.logger.bind(tag=TAG).error(f"获取位置信息失败: {e}")\n'
        '            return ""\n',
    ),
    (
        "core/utils/prompt_manager.py",
        'return "天气信息获取失败"',
        'return "Weather information unavailable"',
    ),
    (
        "core/connection.py",
        'ActionResponse(action=Action.ERROR, result="哎呀，网络遇到点问题，请稍后再试下！"),',
        'ActionResponse(action=Action.ERROR, result="Sorry, something went wrong there. Please try again in a moment."),',
    ),
    (
        "core/connection.py",
        'content="[系统提示] 已达到最大工具调用次数限制，请你基于目前已经获取的所有信息，直接给出最终答案。不要再尝试调用任何工具。",',
        'content="[System notice] Maximum tool-call limit reached. Please give your final answer now based on the information already gathered, without calling any more tools.",',
    ),
    (
        "core/connection.py",
        'self.dialogue.put(Message(role="user", content="给我讲个故事吧", is_temporary=True))',
        'self.dialogue.put(Message(role="user", content="Tell me a story", is_temporary=True))',
    ),
    (
        "core/connection.py",
        '\'{"response": "好呀，你想听什么类型的呀？童话、冒险还是搞笑的？选一个我给你开讲~"}\', "name": "direct_answer"},',
        "'{\"response\": \"Sure! What kind would you like \\u2014 fairy tale, adventure, or something funny? Pick one and I will start.\"}', \"name\": \"direct_answer\"},",
    ),
    (
        "core/connection.py",
        'role="tool", tool_call_id=da_tc_id,\n            content="已直接回复", is_temporary=True,',
        'role="tool", tool_call_id=da_tc_id,\n            content="Replied directly", is_temporary=True,',
    ),
    (
        "core/connection.py",
        'self.dialogue.put(Message(role="user", content="拜拜", is_temporary=True))',
        'self.dialogue.put(Message(role="user", content="Bye", is_temporary=True))',
    ),
    (
        "core/connection.py",
        '\'{"say_goodbye": "再见，下次再聊~"}\', "name": "handle_exit_intent"},',
        '\'{"say_goodbye": "Goodbye, talk again soon!"}\', "name": "handle_exit_intent"},',
    ),
    (
        "core/connection.py",
        'role="tool", tool_call_id=tc_id,\n                content="退出意图已处理", is_temporary=True,',
        'role="tool", tool_call_id=tc_id,\n                content="Exit intent handled", is_temporary=True,',
    ),
    (
        "core/connection.py",
        'role="assistant", content="再见，下次再聊~", is_temporary=True,',
        'role="assistant", content="Goodbye, talk again soon!", is_temporary=True,',
    ),
    (
        "core/handle/intentHandler.py",
        'action=Action.ERROR, result="工具调用超时，请一会再试下哈", response="工具调用超时，请一会再试下哈"',
        'action=Action.ERROR, result="The tool call timed out, please try again shortly.", response="The tool call timed out, please try again shortly."',
    ),
    (
        "core/providers/tools/unified_tool_handler.py",
        'response="无法解析函数参数",',
        'response="Could not parse the function arguments.",',
    ),
    (
        "core/providers/tools/unified_tool_handler.py",
        'return ActionResponse(action=Action.NONE, response="无响应")',
        'return ActionResponse(action=Action.NONE, response="No response")',
    ),
    (
        "core/providers/tools/unified_tool_manager.py",
        'response=f"工具 {tool_name} 不存在",',
        'response=f"Tool {tool_name} does not exist.",',
    ),
    (
        "core/providers/tools/unified_tool_manager.py",
        'response=f"工具类型 {tool_type.value} 的执行器未注册",',
        'response=f"No executor registered for tool type {tool_type.value}.",',
    ),
    (
        "core/providers/tools/device_mcp/mcp_executor.py",
        'response="设备端MCP客户端未初始化",',
        'response="Device MCP client not initialized.",',
    ),
    (
        "core/providers/tools/device_mcp/mcp_executor.py",
        'response="设备端MCP客户端未准备就绪",',
        'response="Device MCP client not ready yet.",',
    ),
    (
        "core/providers/tools/server_mcp/mcp_executor.py",
        'response="MCP管理器未初始化",',
        'response="MCP manager not initialized.",',
    ),
]

ROOT = "/opt/xiaozhi-esp32-server"


def main() -> int:
    ok, skipped = 0, 0
    for rel_path, old, new in PATCHES:
        path = f"{ROOT}/{rel_path}"
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print(f"[patch] SKIP {rel_path}: could not read file ({e})", file=sys.stderr)
            skipped += 1
            continue

        count = content.count(old)
        if count == 0:
            print(
                f"[patch] SKIP {rel_path}: pattern not found "
                f"(upstream file likely changed) — leaving original Chinese text in place",
                file=sys.stderr,
            )
            skipped += 1
            continue

        with open(path, "w", encoding="utf-8") as f:
            f.write(content.replace(old, new))
        ok += 1

    print(f"[patch] applied {ok}/{len(PATCHES)} Chinese-string patches ({skipped} skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
