"""privacy_active must fail closed on a corrupt state file, off on a missing one."""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PrivacyActiveTest(unittest.TestCase):
    def _load(self, state_path):
        # Reload so module globals (cache, mtime, last value) start fresh.
        os.environ["STACKZETA_STATE_PATH"] = str(state_path)
        import stackzeta_privacy
        return importlib.reload(stackzeta_privacy)

    def _temp_state(self, text):
        path = Path(tempfile.mkstemp(suffix=".json")[1])
        path.write_text(text)
        self.addCleanup(path.unlink)
        return path

    def test_missing_file_is_not_private(self):
        module = self._load(Path(tempfile.gettempdir()) / "stackzeta-absent.json")
        self.assertFalse(module.privacy_active())

    def test_corrupt_existing_file_fails_closed(self):
        module = self._load(self._temp_state("{not json"))
        self.assertTrue(module.privacy_active())

    def test_reads_privacy_value(self):
        self.assertTrue(self._load(self._temp_state(
            json.dumps({"device": {"privacy_mode": True}}))).privacy_active())
        self.assertFalse(self._load(self._temp_state(
            json.dumps({"device": {"privacy_mode": False}}))).privacy_active())


if __name__ == "__main__":
    unittest.main()
