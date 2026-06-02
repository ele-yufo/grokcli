"""Tests for the loopback callback server, paste parsing, and remote detection."""

from __future__ import annotations

import threading
import unittest
import urllib.request

from grokcli.auth import loopback


class ParsePastedCallbackTest(unittest.TestCase):
    def test_full_url(self):
        r = loopback.parse_pasted_callback("http://127.0.0.1:56121/callback?code=abc&state=xyz")
        self.assertEqual(r["code"], "abc")
        self.assertEqual(r["state"], "xyz")

    def test_bare_query_fragment(self):
        r = loopback.parse_pasted_callback("?code=abc&state=xyz")
        self.assertEqual(r["code"], "abc")

    def test_query_without_question_mark(self):
        r = loopback.parse_pasted_callback("code=abc&state=xyz")
        self.assertEqual(r["code"], "abc")

    def test_bare_code(self):
        r = loopback.parse_pasted_callback("just-a-code")
        self.assertEqual(r["code"], "just-a-code")
        self.assertIsNone(r["state"])

    def test_error_callback(self):
        r = loopback.parse_pasted_callback("?error=access_denied&error_description=nope")
        self.assertEqual(r["error"], "access_denied")
        self.assertEqual(r["error_description"], "nope")

    def test_empty(self):
        self.assertEqual(loopback.parse_pasted_callback("  ")["code"], None)


class RemoteSessionTest(unittest.TestCase):
    def test_ssh_is_remote(self):
        self.assertTrue(loopback.is_remote_session({"SSH_CLIENT": "1.2.3.4"}))

    def test_codespaces_is_remote(self):
        self.assertTrue(loopback.is_remote_session({"CODESPACES": "true"}))

    def test_local_is_not_remote(self):
        self.assertFalse(loopback.is_remote_session({}))


class ConsoleBrowserTest(unittest.TestCase):
    def test_console_browser_blocks_open(self):
        self.assertFalse(loopback.can_open_browser({"BROWSER": "w3m"}))


class ValidateRedirectTest(unittest.TestCase):
    def test_valid_loopback(self):
        self.assertEqual(loopback.validate_loopback_redirect("http://127.0.0.1:56121/callback"), ("127.0.0.1", 56121))

    def test_https_rejected(self):
        from grokcli.errors import AuthError

        with self.assertRaises(AuthError):
            loopback.validate_loopback_redirect("https://127.0.0.1:56121/callback")

    def test_wrong_host_rejected(self):
        from grokcli.errors import AuthError

        with self.assertRaises(AuthError):
            loopback.validate_loopback_redirect("http://evil.example:56121/callback")

    def test_missing_port_rejected(self):
        from grokcli.errors import AuthError

        with self.assertRaises(AuthError):
            loopback.validate_loopback_redirect("http://127.0.0.1/callback")


class CallbackServerTest(unittest.TestCase):
    def test_captures_code_from_real_request(self):
        server = loopback.CallbackServer()
        try:
            url = f"{server.redirect_uri}?code=THECODE&state=THESTATE"

            def fire():
                urllib.request.urlopen(url, timeout=5).read()

            t = threading.Thread(target=fire)
            t.start()
            result = server.wait(timeout_seconds=5)
            t.join(timeout=5)
        finally:
            server.close()
        self.assertEqual(result["code"], "THECODE")
        self.assertEqual(result["state"], "THESTATE")

    def test_port_fallback_when_default_taken(self):
        first = loopback.CallbackServer(preferred_port=0)  # OS-assigned
        try:
            # Binding the same already-bound port forces the 0 fallback path.
            taken = int(first.redirect_uri.rsplit(":", 1)[1].split("/")[0])
            second = loopback.CallbackServer(preferred_port=taken)
            try:
                self.assertNotEqual(first.redirect_uri, second.redirect_uri)
            finally:
                second.close()
        finally:
            first.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
