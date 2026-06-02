"""Tests for the server-side search tool builders."""

from __future__ import annotations

import unittest

from grokcli.search import tools


class BuildToolsTest(unittest.TestCase):
    def test_none_selected(self):
        self.assertEqual(tools.build_tools(), [])

    def test_both_selected(self):
        built = tools.build_tools(web=True, x=True)
        self.assertEqual(sorted(t["type"] for t in built), ["web_search", "x_search"])

    def test_only_web(self):
        self.assertEqual(tools.build_tools(web=True), [{"type": "web_search"}])


class ToolFiltersTest(unittest.TestCase):
    def test_web_search_domains(self):
        tool = tools.web_search_tool(allowed_domains=["x.ai"], excluded_domains=["spam.com"])
        self.assertEqual(tool["type"], "web_search")
        self.assertEqual(tool["allowed_domains"], ["x.ai"])
        self.assertEqual(tool["excluded_domains"], ["spam.com"])

    def test_x_search_handles(self):
        tool = tools.x_search_tool(allowed_handles=["xai"], excluded_handles=["bot"])
        self.assertEqual(tool["allowed_x_handles"], ["xai"])
        self.assertEqual(tool["excluded_x_handles"], ["bot"])

    def test_bare_tools_have_only_type(self):
        self.assertEqual(tools.web_search_tool(), {"type": "web_search"})
        self.assertEqual(tools.x_search_tool(), {"type": "x_search"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
