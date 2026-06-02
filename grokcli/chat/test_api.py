"""Tests for Responses API payload building and tolerant response parsing."""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List, Optional

from grokcli.chat import api
from grokcli.client import GrokClient


class _FakeClient(GrokClient):
    """GrokClient stand-in that replays canned stream events / JSON."""

    def __init__(self, *, events: Optional[List[Dict[str, str]]] = None, json_result: Any = None):
        self._events = events or []
        self._json_result = json_result

    def stream(self, method, path, *, json_body=None, headers=None, timeout=None):
        return iter(self._events)

    def request_json(self, method, path, *, json_body=None, headers=None, timeout=None):
        return self._json_result


def sse(obj: dict) -> Dict[str, str]:
    return {"event": obj.get("type", ""), "data": json.dumps(obj)}


class BuildPayloadTest(unittest.TestCase):
    def test_basic_shape(self):
        payload = api.build_payload(model="grok-4", messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(payload["model"], "grok-4")
        self.assertEqual(payload["input"], [{"role": "user", "content": "hi"}])
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["store"])
        self.assertNotIn("instructions", payload)

    def test_instructions_and_tools(self):
        payload = api.build_payload(
            model="grok-4",
            messages=[{"role": "user", "content": "hi"}],
            instructions="be terse",
            tools=[{"type": "web_search"}],
            stream=True,
        )
        self.assertEqual(payload["instructions"], "be terse")
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertTrue(payload["parallel_tool_calls"])
        self.assertTrue(payload["stream"])


class ExtractTextTest(unittest.TestCase):
    def test_responses_output_array(self):
        resp = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}]}
        self.assertEqual(api.extract_text(resp), "hello")

    def test_output_text_aggregate(self):
        self.assertEqual(api.extract_text({"output_text": "quick"}), "quick")

    def test_chat_completions_fallback(self):
        resp = {"choices": [{"message": {"content": "fallback"}}]}
        self.assertEqual(api.extract_text(resp), "fallback")

    def test_empty(self):
        self.assertEqual(api.extract_text({}), "")


class ExtractCitationsTest(unittest.TestCase):
    def test_citation_list(self):
        self.assertEqual(api.extract_citations({"citations": ["a", "b", 3]}), ["a", "b"])

    def test_none(self):
        self.assertEqual(api.extract_citations({}), [])


class DeltaTextTest(unittest.TestCase):
    def test_output_text_delta_string(self):
        self.assertEqual(api._delta_text({"type": "response.output_text.delta", "delta": "x"}), "x")

    def test_delta_dict_with_text(self):
        self.assertEqual(api._delta_text({"type": "response.output_text.delta", "delta": {"text": "y"}}), "y")

    def test_reasoning_delta_is_ignored(self):
        # Reasoning/other deltas must NOT leak into the visible answer stream.
        self.assertEqual(api._delta_text({"type": "response.reasoning.delta", "delta": "thinking..."}), "")

    def test_chat_completions_delta(self):
        self.assertEqual(api._delta_text({"choices": [{"delta": {"content": "z"}}]}), "z")

    def test_no_delta(self):
        self.assertEqual(api._delta_text({"type": "response.created"}), "")


class ChatStreamTest(unittest.TestCase):
    def test_assembles_text_and_citations(self):
        events = [
            sse({"type": "response.created"}),
            sse({"type": "response.output_text.delta", "delta": "Hel"}),
            sse({"type": "response.output_text.delta", "delta": "lo"}),
            sse({"type": "response.completed", "response": {"citations": ["https://x.ai"], "usage": {"total_tokens": 5}}}),
        ]
        stream = api.ChatStream(_FakeClient(events=events), model="grok-4", messages=[{"role": "user", "content": "hi"}])
        chunks = list(stream)
        self.assertEqual(chunks, ["Hel", "lo"])
        self.assertEqual(stream.text, "Hello")
        self.assertEqual(stream.citations, ["https://x.ai"])
        self.assertEqual(stream.usage, {"total_tokens": 5})

    def test_complete_non_streaming(self):
        resp = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}],
            "citations": ["https://src"],
            "usage": {"total_tokens": 9},
        }
        result = api.complete(_FakeClient(json_result=resp), model="grok-4", messages=[{"role": "user", "content": "q"}])
        self.assertEqual(result["text"], "answer")
        self.assertEqual(result["citations"], ["https://src"])
        self.assertEqual(result["usage"], {"total_tokens": 9})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
