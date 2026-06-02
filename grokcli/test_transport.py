"""Tests for the urllib HTTP transport, SSE parsing, and error mapping.

The integration tests run a real ``http.server`` on a loopback port so the full
urllib path (headers, retries, streaming, download) is exercised without mocks.
"""

from __future__ import annotations

import socket
import ssl
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from grokcli import errors
from grokcli.transport import HttpClient, _extract_api_message, _iter_sse


class ExtractMessageTest(unittest.TestCase):
    def test_openai_error_shape(self):
        body = b'{"error": {"message": "Invalid API key.", "code": "invalid_api_key"}}'
        self.assertEqual(_extract_api_message(body), "Invalid API key.")

    def test_plain_text_body(self):
        self.assertEqual(_extract_api_message(b"upstream exploded"), "upstream exploded")

    def test_empty_body(self):
        self.assertEqual(_extract_api_message(b""), "")


class SSEParserTest(unittest.TestCase):
    def _events(self, raw_bytes: bytes):
        return list(_iter_sse(iter(raw_bytes.splitlines(keepends=True))))

    def test_parses_multiple_events_with_types(self):
        raw = b"event: a\ndata: 1\n\nevent: b\ndata: 2\n\n"
        self.assertEqual(
            self._events(raw),
            [{"event": "a", "data": "1"}, {"event": "b", "data": "2"}],
        )

    def test_stops_at_done_sentinel(self):
        raw = b"data: hello\n\ndata: [DONE]\n\ndata: after\n\n"
        self.assertEqual(self._events(raw), [{"event": "", "data": "hello"}])

    def test_ignores_comments_and_joins_multiline_data(self):
        raw = b": heartbeat\ndata: line1\ndata: line2\n\n"
        self.assertEqual(self._events(raw), [{"event": "", "data": "line1\nline2"}])

    def test_flushes_final_event_without_trailing_blank(self):
        raw = b"data: tail"
        self.assertEqual(self._events(raw), [{"event": "", "data": "tail"}])


class Map403Test(unittest.TestCase):
    def setUp(self):
        self.client = HttpClient(max_retries=0)

    def test_quota_keyword_maps_to_quota_error(self):
        err = self.client._map_status(403, b'{"error":{"message":"usage limit reached"}}', {})
        self.assertIsInstance(err, errors.QuotaError)

    def test_billing_keyword_maps_to_quota_error(self):
        err = self.client._map_status(403, b'{"error":{"message":"insufficient credits"}}', {})
        self.assertIsInstance(err, errors.QuotaError)

    def test_generic_403_maps_to_tier_denied(self):
        err = self.client._map_status(403, b'{"error":{"message":"not permitted"}}', {})
        self.assertIsInstance(err, errors.TierDeniedError)

    def test_401_is_auth_relogin(self):
        err = self.client._map_status(401, b'{"error":{"message":"bad token"}}', {})
        self.assertIsInstance(err, errors.AuthError)
        self.assertTrue(err.relogin_required)

    def test_429_includes_retry_after(self):
        err = self.client._map_status(429, b"slow down", {"Retry-After": "12"})
        self.assertIsInstance(err, errors.QuotaError)
        self.assertIn("12", err.hint or "")


