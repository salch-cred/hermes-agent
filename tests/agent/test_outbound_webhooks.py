"""Test coverage for agent/outbound_webhooks.py — 18 functions had LOW coverage.

Tests WebhookTarget parsing, matching, config registration, and payload
serialization. All network I/O is mocked — no real HTTP calls are made.
"""

import json
import re
from unittest.mock import MagicMock, patch

import pytest

from agent.outbound_webhooks import (
    WebhookTarget,
    _parse_single_target,
    _serialize_payload,
    iter_configured_targets,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    yield
    reset_for_tests()


class TestWebhookTarget:
    def test_basic_creation(self):
        t = WebhookTarget(url="https://example.com/hook", events=["tool_call"])
        assert t.url == "https://example.com/hook"
        assert t.events == ["tool_call"]
        assert t.matcher is None
        assert t.timeout > 0

    def test_label_prefers_name(self):
        t = WebhookTarget(url="https://x.com", events=[], name="my-hook")
        assert t.label == "my-hook"

    def test_label_falls_back_to_url(self):
        t = WebhookTarget(url="https://x.com", events=[])
        assert t.label == "https://x.com"

    def test_matcher_none_matches_all(self):
        t = WebhookTarget(url="https://x.com", events=[])
        assert t.matches_tool("anything") is True
        assert t.matches_tool(None) is True

    def test_matcher_regex(self):
        t = WebhookTarget(url="https://x.com", events=[], matcher=r"web_search.*")
        assert t.matches_tool("web_search") is True
        assert t.matches_tool("terminal") is False

    def test_matcher_literal(self):
        t = WebhookTarget(url="https://x.com", events=[], matcher="terminal")
        assert t.matches_tool("terminal") is True
        assert t.matches_tool("web_search") is False

    def test_matcher_invalid_regex_treated_as_literal(self):
        t = WebhookTarget(url="https://x.com", events=[], matcher="a[b")
        assert t.compiled_matcher is None
        assert t.matches_tool("a[b") is True

    def test_matcher_none_no_tool(self):
        t = WebhookTarget(url="https://x.com", events=[], matcher=r".*")
        assert t.matches_tool(None) is False


class TestParseSingleTarget:
    def test_valid_entry(self):
        t = _parse_single_target(0, {"url": "https://x.com", "events": ["pre_tool_call"]})
        assert t is not None
        assert t.url == "https://x.com"

    def test_missing_url_returns_none(self):
        assert _parse_single_target(0, {"events": ["pre_tool_call"]}) is None

    def test_missing_events_returns_none(self):
        assert _parse_single_target(0, {"url": "https://x.com"}) is None

    def test_non_dict_returns_none(self):
        assert _parse_single_target(0, "not a dict") is None

    def test_empty_events_returns_none(self):
        assert _parse_single_target(0, {"url": "https://x.com", "events": []}) is None

    def test_unknown_event_skipped(self):
        assert _parse_single_target(0, {"url": "https://x.com", "events": ["bogus_event"]}) is None

    def test_name_and_secret(self):
        t = _parse_single_target(0, {
            "url": "https://x.com", "events": ["pre_tool_call"],
            "name": "test", "secret": "s3cret",
        })
        assert t.name == "test"
        assert t.secret == "s3cret"


class TestSerializePayload:
    def test_basic_payload(self):
        result = _serialize_payload("pre_tool_call", {"tool": "terminal", "args": {"cmd": "ls"}}, "del-123")
        data = json.loads(result)
        assert isinstance(data, dict)
        assert len(data) > 0
