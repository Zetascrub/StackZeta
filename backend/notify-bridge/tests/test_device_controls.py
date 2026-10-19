import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from device_controls import apply_device_controls


class DeviceControlsTest(unittest.TestCase):
    def setUp(self):
        self.config = {"device": {"volume": 70, "brightness": 80, "privacy_mode": False},
                       "notifications": {"dnd": False, "quiet_start": "22:00"},
                       "personality": {"activity": "balanced"},
                       "network_policy": {"enabled": True}}

    def test_dnd_patch_preserves_other_settings(self):
        updated, receipts = apply_device_controls(self.config, {
            "id": "0123456789abcdef", "changes": {"notifications": {"dnd": True}}}, [])
        self.assertTrue(updated["notifications"]["dnd"])
        self.assertEqual(updated["notifications"]["quiet_start"], "22:00")
        self.assertEqual(updated["device"], self.config["device"])
        self.assertFalse(self.config["notifications"]["dnd"])
        self.assertEqual(receipts, ["0123456789abcdef"])

    def test_lost_ack_retry_cannot_undo_later_panel_edit(self):
        message = {"id": "0123456789abcdef", "changes": {"notifications": {"dnd": True}}}
        updated, receipts = apply_device_controls(self.config, message, [])
        updated["notifications"]["dnd"] = False
        retried, receipts = apply_device_controls(updated, message, receipts)
        self.assertFalse(retried["notifications"]["dnd"])
        self.assertEqual(len(receipts), 1)

    def test_invalid_messages_are_atomic(self):
        for changes in [[], {}, {"device": {"privacy_mode": "false"}},
                        {"device": {"volume": True}}, {"device": {"volume": 101}},
                        {"device": {"brightness": 0}}, {"personality": {"activity": "random"}},
                        {"network_policy": {"enabled": False}},
                        {"notifications": {"dnd": True}, "device": {"secret": "value"}}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                apply_device_controls(self.config, {"id": "0123456789abcdef", "changes": changes}, [])
        self.assertFalse(self.config["notifications"]["dnd"])

    def test_receipts_are_bounded(self):
        receipts = [f"{i:016x}" for i in range(64)]
        _, receipts = apply_device_controls(self.config, {
            "id": "ffffffffffffffff", "changes": {"device": {"volume": 0}}}, receipts)
        self.assertEqual(len(receipts), 64)
        self.assertEqual(receipts[-1], "ffffffffffffffff")


if __name__ == "__main__":
    unittest.main()
