# Plugin overrides

Small, targeted replacements of specific built-in `xiaozhi-esp32-server` plugin files, mounted
over the originals in `docker-compose.yml`. Not a general customization mechanism — only exists
because a few default plugins had hardcoded Chinese-language text that bypasses the LLM's own
(English-instructed) response generation entirely, i.e. `response="..."` strings that get spoken
verbatim regardless of persona/language config:

- **`handle_exit_intent.py`** — English tool description + English fallback farewell (the
  original's fallback only fires if the LLM omits its `say_goodbye` argument, but the Chinese tool
  *description* alone can also bias the LLM into generating a Chinese value for that argument).
  Confirmed (by reading the actual plugin-loader source, `core/providers/tools/server_plugins/plugin_executor.py`)
  that this is one of exactly two plugins (`get_lunar` is the other) force-loaded regardless of
  `Intent.function_call.functions` — everything else really is fully gated by that list.
- **`play_music.py`** — replaced with a stub that declines in English. The original has several
  more hardcoded Chinese strings (song announcements, errors) and expects a local music library we
  haven't set up. (Upstream's own config.yaml comment claims this one also force-loads regardless
  of the functions list, alongside handle_exit_intent — that's stale relative to the actual loader
  source as of this check, only handle_exit_intent/get_lunar actually do. Doesn't change anything
  here since it's fully replaced either way, but don't trust that comment for other plugins without
  checking the loader directly.)
- **`vllm_openai.py`** (mounted over `core/providers/vllm/openai.py`, not `plugins_func/`) — removes
  a hardcoded `"(请使用中文回复)"` ("please reply in Chinese") suffix upstream appends to every
  vision/photo-description question, which forced Chinese output from the camera `Explain()`
  feature regardless of persona/language config. Also see `VLLM.OpenAIVLLM` in `.config.yaml` —
  the module itself was unset upstream and defaulted to a Chinese cloud vision API
  (`ChatGLMVLLM` → open.bigmodel.cn) that the firmware's camera feature actually calls.

`change_role` is handled differently — it's not overridden, just left out of
`Intent.function_call.functions` in `.config.yaml`, since it's a genuinely optional (list-gated)
plugin that can switch the entire system prompt to one of three hardcoded Chinese personas. If a
future version of this project wants role-switching, that'd need its own English-persona rewrite,
not just re-enabling the default.

If xiaozhi-esp32-server updates and any of `handle_exit_intent`/`play_music`'s signatures change
upstream, these overrides need re-syncing by hand — they're plain copies with the Chinese strings
translated, not a diff/patch.

## `patch_chinese_strings.py`

A different mechanism from the whole-file overrides above: this one runs once at container
startup (wired into `command:` in `docker-compose.yml`, before `app.py`) and does small, exact
find/replace patches against the *image's own* copies of a handful of core files — never against
a persisted volume, so it's safe to reapply on every start without needing to be idempotent
against its own prior runs. Used instead of a whole-file override for files too large/central to
safely pin a full copy of (`core/connection.py` is ~1900 lines; upstream changes to it are far more
likely than to a small plugin file, and a stale full copy would silently diverge in behavior, not
just wording).

Found by grepping the entire `core/`/`plugins_func/` tree for non-log, non-comment lines with
Chinese text in `result=`/`response=`/`content=`-shaped patterns, then keeping only what's actually
reachable given this deployment's config (`Intent.function_call.functions` is empty, so most
plugin-specific strings elsewhere in the tree are dead code and deliberately not patched — see the
force-loaded-plugins note above for why `get_lunar`/`handle_exit_intent` are the exception).

The one finding worth calling out specifically: `core/utils/util.py`'s `get_ip_info()` was calling
`https://whois.pconline.com.cn/ipJson.jsp` (a Chinese IP-geolocation service) on every single
conversation's startup — wired in via `agent-base-prompt.txt`'s `{{local_address}}`/
`{{weather_info}}` template variables (`core/utils/prompt_manager.py`), a mechanism entirely
separate from the `get_weather` *plugin* disabled above via the empty functions list. Disabling
that plugin was necessary but not sufficient — this was a second, independent path to the same
kind of data leaving the LAN, on every conversation rather than only when a weather question was
asked, and it was missed in the first pass over this deployment specifically because it isn't a
plugin or a `selected_module` at all. Patched to a no-op (empty location, so the weather lookup it
would otherwise feed never triggers either) rather than pointed at a replacement service.

If the patch script's startup log ever shows `[patch] SKIP ... pattern not found`, upstream changed
that file and the corresponding entry in `PATCHES` needs updating to match — the container still
starts either way (skip, not fail), just with that one string reverted to its original Chinese.
