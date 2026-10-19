"""Small, validated device-originated settings patches with retry deduplication."""

from copy import deepcopy
import re


def apply_device_controls(config: dict, message: dict, receipts: list[str]):
    update_id = message.get("id")
    if not isinstance(update_id, str) or not re.fullmatch(r"[0-9a-f]{16}", update_id):
        raise ValueError("invalid settings update id")
    changes = message.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a nonempty object")
    allowed = {
        "device": {"volume", "brightness", "privacy_mode"},
        "notifications": {"dnd"},
        "personality": {"activity"},
    }
    for section, values in changes.items():
        if section not in allowed or not isinstance(values, dict) or not values:
            raise ValueError("unsupported settings section")
        for key, value in values.items():
            if key not in allowed[section]:
                raise ValueError("unsupported device setting")
            if key in {"privacy_mode", "dnd"}:
                if type(value) is not bool:
                    raise ValueError("toggle must be boolean")
            elif key == "activity":
                if value not in ("quiet", "balanced", "lively"):
                    raise ValueError("invalid activity")
            elif type(value) is not int or not (5 if key == "brightness" else 0) <= value <= 100:
                raise ValueError("invalid control value")
    # An ACK may be lost. Replaying an accepted patch must not undo a later
    # panel change. Receipts are persisted alongside config in the same file.
    if update_id in receipts:
        return deepcopy(config), list(receipts)
    result = deepcopy(config)
    for section, values in changes.items():
        result[section].update(values)
    return result, (receipts + [update_id])[-64:]
