# StackZeta override of the upstream plugins_func/functions/play_music.py:
# the original has several hardcoded Chinese response strings (song
# announcements, error messages) and expects a local music library we
# haven't set up. This plugin may load unconditionally regardless of the
# Intent.function_call.functions list (per upstream's own config.yaml
# comment), so it's replaced outright rather than just left disabled in
# config, in case the LLM ever tries to call it. Mounted over the built-in
# file — see backend/docker-compose.yml.
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

play_music_function_desc = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": "Not available on this device — do not call this.",
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "Unused.",
                }
            },
            "required": ["song_name"],
        },
    },
}


@register_function("play_music", play_music_function_desc, ToolType.SYSTEM_CTL)
async def play_music(conn: "ConnectionHandler", song_name: str):
    return ActionResponse(
        action=Action.RESPONSE,
        result="Music playback is not set up on this device",
        response="Sorry, I don't have any music set up yet.",
    )
