"""Codex turns that carry only total_tokens — upstream #278.

Ported from LocalUsageReaderTests.swift (232108c). These build their own
rollouts, so unlike test_codex.py they run without the Swift fixtures.
"""

import json

from poketokenbar.providers.codex import parse_rollout


def _usage(input_=0, cached=0, output=0, total=0):
    return {"input_tokens": input_, "cached_input_tokens": cached,
            "output_tokens": output, "reasoning_output_tokens": 0,
            "total_tokens": total}


def _token_count(ts, last, cumulative=None):
    info = {"last_token_usage": last}
    if cumulative is not None:
        info["total_token_usage"] = cumulative
    return {"type": "event_msg", "timestamp": ts,
            "payload": {"type": "token_count", "info": info}}


def _rollout(tmp_path, *events):
    path = tmp_path / "rollout-test.jsonl"
    meta = {"type": "session_meta", "timestamp": "2026-09-04T00:59:00.000Z",
            "payload": {"id": "solo"}}
    path.write_text("\n".join(json.dumps(e) for e in (meta, *events)) + "\n")
    return parse_rollout(path).entries


def test_counts_when_the_turn_is_the_whole_session_total(tmp_path):
    entries = _rollout(tmp_path, _token_count(
        "2026-09-04T01:29:58.417Z",
        last=_usage(total=51_293), cumulative=_usage(total=51_293)))
    assert [e.total for e in entries] == [51_293]
    assert (entries[0].input, entries[0].output, entries[0].cache_read) == (51_293, 0, 0)


def test_counts_when_there_is_no_cumulative_usage(tmp_path):
    entries = _rollout(tmp_path, _token_count(
        "2026-09-04T01:29:58.417Z", last=_usage(total=51_293)))
    assert [e.total for e in entries] == [51_293]


def test_counts_when_the_cumulative_grew_mid_session(tmp_path):
    entries = _rollout(
        tmp_path,
        _token_count("2026-09-04T01:00:00.000Z",
                     last=_usage(input_=1000, output=100, total=1100),
                     cumulative=_usage(input_=1000, output=100, total=1100)),
        _token_count("2026-09-04T01:01:00.000Z",
                     last=_usage(total=5000),
                     cumulative=_usage(input_=1000, output=100, total=6100)),
    )
    assert [e.total for e in entries] == [1100, 5000]


def test_a_fork_zero_context_turn_stays_zero(tmp_path):
    # The shape a fork writes after replaying its parent: cumulative unchanged,
    # components 0, only last.total_tokens set. Those tokens are not in the
    # session's growth, so counting them would inflate the fork.
    entries = _rollout(
        tmp_path,
        _token_count("2026-07-29T01:00:01.000Z",
                     last=_usage(input_=100, output=10, total=110),
                     cumulative=_usage(input_=100, output=10, total=110)),
        _token_count("2026-07-29T01:00:02.000Z",
                     last=_usage(total=6_742),
                     cumulative=_usage(input_=100, output=10, total=110)),
    )
    assert [e.total for e in entries] == [110, 0]


def test_a_turn_with_components_is_unchanged(tmp_path):
    entries = _rollout(tmp_path, _token_count(
        "2026-09-04T01:00:00.000Z",
        last=_usage(input_=1000, cached=400, output=50, total=1050),
        cumulative=_usage(input_=1000, cached=400, output=50, total=1050)))
    assert (entries[0].input, entries[0].cache_read, entries[0].output) == (600, 400, 50)
