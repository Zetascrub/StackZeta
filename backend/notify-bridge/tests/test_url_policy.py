"""Covers _url_allowed, the host allow/block guard on outbound image fetches."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

scratch = tempfile.TemporaryDirectory()
for name in ("STATE_DIR", "IMAGES_DIR", "AUDIO_DIR"):
    os.environ[name] = str(Path(scratch.name) / name)
os.environ["MQTT_HOST"] = "unused.invalid"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as bridge


class UrlPolicyTest(unittest.TestCase):
    def _policy(self, **overrides):
        policy = {"enabled": True, "allowed_hosts": ["ha.local", "*.ha.local", "api.openai.com"],
                  "blocked_hosts": ["evil.ha.local", "47.113.125.164"]}
        policy.update(overrides)
        bridge.config = {"network_policy": policy}

    def test_allowed_and_unknown_hosts(self):
        self._policy()
        self.assertTrue(bridge._url_allowed("http://ha.local/snap.jpg"))
        self.assertTrue(bridge._url_allowed("http://cam.ha.local/snap.jpg"))  # wildcard
        self.assertFalse(bridge._url_allowed("http://unknown.example/snap.jpg"))

    def test_block_beats_allow(self):
        self._policy()
        self.assertFalse(bridge._url_allowed("http://evil.ha.local/x"))
        self.assertFalse(bridge._url_allowed("http://47.113.125.164/x"))

    def test_wildcard_does_not_match_bare_domain(self):
        self._policy(allowed_hosts=["*.ha.local"])
        self.assertFalse(bridge._url_allowed("http://ha.local/x"))
        self.assertTrue(bridge._url_allowed("http://cam.ha.local/x"))

    def test_bad_scheme_or_host_refused(self):
        self._policy()
        self.assertFalse(bridge._url_allowed("file:///etc/passwd"))
        self.assertFalse(bridge._url_allowed("notaurl"))

    def test_disabled_policy_allows_all(self):
        self._policy(enabled=False)
        self.assertTrue(bridge._url_allowed("http://anything.example/x"))


if __name__ == "__main__":
    unittest.main()
