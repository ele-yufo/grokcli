"""Tests for media: file helpers, image, video poll, TTS, transcription."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

from grokcli import models
from grokcli.client import GrokClient
from grokcli.config import resolve_settings
from grokcli.errors import APIError, ContentFilterError, RequestTimeoutError, UsageError
from grokcli.media import files, image, tts, transcribe, video
from grokcli.transport import Response


def _client(tmp):
    settings = resolve_settings({"output_dir": tmp, "no_color": True}, env={}, file_cfg={})
    return GrokClient(settings, env={})


class FilesTest(unittest.TestCase):
    def test_safe_filename(self):
        self.assertEqual(files.safe_filename("a red fox! @#"), "a_red_fox")

    def test_output_path_shape(self):
        p = files.output_path(Path("/tmp"), label="hi there", ext="png")
        self.assertTrue(p.name.endswith("_hi_there.png"))

    def test_save_and_decode_b64(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = files.decode_b64(base64.b64encode(b"PNGDATA").decode())
            p = files.save_bytes(Path(tmp) / "x.png", raw)
            self.assertEqual(p.read_bytes(), b"PNGDATA")

    def test_data_uri_passthrough_for_url(self):
        self.assertEqual(files.image_to_data_uri("https://x/y.png"), "https://x/y.png")


class ImageTest(unittest.TestCase):
    def test_generate_from_b64(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            b64 = base64.b64encode(b"IMG").decode()
            client.request_json = mock.Mock(return_value={"data": [{"b64_json": b64}]})
            paths = image.generate_images(
                client, prompt="fox", model="m", aspect_ratio="1:1", resolution="2k", n=1, output_dir=Path(tmp)
            )
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].read_bytes(), b"IMG")

    def test_generate_from_url_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(return_value={"data": [{"url": "https://img/1.png"}]})
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            paths = image.generate_images(
                client, prompt="fox", model="m", aspect_ratio="16:9", resolution="1k", n=1, output_dir=Path(tmp)
            )
            client.download.assert_called_once()
            self.assertEqual(len(paths), 1)

    def test_invalid_aspect_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            with self.assertRaises(UsageError):
                image.generate_images(
                    client, prompt="x", model="m", aspect_ratio="bogus", resolution="2k", n=1, output_dir=Path(tmp)
                )


class VideoTest(unittest.TestCase):
    def test_poll_returns_on_done(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value={"status": "done", "video": {"url": "https://v/1.mp4"}})
        with mock.patch.object(video.time, "sleep"):
            result = video._poll(client, "rid", on_status=None, poll_timeout=10)
        self.assertEqual(video._video_url(result), "https://v/1.mp4")

    def test_poll_raises_on_failure(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value={"status": "failed", "error": {"message": "policy violation"}})
        with mock.patch.object(video.time, "sleep"):
            with self.assertRaises(ContentFilterError):
                video._poll(client, "rid", on_status=None, poll_timeout=10)

    def test_poll_times_out(self):
        client = _client("/tmp")
        with self.assertRaises(RequestTimeoutError):
            video._poll(client, "rid", on_status=None, poll_timeout=0.0)

    def test_generate_video_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                side_effect=[{"request_id": "r1"}, {"status": "done", "video": {"url": "https://v/x.mp4"}}]
            )
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            with mock.patch.object(video.time, "sleep"):
                path = video.generate_video(
                    client, prompt="wave", model="m", aspect_ratio="16:9", resolution="720p", duration=8, output_dir=Path(tmp)
                )
            self.assertTrue(str(path).endswith(".mp4"))
            client.download.assert_called_once_with("https://v/x.mp4", path)

    def test_missing_request_id_raises(self):
        self.assertRaises(APIError, video._request_id, {})


class TtsTest(unittest.TestCase):
    def test_synthesize_raw_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request = mock.Mock(
                return_value=Response(status=200, headers={"Content-Type": "audio/mpeg"}, body=b"AUDIO")
            )
            path = tts.synthesize(client, text="hi", model="grok-tts", voice=None, fmt="mp3", output_dir=Path(tmp))
            self.assertEqual(path.read_bytes(), b"AUDIO")

    def test_synthesize_json_base64_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            body = json.dumps({"audio": base64.b64encode(b"WAV").decode()}).encode()
            client.request = mock.Mock(
                return_value=Response(status=200, headers={"Content-Type": "application/json"}, body=body)
            )
            path = tts.synthesize(client, text="hi", model="grok-tts", voice="alloy", fmt="wav", output_dir=Path(tmp))
            self.assertEqual(path.read_bytes(), b"WAV")

    def test_list_voices(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value={"voices": ["alloy", {"id": "echo"}]})
        self.assertEqual(tts.list_voices(client), ["alloy", "echo"])


class TranscribeTest(unittest.TestCase):
    def test_multipart_contains_fields(self):
        body, content_type = files.encode_multipart(
            fields={"model": "grok-transcribe"}, file_field="file", filename="a.mp3", file_bytes=b"RAW", file_mime="audio/mpeg"
        )
        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b'name="model"', body)
        self.assertIn(b'filename="a.mp3"', body)
        self.assertIn(b"RAW", body)

    def test_transcribe_reads_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "a.mp3"
            audio.write_bytes(b"RAW")
            client = _client(tmp)
            client.request = mock.Mock(
                return_value=Response(status=200, headers={"Content-Type": "application/json"}, body=b'{"text":"hello"}')
            )
            result = transcribe.transcribe(client, audio_path=str(audio), model="grok-transcribe")
            self.assertEqual(result["text"], "hello")

    def test_missing_file_raises(self):
        client = _client("/tmp")
        with self.assertRaises(UsageError):
            transcribe.transcribe(client, audio_path="/no/such/file.mp3", model="m")

    def test_missing_text_field_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "a.mp3"
            audio.write_bytes(b"RAW")
            client = _client(tmp)
            client.request = mock.Mock(
                return_value=Response(status=200, headers={"Content-Type": "application/json"}, body=b"{}")
            )
            with self.assertRaises(APIError):
                transcribe.transcribe(client, audio_path=str(audio), model="m")


class VideoFailureStatusTest(unittest.TestCase):
    def test_non_policy_failure_is_api_error(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value={"status": "error", "error": {"message": "internal"}})
        with mock.patch.object(video.time, "sleep"):
            with self.assertRaises(APIError) as ctx:
                video._poll(client, "rid", on_status=None, poll_timeout=10)
        self.assertNotIsInstance(ctx.exception, ContentFilterError)

    def test_cancelled_and_expired_statuses_fail(self):
        for status in ("cancelled", "expired", "canceled"):
            client = _client("/tmp")
            client.request_json = mock.Mock(return_value={"status": status})
            with mock.patch.object(video.time, "sleep"):
                with self.assertRaises(APIError):
                    video._poll(client, "rid", on_status=None, poll_timeout=10)

    def test_failure_error_non_dict_error(self):
        err = video._failure_error({"status": "failed", "error": "oops-string"}, "failed")
        self.assertIsInstance(err, APIError)

    def test_video_url_top_level_fallback(self):
        self.assertEqual(video._video_url({"url": "https://v/top.mp4"}), "https://v/top.mp4")

    def test_video_url_missing_raises(self):
        self.assertRaises(APIError, video._video_url, {"status": "done"})

    def test_generate_video_with_image_uses_data_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                side_effect=[{"request_id": "r"}, {"status": "done", "video": {"url": "https://v/x.mp4"}}]
            )
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            with mock.patch.object(video.files, "image_to_data_uri", return_value="data:image/png;base64,AAA"), mock.patch.object(video.time, "sleep"):
                video.generate_video(
                    client, prompt="p", model="grok-imagine-video-1.5", aspect_ratio="16:9",
                    resolution="720p", duration=5, output_dir=Path(tmp), image="x.png",
                )
            submit_kwargs = client.request_json.call_args_list[0].kwargs
            self.assertEqual(submit_kwargs["json_body"]["image"], {"url": "data:image/png;base64,AAA"})
            self.assertIn("x-idempotency-key", submit_kwargs["headers"])


class TtsBranchTest(unittest.TestCase):
    def test_audio_bytes_data_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            body = json.dumps({"data": base64.b64encode(b"SND").decode()}).encode()
            client.request = mock.Mock(return_value=Response(status=200, headers={"Content-Type": "application/json"}, body=body))
            path = tts.synthesize(client, text="x", model="grok-tts", voice=None, fmt="mp3", output_dir=Path(tmp))
            self.assertEqual(path.read_bytes(), b"SND")

    def test_audio_bytes_empty_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request = mock.Mock(return_value=Response(status=200, headers={"Content-Type": "application/json"}, body=b"{}"))
            with self.assertRaises(APIError):
                tts.synthesize(client, text="x", model="grok-tts", voice=None, fmt="mp3", output_dir=Path(tmp))

    def test_list_voices_plain_list_and_empty(self):
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value=["v1", "v2"])
        self.assertEqual(tts.list_voices(client), ["v1", "v2"])
        client.request_json = mock.Mock(return_value={})
        self.assertEqual(tts.list_voices(client), [])


class FilesHelpersTest(unittest.TestCase):
    def test_safe_filename_all_special_returns_output(self):
        self.assertEqual(files.safe_filename("!!!@@@###"), "output")

    def test_output_path_with_index(self):
        p = files.output_path(Path("/tmp"), label="x", ext="png", index=2)
        self.assertTrue(p.name.endswith("_x_2.png"))

    def test_decode_b64_data_uri(self):
        self.assertEqual(files.decode_b64("data:image/png;base64,QUJD"), b"ABC")

    def test_image_to_data_uri_local_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "p.png"
            png.write_bytes(b"\x89PNG\r\n")
            uri = files.image_to_data_uri(str(png))
            self.assertTrue(uri.startswith("data:image/png;base64,"))

    def test_image_to_data_uri_non_image_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "a.txt"
            txt.write_text("hi")
            self.assertEqual(files.image_to_data_uri(str(txt)), str(txt))


class ImageValidationTest(unittest.TestCase):
    def test_invalid_resolution_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            with self.assertRaises(UsageError):
                image.generate_images(
                    client, prompt="x", model="m", aspect_ratio="1:1", resolution="9k", n=1, output_dir=Path(tmp)
                )

    def test_invalid_aspect_ratio_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            with self.assertRaises(UsageError):
                image.generate_images(
                    client, prompt="x", model="m", aspect_ratio="5:4", resolution="2k", n=1, output_dir=Path(tmp)
                )

    def test_wide_and_auto_aspect_ratios_accepted(self):
        # Imagine Image 2.0 era (docs 2026-08): phone-full-screen ratios and
        # "auto" are valid for image generation/editing (not for video).
        for ratio in ("9:19.5", "19.5:9", "9:20", "20:9", "1:2", "2:1", "auto"):
            self.assertIn(ratio, models.IMAGE_ASPECT_RATIOS)
            self.assertNotIn(ratio, models.ASPECT_RATIOS)

    def test_cinematic_and_banner_aspect_ratios_accepted(self):
        # Release notes 2026-08: 21:9 and 5:2 added for generation and editing.
        for ratio in ("21:9", "5:2"):
            self.assertIn(ratio, models.IMAGE_ASPECT_RATIOS)
            self.assertNotIn(ratio, models.ASPECT_RATIOS)

    def test_quality_passthrough_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(return_value={"data": [{"b64_json": base64.b64encode(b"OUT").decode()}]})
            image.generate_images(
                client, prompt="x", model="grok-imagine-image-2.0", aspect_ratio="1:1", resolution="2k",
                n=1, output_dir=Path(tmp), quality="low",
            )
            self.assertEqual(client.request_json.call_args.kwargs["json_body"]["quality"], "low")
            # Omitted by default — the API's own "auto" applies.
            image.generate_images(
                client, prompt="x", model="grok-imagine-image-2.0", aspect_ratio="1:1", resolution="2k",
                n=1, output_dir=Path(tmp),
            )
            self.assertNotIn("quality", client.request_json.call_args.kwargs["json_body"])
            with self.assertRaises(UsageError):
                image.generate_images(
                    client, prompt="x", model="m", aspect_ratio="1:1", resolution="2k", n=1,
                    output_dir=Path(tmp), quality="ultra",
                )

    def test_edit_quality_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(return_value={"data": [{"b64_json": base64.b64encode(b"OUT").decode()}]})
            image.edit_image(
                client, prompt="x", sources=["https://in/a.png"], model="grok-imagine-image-2.0",
                aspect_ratio=None, resolution=None, n=1, output_dir=Path(tmp), quality="medium",
            )
            self.assertEqual(client.request_json.call_args.kwargs["json_body"]["quality"], "medium")

    def test_count_above_ten_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            with self.assertRaises(UsageError):
                image.generate_images(
                    client, prompt="x", model="m", aspect_ratio="1:1", resolution="2k", n=11, output_dir=Path(tmp)
                )

    def test_response_format_passthrough_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(return_value={"data": [{"b64_json": base64.b64encode(b"OUT").decode()}]})
            image.generate_images(
                client, prompt="x", model="grok-imagine-image-2.0", aspect_ratio="1:1", resolution="2k",
                n=1, output_dir=Path(tmp), response_format="b64_json",
            )
            body = client.request_json.call_args.kwargs["json_body"]
            self.assertEqual(body["response_format"], "b64_json")
            with self.assertRaises(UsageError):
                image.generate_images(
                    client, prompt="x", model="m", aspect_ratio="1:1", resolution="2k", n=1,
                    output_dir=Path(tmp), response_format="jpeg",
                )

    def test_defaults_use_imagine_image_2(self):
        self.assertIn("grok-imagine-image-2.0", models.IMAGE_MODELS)
        self.assertEqual(image.DEFAULT_EDIT_MODEL, "grok-imagine-image-2.0")

    def test_mime_type_drives_extension(self):
        # Imagine Image 2.0 returns image/jpeg; the saved file must not lie
        # about its format (was: hardcoded .png).
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                return_value={"data": [{"b64_json": base64.b64encode(b"OUT").decode(), "mime_type": "image/jpeg"}]}
            )
            paths = image.generate_images(
                client, prompt="fox", model="grok-imagine-image-2.0", aspect_ratio="1:1",
                resolution="2k", n=1, output_dir=Path(tmp),
            )
            self.assertTrue(paths[0].name.endswith(".jpg"), paths[0].name)

    def test_missing_mime_type_falls_back_to_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(return_value={"data": [{"b64_json": base64.b64encode(b"OUT").decode()}]})
            paths = image.generate_images(
                client, prompt="fox", model="m", aspect_ratio="1:1", resolution="2k", n=1, output_dir=Path(tmp),
            )
            self.assertTrue(paths[0].name.endswith(".png"), paths[0].name)


class ImageEditTest(unittest.TestCase):
    def test_edit_sends_images_and_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.png"
            src.write_bytes(b"\x89PNG\r\n")
            client = _client(tmp)
            client.request_json = mock.Mock(return_value={"data": [{"b64_json": base64.b64encode(b"OUT").decode()}]})
            paths = image.edit_image(
                client, prompt="make it night", sources=[str(src)], model="grok-imagine-image",
                aspect_ratio=None, resolution=None, n=1, output_dir=Path(tmp),
            )
            self.assertEqual(paths[0].read_bytes(), b"OUT")
            body = client.request_json.call_args.kwargs["json_body"]
            self.assertEqual(client.request_json.call_args.args, ("POST", "/images/edits"))
            # Canonical field is ``url`` (docs 2026-08); ``image_url`` is the
            # legacy alias.
            self.assertTrue(body["images"][0]["url"].startswith("data:image/png;base64,"))

    def test_edit_requires_a_source(self):
        client = _client("/tmp")
        with self.assertRaises(UsageError):
            image.edit_image(client, prompt="x", sources=[], model="m", aspect_ratio=None, resolution=None, n=1, output_dir=Path("/tmp"))

    def test_edit_rejects_more_than_five(self):
        client = _client("/tmp")
        with self.assertRaises(UsageError):
            image.edit_image(client, prompt="x", sources=["a"] * 6, model="m", aspect_ratio=None, resolution=None, n=1, output_dir=Path("/tmp"))

    def test_edit_limit_is_per_model(self):
        # Default cap is 5 — the multi-image editing guide documents "up to
        # five source images for a single image edit" (API raised 3 -> 5 on
        # 2026-08-28).
        self.assertEqual(models.image_edit_max_sources("unknown-model"), 5)
        self.assertEqual(models.image_edit_max_sources("grok-imagine-image-2.0"), 5)
        client = _client("/tmp")
        client.request_json = mock.Mock(return_value={"data": [{"b64_json": base64.b64encode(b"OUT").decode()}]})
        image.edit_image(client, prompt="x", sources=["a"] * 5, model="grok-imagine-image-2.0",
                         aspect_ratio=None, resolution=None, n=1, output_dir=Path("/tmp"))
        self.assertEqual(len(client.request_json.call_args.kwargs["json_body"]["images"]), 5)
        # A model with a tighter documented cap still wins over the default.
        with mock.patch.dict(models.IMAGE_EDIT_MAX_SOURCES, {"legacy-model": 3}):
            self.assertEqual(models.image_edit_max_sources("legacy-model"), 3)
            with self.assertRaises(UsageError):
                image.edit_image(_client("/tmp"), prompt="x", sources=["a"] * 4, model="legacy-model",
                                 aspect_ratio=None, resolution=None, n=1, output_dir=Path("/tmp"))

    def test_url_source_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(return_value={"data": [{"url": "https://img/e.png"}]})
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            image.edit_image(client, prompt="x", sources=["https://in/a.png"], model="m", aspect_ratio="auto", resolution=None, n=1, output_dir=Path(tmp))
            self.assertEqual(client.request_json.call_args.kwargs["json_body"]["images"][0]["url"], "https://in/a.png")


class VideoReferenceAndExtendTest(unittest.TestCase):
    def test_reference_images_added_to_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                side_effect=[{"request_id": "r"}, {"status": "done", "video": {"url": "https://v/x.mp4"}}]
            )
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            with mock.patch.object(video.files, "image_to_data_uri", side_effect=lambda p: f"data:image/png;base64,{p}"), \
                    mock.patch.object(video.time, "sleep"):
                video.generate_video(
                    client, prompt="p", model="grok-imagine-video", aspect_ratio="16:9",
                    resolution="720p", duration=5, output_dir=Path(tmp), reference_images=["a", "b"],
                )
            refs = client.request_json.call_args_list[0].kwargs["json_body"]["reference_images"]
            self.assertEqual([r["url"] for r in refs], ["data:image/png;base64,a", "data:image/png;base64,b"])

    def test_too_many_reference_images_rejected(self):
        client = _client("/tmp")
        with self.assertRaises(UsageError):
            video.generate_video(
                client, prompt="p", model="grok-imagine-video", aspect_ratio="16:9", resolution="720p", duration=5,
                output_dir=Path("/tmp"), reference_images=[str(i) for i in range(8)],
            )


class VideoPerModelValidationTest(unittest.TestCase):
    def _gen(self, **over):
        kw: dict = {
            "prompt": "p", "model": "grok-imagine-video", "aspect_ratio": "16:9",
            "resolution": "720p", "duration": 5, "output_dir": Path("/tmp"),
        }
        kw.update(over)
        return video.generate_video(_client("/tmp"), **kw)

    def test_duration_out_of_range_errors_not_clamps(self):
        with self.assertRaises(UsageError) as ctx:
            self._gen(duration=20)
        self.assertIn("out of range", ctx.exception.message)

    def test_reference_images_accepted_on_15(self):
        # The 1.5 model went from preview (I2V only, R2V rejected) to the unified
        # T2V/I2V/R2V flagship (2026-08) — R2V must now pass client validation.
        client = _client("/tmp")
        client.request_json = mock.Mock(side_effect=RuntimeError("reached-submit"))
        with self.assertRaises(RuntimeError):
            video.generate_video(
                client, prompt="p", model="grok-imagine-video-1.5", aspect_ratio="16:9",
                resolution="720p", duration=5, output_dir=Path("/tmp"), reference_images=["a"],
            )

    def test_image_rejected_on_base_model(self):
        with self.assertRaises(UsageError) as ctx:
            self._gen(model="grok-imagine-video", image="a.png")
        self.assertIn("image-to-video", ctx.exception.message)

    def test_1080p_allowed_client_side(self):
        # 1080p is tier-gated by the API, but the client must not block it: validation
        # passes and we reach the submit call (stubbed), rather than a client UsageError.
        client = _client("/tmp")
        client.request_json = mock.Mock(side_effect=RuntimeError("reached-submit"))
        with self.assertRaises(RuntimeError):
            video.generate_video(
                client, prompt="p", model="grok-imagine-video", aspect_ratio="16:9",
                resolution="1080p", duration=5, output_dir=Path("/tmp"),
            )

    def test_unknown_resolution_rejected(self):
        with self.assertRaises(UsageError):
            self._gen(resolution="4k")

    def test_video_spec_lookup(self):
        from grokcli import models

        self.assertTrue(models.video_spec("grok-imagine-video-1.5").supports_reference)
        self.assertFalse(models.video_spec("grok-imagine-video").supports_image)
        self.assertEqual(models.video_spec("grok-imagine-video-1.5").r2v_max_resolution, "720p")
        self.assertEqual(models.video_spec("grok-imagine-video").max_reference_audios, 0)
        self.assertTrue(models.video_spec("some-future-model").supports_reference)  # permissive default

    def test_video_to_url_http_passthrough(self):
        self.assertEqual(video._video_to_url("https://v/x.mp4"), "https://v/x.mp4")

    def test_video_to_url_local_data_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "c.mp4"
            v.write_bytes(b"MP4DATA")
            uri = video._video_to_url(str(v))
            self.assertTrue(uri.startswith("data:video/mp4;base64,"))

    def test_video_to_url_missing_raises(self):
        with self.assertRaises(UsageError):
            video._video_to_url("/no/such/clip.mp4")

    def test_extend_video_submits_and_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                side_effect=[{"request_id": "r"}, {"status": "done", "video": {"url": "https://v/ext.mp4"}}]
            )
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            with mock.patch.object(video.time, "sleep"):
                path = video.extend_video(
                    client, video="https://v/in.mp4", prompt="more", model="grok-imagine-video",
                    duration=6, output_dir=Path(tmp),
                )
            self.assertEqual(client.request_json.call_args_list[0].args, ("POST", "/videos/extensions"))
            body = client.request_json.call_args_list[0].kwargs["json_body"]
            self.assertEqual(body["video"]["url"], "https://v/in.mp4")
            self.assertEqual(body["prompt"], "more")
            client.download.assert_called_once_with("https://v/ext.mp4", path)


class VideoR2VAudioAndEditTest(unittest.TestCase):
    """R2V narration, mode exclusivity, 1080p caps, edits, and polling extras."""

    def _generate(self, tmp, **over: Any):
        client = _client(tmp)
        client.request_json = mock.Mock(
            side_effect=[{"request_id": "r"}, {"status": "done", "video": {"url": "https://v/x.mp4"}}]
        )
        client.download = mock.Mock(side_effect=lambda url, path, **k: path)
        kw: Dict[str, Any] = {"prompt": "p", "model": "grok-imagine-video-1.5", "aspect_ratio": "16:9",
                              "resolution": "720p", "duration": 5, "output_dir": Path(tmp)}
        kw.update(over)
        with mock.patch.object(video.time, "sleep"):
            video.generate_video(client, **kw)
        return client.request_json.call_args_list[0].kwargs["json_body"]

    def test_reference_audios_in_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._generate(tmp, reference_audios=["eve", "rex"])
        self.assertEqual(payload["reference_audios"], [{"voice_id": "eve"}, {"voice_id": "rex"}])

    def test_more_than_three_reference_audios_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError):
                self._generate(tmp, reference_audios=["a", "b", "c", "d"])

    def test_reference_audios_rejected_on_base_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError) as ctx:
                self._generate(tmp, model="grok-imagine-video", reference_audios=["eve"])
        self.assertIn("narration", ctx.exception.message)

    def test_image_and_references_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError) as ctx:
                self._generate(tmp, image="a.png", reference_images=["b.png"])
        self.assertIn("mutually exclusive", ctx.exception.message)

    def test_image_and_reference_audio_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError):
                self._generate(tmp, image="a.png", reference_audios=["eve"])

    def test_r2v_1080p_rejected_on_15(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError) as ctx:
                self._generate(tmp, reference_images=["a.png"], resolution="1080p")
        self.assertIn("720p", ctx.exception.message)

    def test_t2v_1080p_reaches_submit_on_15(self):
        # Native 1080p for T2V/I2V on 1.5: validation passes, submit is reached.
        client = _client("/tmp")
        client.request_json = mock.Mock(side_effect=RuntimeError("reached-submit"))
        with self.assertRaises(RuntimeError):
            video.generate_video(
                client, prompt="p", model="grok-imagine-video-1.5", aspect_ratio="16:9",
                resolution="1080p", duration=5, output_dir=Path("/tmp"),
            )

    def test_extend_duration_beyond_10_rejected(self):
        client = _client("/tmp")
        with self.assertRaises(UsageError):
            video.extend_video(
                client, video="https://v/in.mp4", model="grok-imagine-video-1.5", duration=11, output_dir=Path("/tmp")
            )

    def test_extend_duration_2_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                side_effect=[{"request_id": "r"}, {"status": "done", "video": {"url": "https://v/x.mp4"}}]
            )
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            with mock.patch.object(video.time, "sleep"):
                video.extend_video(
                    client, video="https://v/in.mp4", model="grok-imagine-video-1.5", duration=2, output_dir=Path(tmp)
                )
            self.assertEqual(client.request_json.call_args_list[0].kwargs["json_body"]["duration"], 2)

    def test_edit_video_submits_and_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                side_effect=[{"request_id": "r"}, {"status": "done", "video": {"url": "https://v/e.mp4"}}]
            )
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            with mock.patch.object(video.time, "sleep"):
                path = video.edit_video(client, video="https://v/in.mp4", model="m", prompt="add neon", output_dir=Path(tmp))
            self.assertEqual(client.request_json.call_args_list[0].args, ("POST", "/videos/edits"))
            body = client.request_json.call_args_list[0].kwargs["json_body"]
            self.assertEqual(body["video"]["url"], "https://v/in.mp4")
            self.assertEqual(body["prompt"], "add neon")
            client.download.assert_called_once_with("https://v/e.mp4", path)

    def test_edit_video_requires_prompt(self):
        client = _client("/tmp")
        with self.assertRaises(UsageError):
            video.edit_video(client, video="https://v/in.mp4", model="m", prompt="  ", output_dir=Path("/tmp"))

    def test_respect_moderation_false_raises_content_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                side_effect=[{"request_id": "r"}, {"status": "done", "video": {"url": "", "respect_moderation": False}}]
            )
            with self.assertRaises(ContentFilterError):
                with mock.patch.object(video.time, "sleep"):
                    video.generate_video(
                        client, prompt="p", model="grok-imagine-video-1.5", aspect_ratio="16:9",
                        resolution="720p", duration=5, output_dir=Path(tmp),
                    )

    def test_poll_reports_progress_to_callback(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(tmp)
            client.request_json = mock.Mock(
                side_effect=[
                    {"request_id": "r"},
                    {"status": "pending", "progress": 42},
                    {"status": "done", "video": {"url": "https://v/x.mp4"}},
                ]
            )
            client.download = mock.Mock(side_effect=lambda url, path, **k: path)
            with mock.patch.object(video.time, "sleep"):
                video.generate_video(
                    client, prompt="p", model="grok-imagine-video-1.5", aspect_ratio="16:9",
                    resolution="720p", duration=5, output_dir=Path(tmp),
                    on_status=lambda s, e, p: calls.append((s, p)),
                )
        self.assertEqual(calls, [("pending 42%", 42)])


class TTSNewParamsTest(unittest.TestCase):
    """voice_id, speed/latency/normalization, text cap, output_format codec."""

    def _synth(self, tmp, **over: Any):
        client = _client(tmp)
        client.request = mock.Mock(return_value=Response(200, {"Content-Type": "audio/mpeg"}, b"AUDIO"))
        kw: Dict[str, Any] = dict(text="hi", model="grok-tts", voice=None, fmt="mp3", output_dir=Path(tmp), language="en")
        kw.update(over)
        tts.synthesize(client, **kw)
        return json.loads(client.request.call_args.kwargs["body"].decode())

    def test_voice_id_instead_of_voice(self):
        payload = self._synth("/tmp", voice="Rex")
        self.assertEqual(payload["voice_id"], "Rex")
        self.assertNotIn("voice", payload)

    def test_no_model_field_sent(self):
        payload = self._synth("/tmp")
        self.assertNotIn("model", payload)
        self.assertEqual(payload["text"], "hi")
        self.assertEqual(payload["language"], "en")

    def test_speed_latency_normalize_in_payload(self):
        payload = self._synth("/tmp", speed=0.8, optimize_streaming_latency=2, text_normalization=True)
        self.assertEqual(payload["speed"], 0.8)
        self.assertEqual(payload["optimize_streaming_latency"], 2)
        self.assertTrue(payload["text_normalization"])

    def test_output_format_codec_for_wav(self):
        payload = self._synth("/tmp", fmt="wav")
        self.assertEqual(payload["output_format"], {"codec": "wav"})

    def test_default_mp3_sends_no_output_format(self):
        payload = self._synth("/tmp")
        self.assertNotIn("output_format", payload)

    def test_speed_out_of_range_rejected(self):
        with self.assertRaises(UsageError):
            self._synth("/tmp", speed=2.0)

    def test_latency_out_of_range_rejected(self):
        with self.assertRaises(UsageError):
            self._synth("/tmp", optimize_streaming_latency=5)

    def test_invalid_codec_rejected(self):
        with self.assertRaises(UsageError):
            self._synth("/tmp", fmt="ogg")

    def test_text_over_15000_rejected(self):
        with self.assertRaises(UsageError):
            self._synth("/tmp", text="x" * 15001)


class TranscribeNewParamsTest(unittest.TestCase):
    """vad_threshold, language, diarize, keyterm option fields."""

    def _transcribe(self, tmp, **over: Any):
        audio = Path(tmp) / "a.wav"
        audio.write_bytes(b"WAVDATA")
        client = _client(tmp)
        client.request = mock.Mock(
            return_value=Response(200, {"Content-Type": "application/json"}, json.dumps({"text": "hi"}).encode())
        )
        kw: Dict[str, Any] = dict(audio_path=str(audio), model="grok-transcribe")
        kw.update(over)
        transcribe.transcribe(client, **kw)
        return client.request.call_args.kwargs["body"].decode("latin-1")

    def test_vad_threshold_and_language_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = self._transcribe(tmp, vad_threshold=0.3, language="en")
        self.assertIn('name="vad_threshold"', body)
        self.assertIn("0.3", body)
        self.assertIn('name="language"', body)

    def test_diarize_and_repeated_keyterms(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = self._transcribe(tmp, diarize=True, keyterms=["Grok", "API"])
        self.assertIn('name="diarize"', body)
        self.assertEqual(body.count('name="keyterm"'), 2)
        # Option fields must precede the file part (API contract for streamable uploads).
        self.assertLess(body.index("keyterm"), body.index('name="file"'))

    def test_vad_threshold_out_of_range_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "a.wav"
            audio.write_bytes(b"WAVDATA")
            client = _client(tmp)
            with self.assertRaises(UsageError):
                transcribe.transcribe(client, audio_path=str(audio), model="m", vad_threshold=1.5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
