"""Tests for the OAuth protocol: PKCE, authorize URL, discovery, token shapes."""

from __future__ import annotations

import base64
import hashlib
import unittest
from urllib.parse import parse_qs, urlparse

from grokcli.auth import oauth
from grokcli.errors import AuthError
from grokcli.transport import HttpClient, Response


class PkceTest(unittest.TestCase):
    def test_verifier_length_in_rfc_range(self):
        v = oauth.generate_code_verifier()
        self.assertGreaterEqual(len(v), 43)
        self.assertLessEqual(len(v), 128)

    def test_challenge_is_s256_of_verifier(self):
        verifier = "abc123_test-verifier"
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.assertEqual(oauth.code_challenge(verifier), expected)

    def test_challenge_has_no_padding(self):
        self.assertNotIn("=", oauth.code_challenge(oauth.generate_code_verifier()))


class AuthorizeUrlTest(unittest.TestCase):
    def test_contains_required_params(self):
        url = oauth.build_authorize_url(
            authorization_endpoint="https://auth.x.ai/oauth2/authorize",
            redirect_uri="http://127.0.0.1:56121/callback",
            challenge="CHAL",
            state="STATE",
            nonce="NONCE",
        )
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q["response_type"], ["code"])
        self.assertEqual(q["client_id"], [oauth.CLIENT_ID])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["code_challenge"], ["CHAL"])
        self.assertEqual(q["plan"], ["generic"])  # mandatory for non-allowlisted clients
        self.assertEqual(q["scope"], [oauth.SCOPE])
        self.assertEqual(q["redirect_uri"], ["http://127.0.0.1:56121/callback"])


class ValidateEndpointTest(unittest.TestCase):
    def test_accepts_xai_https(self):
        self.assertEqual(
            oauth.validate_endpoint("https://auth.x.ai/oauth2/token", field="token_endpoint"),
            "https://auth.x.ai/oauth2/token",
        )

    def test_rejects_foreign_host(self):
        with self.assertRaises(AuthError):
            oauth.validate_endpoint("https://evil.example/token", field="token_endpoint")

    def test_rejects_http(self):
        with self.assertRaises(AuthError):
            oauth.validate_endpoint("http://auth.x.ai/token", field="token_endpoint")


class _FakeClient(HttpClient):
    """Stand-in for HttpClient used by discover/exchange/refresh (no real opener)."""

    def __init__(self, *, json_result=None, json_error=None, response=None):
        self._json_result = json_result
        self._json_error = json_error
        self._response = response

    def request_json(self, method, url, *, json_body=None, headers=None, timeout=None):
        if self._json_error is not None:
            raise self._json_error
        return self._json_result

    def request(self, method, url, *, headers=None, body=None, timeout=None):
        if self._json_error is not None:
            raise self._json_error
        return self._response


class DiscoverTest(unittest.TestCase):
    def test_uses_discovered_endpoints(self):
        client = _FakeClient(
            json_result={
                "authorization_endpoint": "https://auth.x.ai/oauth2/authorize",
                "token_endpoint": "https://auth.x.ai/oauth2/token",
            }
        )
        d = oauth.discover(client)
        self.assertEqual(d["token_endpoint"], "https://auth.x.ai/oauth2/token")

    def test_falls_back_when_discovery_fails(self):
        client = _FakeClient(json_error=AuthError("network"))
        d = oauth.discover(client)
        self.assertEqual(d["authorization_endpoint"], oauth.DEFAULT_AUTHORIZATION_ENDPOINT)
        self.assertEqual(d["token_endpoint"], oauth.DEFAULT_TOKEN_ENDPOINT)

    def test_rejects_foreign_discovered_endpoint(self):
        client = _FakeClient(
            json_result={
                "authorization_endpoint": "https://evil.example/a",
                "token_endpoint": "https://evil.example/t",
            }
        )
        with self.assertRaises(AuthError):
            oauth.discover(client)


class ExchangeAndRefreshTest(unittest.TestCase):
    def _resp(self, obj):
        import json

        return Response(status=200, headers={}, body=json.dumps(obj).encode())

    def test_exchange_returns_payload(self):
        client = _FakeClient(response=self._resp({"access_token": "a", "refresh_token": "r"}))
        payload = oauth.exchange_code(
            client,
            token_endpoint="https://auth.x.ai/oauth2/token",
            code="c",
            redirect_uri="http://127.0.0.1:56121/callback",
            code_verifier="v",
            challenge="ch",
        )
        self.assertEqual(payload["access_token"], "a")

    def test_exchange_requires_refresh_token(self):
        client = _FakeClient(response=self._resp({"access_token": "a"}))
        with self.assertRaises(AuthError):
            oauth.exchange_code(
                client,
                token_endpoint="https://auth.x.ai/oauth2/token",
                code="c",
                redirect_uri="http://127.0.0.1:56121/callback",
                code_verifier="v",
                challenge="ch",
            )

    def test_refresh_requires_refresh_token_value(self):
        client = _FakeClient(response=self._resp({"access_token": "a"}))
        with self.assertRaises(AuthError):
            oauth.refresh(client, token_endpoint="https://auth.x.ai/oauth2/token", refresh_token="")

    def test_400_invalid_grant_maps_to_relogin_auth_error(self):
        from grokcli.errors import APIError

        client = _FakeClient(json_error=APIError("invalid_grant", status_code=400))
        with self.assertRaises(AuthError) as ctx:
            oauth.refresh(client, token_endpoint="https://auth.x.ai/oauth2/token", refresh_token="r")
        self.assertTrue(ctx.exception.relogin_required)

    def test_401_maps_to_relogin_auth_error(self):
        client = _FakeClient(json_error=AuthError("unauthorized", status_code=401))
        with self.assertRaises(AuthError) as ctx:
            oauth.exchange_code(
                client, token_endpoint="https://auth.x.ai/oauth2/token", code="c",
                redirect_uri="http://127.0.0.1:56121/callback", code_verifier="v", challenge="ch",
            )
        self.assertTrue(ctx.exception.relogin_required)


class NormalizeTokensTest(unittest.TestCase):
    def test_preserves_previous_refresh_when_omitted(self):
        out = oauth.normalize_tokens(
            {"access_token": "new"}, previous={"refresh_token": "old", "id_token": "idt"}
        )
        self.assertEqual(out["refresh_token"], "old")
        self.assertEqual(out["id_token"], "idt")
        self.assertEqual(out["token_type"], "Bearer")

    def test_uses_new_refresh_when_present(self):
        out = oauth.normalize_tokens({"access_token": "a", "refresh_token": "fresh"}, previous={"refresh_token": "old"})
        self.assertEqual(out["refresh_token"], "fresh")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
