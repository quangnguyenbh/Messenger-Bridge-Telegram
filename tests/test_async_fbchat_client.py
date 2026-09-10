from __future__ import annotations

import asyncio
import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config import AppConfig, load_config  # noqa: E402
from messenger.client import MessengerClient  # noqa: E402
from models import QuoteData, TopicEntry  # noqa: E402


def make_config(**overrides) -> AppConfig:
    values = {
        "log_level": "INFO",
        "telegram_token": "test-token",
        "telegram_group_id": -100123,
        "facebook_cookie": "c_user=1; xs=test; fr=test; datr=test;",
        "data_dir": PROJECT_ROOT / "data",
        "store_path": PROJECT_ROOT / "data" / "bridge-store.json",
        "fbchat_e2ee_bin": None,
        "fbchat_e2ee_device_path": None,
        "fbchat_e2ee_log_level": "none",
        "fbchat_e2ee_memory_only": True,
        "fbchat_enable_e2ee": True,
        "fbchat_e2ee_ready_timeout": 0.5,
        "fbchat_e2ee_send_timeout": 1.0,
        "ignore_self_messages": True,
        "message_cache_limit": 100,
        "telegram_connect_timeout": 1.0,
        "telegram_read_timeout": 1.0,
        "telegram_write_timeout": 1.0,
        "telegram_pool_timeout": 1.0,
        "forward_messenger_reactions": True,
        "forward_typing_activity": False,
        "forward_read_receipts": False,
    }
    values.update(overrides)
    return AppConfig(**values)


class FakeListener:
    def __init__(self, *, ready: bool = True) -> None:
        self.callback = None
        self.ready = ready
        self.stop_event = threading.Event()
        self.stop_calls = 0
        self.wait_calls: list[tuple[float, bool]] = []
        self._bridge = SimpleNamespace(call=AsyncMock())
        self.send_message = AsyncMock(
            return_value={"messageId": "regular-mid", "timestampMs": 123}
        )
        self.send_e2ee_message = AsyncMock(
            return_value={"messageId": "e2ee-mid", "timestampMs": 456}
        )

    def on_message(self, callback):
        self.callback = callback
        return callback

    async def connect_mqtt(self) -> None:
        await asyncio.to_thread(self.stop_event.wait)

    def wait_until_connected(
        self, timeout: float, *, require_e2ee: bool = False
    ) -> bool:
        self.wait_calls.append((timeout, require_e2ee))
        return self.ready

    def stop(self) -> None:
        self.stop_calls += 1
        self.stop_event.set()


class MessengerClientAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_awaits_pypi_session(self) -> None:
        client = MessengerClient(make_config())
        data_fb = {"FacebookID": "42", "cookieFacebook": "c_user=42;"}

        with patch(
            "messenger.client.dataGetHome", AsyncMock(return_value=data_fb)
        ) as data_get_home:
            await client.login()

        data_get_home.assert_awaited_once_with(client.config.facebook_cookie)
        self.assertEqual(client.data_fb, data_fb)
        self.assertEqual(client.self_id, "42")

    async def test_start_waits_for_ready_and_stop_joins_listener(self) -> None:
        client = MessengerClient(make_config())
        client.data_fb = {"FacebookID": "42", "cookieFacebook": "c_user=42;"}
        listener = FakeListener()

        def callback(event) -> None:
            pass

        with patch("messenger.client.listeningE2EEEvent", return_value=listener):
            await client.start(callback)

        self.assertTrue(client.is_running)
        self.assertIs(listener.callback, callback)
        self.assertEqual(listener.wait_calls, [(0.5, True)])

        await client.stop()

        self.assertFalse(client.is_running)
        self.assertEqual(listener.stop_calls, 1)
        self.assertIsNone(client.listener)
        self.assertIsNone(client._listener_task)

    async def test_start_timeout_cleans_up_listener_task(self) -> None:
        client = MessengerClient(make_config())
        client.data_fb = {"FacebookID": "42", "cookieFacebook": "c_user=42;"}
        listener = FakeListener(ready=False)

        with patch("messenger.client.listeningE2EEEvent", return_value=listener):
            with self.assertRaisesRegex(TimeoutError, "did not become ready"):
                await client.start(lambda event: None)

        self.assertFalse(client.is_running)
        self.assertEqual(listener.stop_calls, 1)
        self.assertIsNone(client.listener)
        self.assertIsNone(client._listener_task)

    async def test_send_text_awaits_regular_and_e2ee_methods(self) -> None:
        client = MessengerClient(make_config())
        listener = FakeListener()
        client.listener = listener

        regular = TopicEntry(
            topic_id=1,
            messenger_id="100",
            transport="regular",
            name="Regular",
            thread_id="100",
        )
        regular_result = await client.send_text(regular, " hello ")

        listener.send_message.assert_awaited_once_with(100, "hello", reply_to_id="")
        self.assertEqual(regular_result["payload"]["messageID"], "regular-mid")

        e2ee = TopicEntry(
            topic_id=2,
            messenger_id="42@msgr",
            transport="e2ee",
            name="E2EE",
            chat_jid="42@msgr",
        )
        quote = QuoteData(
            message_id="quoted-mid",
            transport="e2ee",
            messenger_id="42@msgr",
            sender_jid="42@msgr",
        )
        e2ee_result = await client.send_text(e2ee, " world ", quote)

        listener.send_e2ee_message.assert_awaited_once_with(
            "42@msgr",
            "world",
            reply_to_id="quoted-mid",
            reply_to_sender_jid="42@msgr",
        )
        self.assertEqual(e2ee_result["payload"]["messageID"], "e2ee-mid")

    async def test_reaction_awaits_async_bridge_rpc(self) -> None:
        client = MessengerClient(make_config())
        bridge_call = AsyncMock(return_value={"messageId": "reaction-mid"})
        client.listener = SimpleNamespace(_bridge=SimpleNamespace(call=bridge_call))
        quote = QuoteData(
            message_id="target-mid",
            transport="regular",
            messenger_id="100",
            thread_id="100",
        )

        result = await client.send_reaction(quote, "👍")

        bridge_call.assert_awaited_once_with(
            "sendReaction",
            {"threadId": 100, "messageId": "target-mid", "emoji": "👍"},
            timeout=60.0,
        )
        self.assertEqual(result["payload"]["messageID"], "reaction-mid")

    async def test_user_lookup_awaits_async_feature(self) -> None:
        client = MessengerClient(make_config())
        client.data_fb = {"FacebookID": "42", "cookieFacebook": "c_user=42;"}

        with patch(
            "messenger.client.get_user_info",
            AsyncMock(return_value={"nameUser": "Nguyễn Văn A"}),
        ) as lookup:
            name = await client.resolve_user_name("100")

        lookup.assert_awaited_once_with(client.data_fb, "100")
        self.assertEqual(name, "Nguyễn Văn A")


class PackageOnlyConfigTests(unittest.TestCase):
    def test_local_fbchat_source_settings_are_ignored(self) -> None:
        env = {
            "TG_TOKEN": "test-token",
            "TG_GROUP_ID": "-100123",
            "FACEBOOK_COOKIE": "c_user=1; xs=test; fr=test; datr=test;",
            "FBCHAT_V2_USE_PACKAGE": "0",
            "FBCHAT_V2_SRC_PATH": "../fbchat-v2/src",
        }

        with patch("config._load_dotenv"), patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertFalse(hasattr(config, "fbchat_v2_src_path"))
        self.assertIsNone(config.fbchat_e2ee_bin)
        self.assertEqual(config.fbchat_e2ee_ready_timeout, 90.0)


if __name__ == "__main__":
    unittest.main()
