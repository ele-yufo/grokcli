"""Tests for custom voices (voice cloning): multipart submit, listing, deletion."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grokcli.client import GrokClient
from grokcli.config import resolve_settings
from grokcli.errors import APIError, UsageError
from grokcli.media import voice
from grokcli.transport import Response


def _client(tmp):
    settings = resolve_settings({"output_dir": tmp, "no_color": True}, env={}, file_cfg={})
    return GrokClient(settings, env={})


class VoiceCloneTest(unittest.TestCase):
    def test_clone_sends_multipart_and_returns_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "c.wav"
            clip.write_bytes(b"WAVDATA")
            client = _client(tmp)
            client.request = mock.Mock(
                return_value=Response(
                    201, {"Content-Type": "application/json"},
                    json.dumps({"voice_id": "ab12cd34", "name": "Narrator"}).encode(),
                )
            )
            result = voice.clone_voice(client, audio_path=str(clip), name="Narrator", gender="neutral")
            self.assertEqual(result["voice_id"], "ab12cd34")
            self.assertEqual(client.request.call_args.args, ("POST", "/custom-voices"))
            body = client.request.call_args.kwargs["body"].decode("latin-1")
            self.assertIn('name="name"', body)
            self.assertIn("Narrator", body)
            self.assertIn('name="gender"', body)
            self.assertIn('name="file"', body)

    def test_clone_missing_file_raises(self):
        client = _client("/tmp")
        with self.assertRaises(UsageError):
            voice.clone_voice(client, audio_path="/no/such/clip.wav")

    def test_clone_invalid_gender_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "c.wav"
            clip.write_bytes(b"WAVDATA")
            client = _client(tmp)
            with self.assertRaises(UsageError):
                voice.clone_voice(client, audio_path=str(clip), gender="robot")

    def test_clone_response_without_id_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "c.wav"
            clip.write_bytes(b"WAVDATA")
            client = _client(tmp)
            client.request = mock.Mock(
                return_value=Response(200, {"Content-Type": "application/json"}, json.dumps({"name": "x"}).encode())
            )
            with self.assertRaises(APIError):
                voice.clone_voice(client, audio_path=str(clip))


class VoiceListDeleteTest(unittest.TestCase):
    def test_list_parses_voices_object(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value={"voices": [{"voice_id": "a", "name": "A"}]})
        self.assertEqual(voice.list_custom_voices(client), [{"voice_id": "a", "name": "A"}])

    def test_list_plain_array(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value=[{"id": "x"}])
        self.assertEqual(voice.list_custom_voices(client), [{"id": "x"}])

    def test_list_empty(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value={"voices": []})
        self.assertEqual(voice.list_custom_voices(client), [])

    def test_delete_parses_deleted(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value={"deleted": True})
        self.assertTrue(voice.delete_custom_voice(client, "ab12cd34"))
        self.assertEqual(client.request_json.call_args.args, ("DELETE", "/custom-voices/ab12cd34"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