# --- integration server ------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # silence
        return

    def _send(self, status, body=b"", content_type="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ok":
            self._send(200, b'{"hello": "world"}')
        elif self.path == "/flaky":
            hits = getattr(self.server, "hits", 0) + 1
            setattr(self.server, "hits", hits)
            if hits < 3:
                self._send(503, b'{"error":{"message":"try later"}}')
            else:
                self._send(200, b'{"ok": true, "attempt": %d}' % hits)
        elif self.path == "/missing":
            self._send(404, b'{"error":{"message":"nope"}}')
        elif self.path == "/stream":
            body = b"event: msg\ndata: one\n\ndata: two\n\ndata: [DONE]\n\n"
            self._send(200, body, content_type="text/event-stream")
        elif self.path == "/file":
            self._send(200, b"BINARYDATA", content_type="application/octet-stream")
        elif self.path == "/gzip":
            import gzip as _gz

            body = _gz.compress(b'{"compressed": true}')
            self._send(200, body, extra={"Content-Encoding": "gzip"})
        elif self.path == "/always503":
            self._send(503, b'{"error":{"message":"down"}}')
        else:
            self._send(404, b'{"error":{"message":"unknown"}}')

    def do_POST(self):
        # Count attempts so a test can assert a POST is NOT retried on 5xx.
        hits = getattr(self.server, "post_hits", 0) + 1
        setattr(self.server, "post_hits", hits)
        self._send(503, b'{"error":{"message":"server boom"}}')


class HttpIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        addr = cls.server.server_address
        cls.base = f"http://{addr[0]}:{addr[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_request_json_success(self):
        client = HttpClient(max_retries=0)
        data = client.request_json("GET", f"{self.base}/ok")
        self.assertEqual(data, {"hello": "world"})

    def test_retry_on_503_then_success(self):
        setattr(self.server, "hits", 0)
        client = HttpClient(max_retries=3)
        # Make backoff instant for the test.
        client._backoff = lambda attempt, headers=None: None  # type: ignore[method-assign]
        data = client.request_json("GET", f"{self.base}/flaky")
        self.assertTrue(data["ok"])
        self.assertEqual(data["attempt"], 3)

    def test_404_raises_api_error(self):
        client = HttpClient(max_retries=0)
        with self.assertRaises(errors.APIError) as ctx:
            client.request_json("GET", f"{self.base}/missing")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_stream_sse_yields_events(self):
        client = HttpClient(max_retries=0)
        events = list(client.stream_sse("GET", f"{self.base}/stream"))
        self.assertEqual(events, [{"event": "msg", "data": "one"}, {"event": "", "data": "two"}])

    def test_download_writes_file_atomically(self):
        client = HttpClient(max_retries=0)
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.bin"
            seen = []
            client.download(f"{self.base}/file", dest, progress=lambda d, t: seen.append((d, t)))
            self.assertEqual(dest.read_bytes(), b"BINARYDATA")
            self.assertTrue(seen)  # progress callback fired

    def test_gzip_response_is_decompressed(self):
        client = HttpClient(max_retries=0)
        self.assertEqual(client.request_json("GET", f"{self.base}/gzip"), {"compressed": True})

    def test_post_is_not_retried_on_5xx(self):
        setattr(self.server, "post_hits", 0)
        client = HttpClient(max_retries=3)
        client._backoff = lambda attempt, headers=None: None  # type: ignore[method-assign]
        with self.assertRaises(errors.APIError):
            client.request_json("POST", f"{self.base}/always503", json_body={"x": 1})
        # Exactly one attempt: a non-idempotent POST must not be replayed.
        self.assertEqual(getattr(self.server, "post_hits"), 1)

    def test_get_retry_exhaustion_raises(self):
        client = HttpClient(max_retries=2)
        client._backoff = lambda attempt, headers=None: None  # type: ignore[method-assign]
        with self.assertRaises(errors.APIError) as ctx:
            client.request_json("GET", f"{self.base}/always503")
        self.assertEqual(ctx.exception.status_code, 503)


class MaskAuthTest(unittest.TestCase):
    def test_none(self):
        from grokcli.transport import _mask_auth

        self.assertEqual(_mask_auth(None), "(none)")

    def test_long_bearer_exposes_at_most_4_chars(self):
        from grokcli.transport import _mask_auth

        masked = _mask_auth("Bearer abcdefghijklmnop")
        self.assertEqual(masked, "Bearer abcd…(16 chars)")
        self.assertNotIn("efgh", masked)

    def test_short_token_fully_redacted(self):
        from grokcli.transport import _mask_auth

        self.assertEqual(_mask_auth("Bearer xy"), "Bearer [REDACTED]")


class MapTransportTest(unittest.TestCase):
    def test_ssl_error_maps_to_network_tls(self):
        client = HttpClient(max_retries=0)
        exc = urllib.error.URLError(ssl.SSLError("handshake failed"))
        mapped = client._map_transport(exc)
        self.assertIsInstance(mapped, errors.NetworkError)
        self.assertEqual(mapped.code, "tls_error")

    def test_socket_timeout_maps_to_timeout(self):
        client = HttpClient(max_retries=0)
        self.assertIsInstance(client._map_transport(socket.timeout()), errors.RequestTimeoutError)

    def test_generic_urlerror_maps_to_network(self):
        client = HttpClient(max_retries=0)
        self.assertIsInstance(client._map_transport(urllib.error.URLError("refused")), errors.NetworkError)


class RedirectStripTest(unittest.TestCase):
    def _redirect(self, from_url, to_url):
        import io
        from http.client import HTTPMessage

        from grokcli.transport import _StripAuthOnCrossHostRedirect

        req = urllib.request.Request(from_url)
        req.add_header("Authorization", "Bearer secret")
        return _StripAuthOnCrossHostRedirect().redirect_request(
            req, io.BytesIO(b""), 302, "Found", HTTPMessage(), to_url
        )

    def test_authorization_stripped_on_cross_host_redirect(self):
        new_req = self._redirect("https://api.x.ai/v1/responses", "https://evil.example/steal")
        assert new_req is not None
        self.assertNotIn("Authorization", new_req.headers)

    def test_authorization_kept_on_same_host_redirect(self):
        new_req = self._redirect("https://api.x.ai/v1/a", "https://api.x.ai/v1/b")
        assert new_req is not None
        self.assertEqual(new_req.headers.get("Authorization"), "Bearer secret")


class ExtractMessageVariantsTest(unittest.TestCase):
    def test_error_as_string(self):
        self.assertEqual(_extract_api_message(b'{"error": "boom"}'), "boom")

    def test_top_level_message(self):
        self.assertEqual(_extract_api_message(b'{"message": "top"}'), "top")

    def test_non_dict_json(self):
        self.assertEqual(_extract_api_message(b"[1, 2, 3]"), "[1, 2, 3]")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
