"""Run with the notify-bridge image's dependencies, isolated from live state."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

scratch = tempfile.TemporaryDirectory()
for name in ("STATE_DIR", "IMAGES_DIR", "AUDIO_DIR"):
    os.environ[name] = str(Path(scratch.name) / name)
os.environ["MQTT_HOST"] = "unused.invalid"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import app as bridge


class BridgeProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bridge.config = deepcopy(bridge.DEFAULT_CONFIG)
        bridge.hub = bridge.DeviceHub()
        app = web.Application()
        app.router.add_get('/ws', bridge.ws_handler)
        app.router.add_put('/api/config', bridge.config_put_handler)
        app.router.add_get('/api/config', bridge.config_get_handler)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.ws = await self.client.ws_connect('/ws')
        self.assertEqual((await self.receive())["type"], "settings")

    async def asyncTearDown(self):
        await self.ws.close()
        await self.client.close()

    async def receive(self):
        return await asyncio.wait_for(self.ws.receive_json(), 2)

    async def test_roundtrip_reconnect_and_unrelated_panel_save(self):
        update = {"type": "settings_update", "id": "0123456789abcdef",
                  "changes": {"notifications": {"dnd": True}, "device": {"privacy_mode": True}}}
        await self.ws.send_json(update)
        ack = await self.receive()
        self.assertEqual(ack["accepted_update"], update["id"])
        self.assertTrue(ack["settings"]["notifications"]["dnd"])
        self.assertNotIn("_device_receipts", ack["settings"])
        response = await self.client.put('/api/config', json={"device": {"volume": 40}})
        self.assertEqual(response.status, 200)
        pushed = await self.receive()
        self.assertTrue(pushed["settings"]["notifications"]["dnd"])
        self.assertTrue(pushed["settings"]["device"]["privacy_mode"])
        self.assertEqual(pushed["settings"]["device"]["volume"], 40)
        # Later deliberate panel edit wins over retransmission of a lost ACK.
        await self.client.put('/api/config', json={"notifications": {"dnd": False}})
        await self.receive()
        bridge.config = json.loads(bridge.CONFIG_PATH.read_text())  # simulate restart persistence
        await self.ws.close()
        self.ws = await self.client.ws_connect('/ws')
        await self.receive()
        await self.ws.send_json(update)
        self.assertFalse((await self.receive())["settings"]["notifications"]["dnd"])

    async def test_bad_frames_do_not_break_connection_or_apply_partial_changes(self):
        await self.ws.send_json([])
        await self.ws.send_json({"type": "settings_update", "id": "0123456789abcdef",
                                 "changes": {"device": {"privacy_mode": "false"}}})
        await self.ws.send_json({"type": "settings_update", "id": "1111111111111111",
                                 "changes": {"device": {"brightness": 55}}})
        ack = await self.receive()
        self.assertEqual(ack["accepted_update"], "1111111111111111")
        self.assertFalse(ack["settings"]["device"]["privacy_mode"])
        self.assertEqual(ack["settings"]["device"]["brightness"], 55)


if __name__ == '__main__':
    unittest.main()
