"""Tests for GrokClient bearer injection and reactive refresh-on-401 retry."""

from __future__ import annotations

import unittest
from unittest import mock

from grokcli import client as client_mod
from grokcli.client import GrokClient
from grokcli.config import resolve_settings
from grokcli.errors import AuthError, APIError


def _settings():
    return resolve_settings({}, env={}, file_cfg={})


class GrokClientTest(unittest.TestCase):
    def setUp(self):
        self.settings = _settings()

    def _client_with_creds(self):
        client = GrokClient(self.settings, env={})
        self.resolve = mock.patch.object(
            client_mod.tokens,
            "resolve_runtime_credentials",
            return_value={"access_token": "TOK", "token_type": "Bearer", "base_url": "https://api.x.ai/v1", "account": {}},
        )
        return client

    def test_request_json_injects_bearer(self):
        client = self._client_with_creds()
        with self.resolve:
            client.http = mock.Mock()
            client.http.request_json.return_value = {"ok": True}
            out = client.request_json("POST", "/responses", json_body={"a": 1})
        self.assertEqual(out, {"ok": True})
        _, kwargs = client.http.request_json.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer TOK")

    def test_refresh_and_retry_once_on_401(self):
        client = GrokClient(self.settings, env={})
        client.http = mock.Mock()
        client.http.request_json.side_effect = [AuthError("expired", status_code=401), {"ok": True}]
        with mock.patch.object(
            client_mod.tokens,
            "resolve_runtime_credentials",
            return_value={"access_token": "TOK", "token_type": "Bearer", "base_url": "https://api.x.ai/v1", "account": {}},
        ) as resolve:
            out = client.request_json("GET", "/models")
        self.assertEqual(out, {"ok": True})
        self.assertEqual(client.http.request_json.call_count, 2)
        # Two resolves: initial + forced refresh.
        self.assertEqual(resolve.call_count, 2)
        self.assertTrue(resolve.call_args_list[1].kwargs["force_refresh"])

    def test_non_401_error_does_not_retry(self):
        client = GrokClient(self.settings, env={})
        client.http = mock.Mock()
        client.http.request_json.side_effect = APIError("server", status_code=500)
        with mock.patch.object(
            client_mod.tokens,
            "resolve_runtime_credentials",
            return_value={"access_token": "TOK", "token_type": "Bearer", "base_url": "https://api.x.ai/v1", "account": {}},
        ):
            with self.assertRaises(APIError):
                client.request_json("GET", "/models")
        self.assertEqual(client.http.request_json.call_count, 1)

    def test_url_join(self):
        client = GrokClient(self.settings, env={})
        self.assertEqual(client._url("/responses"), "https://api.x.ai/v1/responses")
        self.assertEqual(client._url("responses"), "https://api.x.ai/v1/responses")

    def test_url_absolute_passes_through(self):
        # Hardcoded service constants (billing proxy) bypass the base URL join.
        client = GrokClient(self.settings, env={})
        self.assertEqual(client._url("https://cli-chat-proxy.grok.com/v1/billing"), "https://cli-chat-proxy.grok.com/v1/billing")

    def test_stream_refreshes_and_reopens_on_401(self):
        client = GrokClient(self.settings, env={})
        calls = {"n": 0}

        def stream_side_effect(method, url, *, json_body=None, headers=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise AuthError("expired", status_code=401)
            return iter([{"event": "", "data": "ok"}])

        http_mock = mock.Mock()
        http_mock.stream_sse.side_effect = stream_side_effect
        client.http = http_mock
        with mock.patch.object(
            client_mod.tokens,
            "resolve_runtime_credentials",
            return_value={"access_token": "T", "token_type": "Bearer", "base_url": "https://api.x.ai/v1", "account": {}},
        ) as resolve:
            events = list(client.stream("POST", "/responses", json_body={"a": 1}))
        self.assertEqual(events, [{"event": "", "data": "ok"}])
        self.assertEqual(calls["n"], 2)
        self.assertTrue(resolve.call_args_list[1].kwargs["force_refresh"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
