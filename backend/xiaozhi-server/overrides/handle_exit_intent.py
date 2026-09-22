# StackZeta override of the upstream plugins_func/functions/handle_exit_intent.py:
# the tool description and fallback farewell were hardcoded Chinese strings that
# could leak into TTS output (the description alone can bias the LLM's generated
# say_goodbye text; the fallback fires outright if the LLM omits the argument).
# Mounted over the built-in file — see backend/docker-compose.yml.
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

handle_exit_intent_function_desc = {
    "type": "function",
    "function": {
        "name": "handle_exit_intent",
        "description": "Call this when the user wants to end the conversation or exit.",
        "parameters": {
            "type": "object",
            "properties": {
                "say_goodbye": {
                    "type": "string",
                    "description": "A short, friendly farewell to the user, in English.",
                }
            },
            "required": ["say_goodbye"],
        },
    },
}


@register_function(
    "handle_exit_intent", handle_exit_intent_function_desc, ToolType.SYSTEM_CTL
)
def handle_exit_intent(conn: "ConnectionHandler", say_goodbye: str | None = None):
    try:
        if say_goodbye is None:
            say_goodbye = "Goodbye, have a great day!"
        if not conn.close_after_chat:
            conn.close_after_chat = True
        logger.bind(tag=TAG).info(f"Exit intent handled: {say_goodbye}")
        return ActionResponse(
            action=Action.RESPONSE, result="Exit intent handled", response=say_goodbye
        )
    except Exception as e:
        logger.bind(tag=TAG).error(f"Error handling exit intent: {e}")
        return ActionResponse(
            action=Action.NONE, result="Failed to handle exit intent", response=""
        )
