"""When NOTIFY_WS_TOKEN is set, /ws requires a matching Bearer token."""
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

scratch = tempfile.TemporaryDirectory()
for name in ("STATE_DIR", "IMAGES_DIR", "AUDIO_DIR"):
    os.environ[name] = str(Path(scratch.name) / name)
os.environ["MQTT_HOST"] = "unused.invalid"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import app as bridge


class WsAuthTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bridge.config = deepcopy(bridge.DEFAULT_CONFIG)
        bridge.hub = bridge.DeviceHub()
        self._saved_token = bridge.NOTIFY_WS_TOKEN
        bridge.NOTIFY_WS_TOKEN = "s3cret-token"
        app = web.Application()
        app.router.add_get("/ws", bridge.ws_handler)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        bridge.NOTIFY_WS_TOKEN = self._saved_token
        await self.client.close()

    async def test_missing_token_rejected(self):
        with self.assertRaises(aiohttp.WSServerHandshakeError):
            await self.client.ws_connect("/ws")

    async def test_wrong_token_rejected(self):
        with self.assertRaises(aiohttp.WSServerHandshakeError):
            await self.client.ws_connect("/ws", headers={"Authorization": "Bearer nope"})

    async def test_correct_token_accepted(self):
        ws = await self.client.ws_connect("/ws", headers={"Authorization": "Bearer s3cret-token"})
        self.assertEqual((await ws.receive_json())["type"], "settings")
        await ws.close()


if __name__ == "__main__":
    unittest.main()
