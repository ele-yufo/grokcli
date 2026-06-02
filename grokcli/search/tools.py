"""Builders for xAI server-side search tools used in Responses API ``tools[]``.

These are xAI-specific tool *types* (not function tools): the model runs the
search loop server-side and returns citations. See the xAI tools reference.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def web_search_tool(
    *,
    allowed_domains: Optional[Sequence[str]] = None,
    excluded_domains: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    tool: Dict[str, Any] = {"type": "web_search"}
    if allowed_domains:
        tool["allowed_domains"] = list(allowed_domains)
    if excluded_domains:
        tool["excluded_domains"] = list(excluded_domains)
    return tool


def x_search_tool(
    *,
    allowed_handles: Optional[Sequence[str]] = None,
    excluded_handles: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    tool: Dict[str, Any] = {"type": "x_search"}
    if allowed_handles:
        tool["allowed_x_handles"] = list(allowed_handles)
    if excluded_handles:
        tool["excluded_x_handles"] = list(excluded_handles)
    return tool


def build_tools(*, web: bool = False, x: bool = False) -> List[Dict[str, Any]]:
    """Return the requested search tools as a Responses ``tools[]`` list."""
    tools: List[Dict[str, Any]] = []
    if web:
        tools.append(web_search_tool())
    if x:
        tools.append(x_search_tool())
    return tools
