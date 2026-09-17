"""Verified against the Swift suite's real fixtures.

Expected values come from LocalUsageReaderTests.swift, so these are not
self-referential: they assert the Python port agrees with the shipped macOS
implementation on the same bytes.
"""

from pathlib import Path

import pytest

from poketokenbar.providers.codex import CodexProvider, parse_rollout

FIXTURES = Path(__file__).resolve().parents[2] / "Tests" / "PokeTokenBarTests" / "Fixtures"
FORK = FIXTURES / "CodexFork"

pytestmark = pytest.mark.skipif(
    not FORK.is_dir(), reason="Swift fixtures not present"
)


def _entries(*names):
    out = []
    for name in names:
        out.extend(parse_rollout(FORK / name).entries)
    return out


def test_parent_total_matches_the_swift_expectation():
    entries = _entries("parent.jsonl")
    assert sum(e.total for e in entries) == 312_814
    assert len(entries) == 8


def test_fork_contributes_only_its_new_turns():
    # Swift expects 312_814 + 28_138 + 28_263 == 369_215. A fork replays the
    # parent's turns with fresh timestamps, so counting files naively would
    # report 994_843.
    deduped = CodexProvider.dedup_entries(_entries("parent.jsonl", "child.jsonl", "sibling.jsonl"))
    assert sum(e.total for e in deduped) == 369_215


def test_naive_concatenation_would_overcount():
    # Guards the dedup: without it the total nearly triples.
    raw = _entries("parent.jsonl", "child.jsonl", "sibling.jsonl")
    assert sum(e.total for e in raw) == 994_843


def test_dedup_keeps_the_forks_own_turns():
    deduped = CodexProvider.dedup_entries(_entries("parent.jsonl", "child.jsonl", "sibling.jsonl"))
    totals = {e.total for e in deduped}
    assert 28_138 in totals
    assert 28_263 in totals


def test_input_excludes_cached_tokens():
    # input is reported inclusive of cache; the entry must hold them apart or
    # the same tokens are counted twice.
    entry = parse_rollout(FORK / "parent.jsonl").entries[0]
    assert entry.input == 20_107 - 279 - 2_432
    assert entry.cache_read == 2_432
    assert entry.output == 279


def test_subagent_fixtures_parse_without_error():
    subagent = FIXTURES / "CodexSubagent"
    if not subagent.is_dir():
        pytest.skip("subagent fixtures absent")
    for path in sorted(subagent.glob("*.jsonl")):
        parse_rollout(path)  # must not raise
