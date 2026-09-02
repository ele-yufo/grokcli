"""Grok chat over the xAI Responses API.

Request shape (verified against the official Grok CLI and Moore's grok-cli):

    POST /v1/responses
    {"model", "input": [{"role", "content"}], "instructions"?, "stream",
     "store": false, "tools"?, "tool_choice"?, "parallel_tool_calls"?,
     "reasoning": {"effort"}?, "service_tier"?}

``reasoning.effort`` (none/low/medium/high) tunes how hard a reasoning model
thinks before responding; grok-4.6 rejects ``none`` with HTTP 400. ``service_tier: "priority"``
requests priority processing. The response carries an ``output[]`` array;
assistant text lives in items of type ``message`` under
``content[].type == "output_text"``. Streaming arrives as SSE events whose data
is JSON; text deltas appear on ``*.output_text.delta`` events. Parsing here is
intentionally tolerant of minor shape differences (and also accepts an OpenAI
``chat/completions`` shape as a fallback).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

from .. import models
from ..client import GrokClient
from ..errors import UsageError

RESPONSES_PATH = "/responses"


def _validated_effort(effort: Optional[str]) -> Optional[str]:
    """Validate a reasoning-effort value against the known set."""
    if effort is None:
        return None
    if effort not in models.REASONING_EFFORTS:
        raise UsageError(
            f"Invalid reasoning effort {effort!r}.",
            hint=f"Choose from: {', '.join(sorted(models.REASONING_EFFORTS))}.",
        )
    return effort


def build_payload(
    *,
    model: str,
    messages: Sequence[Mapping[str, str]],
    instructions: Optional[str] = None,
    stream: bool = False,
    tools: Optional[List[Dict[str, Any]]] = None,
    store: bool = False,
    effort: Optional[str] = None,
    priority: bool = False,
) -> Dict[str, Any]:
    """Assemble the Responses API request body."""
    payload: Dict[str, Any] = {
        "model": model,
        "input": [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": stream,
        "store": store,
    }
    if instructions:
        payload["instructions"] = instructions
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        payload["parallel_tool_calls"] = True
    effort = _validated_effort(effort)
    if effort:
        payload["reasoning"] = {"effort": effort}
    if priority:
        payload["service_tier"] = "priority"
    return payload


def complete(
    client: GrokClient,
    *,
    model: str,
    messages: Sequence[Mapping[str, str]],
    instructions: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    effort: Optional[str] = None,
    priority: bool = False,
) -> Dict[str, Any]:
    """Non-streaming completion. Returns ``{text, citations, usage, raw}``."""
    payload = build_payload(
        model=model, messages=messages, instructions=instructions, tools=tools,
        stream=False, effort=effort, priority=priority,
    )
    raw = client.request_json("POST", RESPONSES_PATH, json_body=payload)
    return {
        "text": extract_text(raw),
        "citations": extract_citations(raw),
        "usage": raw.get("usage") if isinstance(raw, dict) else None,
        "raw": raw,
    }


class ChatStream:
    """Iterate to consume assistant text deltas; metadata is filled as it streams.

    After iteration completes, :attr:`text`, :attr:`citations`, and :attr:`usage`
    hold the full assembled result.
    """

    def __init__(
        self,
        client: GrokClient,
        *,
        model: str,
        messages: Sequence[Mapping[str, str]],
        instructions: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        effort: Optional[str] = None,
        priority: bool = False,
    ) -> None:
        self._payload = build_payload(
            model=model, messages=messages, instructions=instructions, tools=tools,
            stream=True, effort=effort, priority=priority,
        )
        self._client = client
        self.text = ""
        self.citations: List[str] = []
        self.usage: Optional[Dict[str, Any]] = None

    def __iter__(self) -> Iterator[str]:
        for event in self._client.stream("POST", RESPONSES_PATH, json_body=self._payload):
            data = _parse_event_data(event.get("data"))
            if data is None:
                continue
            delta = _delta_text(data)
            if delta:
                self.text += delta
                yield delta
            self._capture_final(data)

    def _capture_final(self, data: Dict[str, Any]) -> None:
        event_type = str(data.get("type") or "")
        final = data.get("response") if isinstance(data.get("response"), dict) else None
        if final is None and "output" in data:
            final = data
        if final is None:
            return
        if event_type.endswith("completed") or "output" in final:
            if not self.text:
                self.text = extract_text(final)
            cites = extract_citations(final)
            if cites:
                self.citations = cites
            if isinstance(final.get("usage"), dict):
                self.usage = final["usage"]


def _parse_event_data(data: Optional[str]) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    try:
        parsed = json.loads(data)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _delta_text(data: Dict[str, Any]) -> str:
    """Extract an *answer* text chunk from a streaming event.

    Restricted to ``output_text`` deltas on purpose: the Responses API also emits
    ``reasoning``/``function_call``/``audio_transcript`` deltas, and a greedy
    "any event ending in delta" rule would splice the model's private reasoning
    into the visible answer.
    """
    event_type = str(data.get("type") or "")
    delta = data.get("delta")
    if "output_text.delta" in event_type:
        if isinstance(delta, str):
            return delta
        if isinstance(delta, dict) and isinstance(delta.get("text"), str):
            return delta["text"]
    # chat/completions-style streaming fallback (no event type, text under choices).
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        piece = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
        if isinstance(piece, dict) and isinstance(piece.get("content"), str):
            return piece["content"]
    return ""


def extract_text(response: Any) -> str:
    """Assemble assistant text from a Responses (or chat/completions) payload."""
    if not isinstance(response, dict):
        return ""
    aggregate = response.get("output_text")
    if isinstance(aggregate, str) and aggregate:
        return aggregate
    parts: List[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") not in (None, "message"):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("type") in ("output_text", "text"):
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)
    if parts:
        return "".join(parts)
    # chat/completions fallback.
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message", {})
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def extract_citations(response: Any) -> List[str]:
    """Collect citation URLs from a response, if any."""
    if not isinstance(response, dict):
        return []
    citations = response.get("citations")
    if isinstance(citations, list):
        return [c for c in citations if isinstance(c, str)]
    return []
