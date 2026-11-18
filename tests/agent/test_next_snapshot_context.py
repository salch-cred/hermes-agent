"""#157480: a -next snapshot must not inherit its family's context window."""

from agent.model_metadata import _longest_key_match, _is_unverified_snapshot

TABLE = {"qwen3.8-flash": 1_000_000, "qwen3.8-flash-next": 524_288}


def test_next_snapshot_does_not_inherit_family_entry():
    family_only = {"qwen3.8-flash": 1_000_000}
    assert _longest_key_match(family_only, "qwen3.8-flash-next") is None


def test_explicit_next_entry_still_wins():
    assert _longest_key_match(TABLE, "qwen3.8-flash-next") == ("qwen3.8-flash-next", 524_288)


def test_family_route_unchanged():
    family_only = {"qwen3.8-flash": 1_000_000}
    assert _longest_key_match(family_only, "qwen3.8-flash") == ("qwen3.8-flash", 1_000_000)


def test_vendor_prefixed_snapshot_also_skips_family():
    family_only = {"qwen3.8-flash": 1_000_000}
    assert _longest_key_match(family_only, "qwen/qwen3.8-flash-next") is None


def test_other_suffixes_still_inherit():
    family_only = {"qwen3.8-flash": 1_000_000}
    assert _longest_key_match(family_only, "qwen3.8-flash-turbo") == ("qwen3.8-flash", 1_000_000)


def test_snapshot_predicate_is_narrow():
    assert _is_unverified_snapshot("qwen3.8-flash-next", "qwen3.8-flash")
    assert not _is_unverified_snapshot("qwen3.8-flash", "qwen3.8-flash")
    assert not _is_unverified_snapshot("qwen3.8-flash-next", "qwen3.8-flash-next")
    assert not _is_unverified_snapshot("other-next", "qwen3.8-flash")
