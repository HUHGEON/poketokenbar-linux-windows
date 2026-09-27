import json

from poketokenbar.providers import claude


def _line(**over):
    obj = {
        "type": "assistant",
        "timestamp": "2026-08-18T20:50:59.023Z",
        "requestId": "req_1",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-5",
            "usage": {
                "input_tokens": 2,
                "output_tokens": 570,
                "cache_creation_input_tokens": 24_155,
                "cache_read_input_tokens": 16_203,
            },
        },
    }
    obj.update(over)
    return json.dumps(obj)


def test_parse_line_extracts_four_token_kinds():
    e = claude.parse_line(_line())
    assert e is not None
    assert (e.input, e.output, e.cache_write, e.cache_read) == (2, 570, 24_155, 16_203)
    assert e.total == 40_930
    assert e.model == "claude-opus-5"


def test_parse_line_id_is_message_id_joined_with_request_id():
    assert claude.parse_line(_line()).id == "msg_1|req_1"


def test_parse_line_ignores_non_assistant_rows():
    assert claude.parse_line(_line(type="user")) is None


def test_parse_line_ignores_rows_without_usage():
    obj = json.loads(_line())
    del obj["message"]["usage"]
    assert claude.parse_line(json.dumps(obj)) is None


def test_parse_line_survives_malformed_json():
    assert claude.parse_line("{not json") is None


def test_parse_line_ignores_nested_iterations_totals():
    # Real logs repeat the same counts inside usage.iterations[]. Summing them
    # would double-count every turn. Only top-level fields may be read.
    obj = json.loads(_line())
    obj["message"]["usage"]["iterations"] = [
        {
            "input_tokens": 2,
            "output_tokens": 570,
            "cache_read_input_tokens": 16_203,
            "cache_creation_input_tokens": 24_155,
        }
    ]
    assert claude.parse_line(json.dumps(obj)).total == 40_930


def test_dedup_keeps_the_largest_total_per_id():
    # Streaming and session resume re-log the same (message.id, requestId) with
    # a growing output while input/cacheRead stay fixed. Keeping the first
    # occurrence under-counts cost badly.
    partial = claude.parse_line(_line())
    complete = claude.parse_line(_line())
    partial.output = 10
    complete.output = 570
    kept = claude.dedup_keep_max([partial, complete])
    assert len(kept) == 1
    assert kept[0].output == 570


def test_dedup_keeps_distinct_ids():
    a = claude.parse_line(_line(requestId="req_1"))
    b = claude.parse_line(_line(requestId="req_2"))
    assert len(claude.dedup_keep_max([a, b])) == 2


def test_parse_file_dedups_within_the_file(tmp_path):
    f = tmp_path / "s.jsonl"
    small = json.loads(_line())
    small["message"]["usage"]["output_tokens"] = 1
    f.write_text(json.dumps(small) + "\n" + _line() + "\n", encoding="utf-8")
    entries = claude.parse_file(f)
    assert len(entries) == 1
    assert entries[0].output == 570


def test_parse_file_returns_empty_for_unreadable_path(tmp_path):
    assert claude.parse_file(tmp_path / "missing.jsonl") == []


def test_a_turn_logged_twice_keeps_the_time_it_first_happened():
    """Forking or resuming a session writes the same turn again with a later
    timestamp. Whichever copy holds the larger total used to decide the day, so
    tokens moved into a day they did not happen in (upstream e76a8e0)."""
    from datetime import datetime, timezone

    from poketokenbar.models import Entry
    from poketokenbar.providers.base import dedup_keep_max

    first = Entry(id="a", date=datetime(2026, 9, 17, 23, 50, tzinfo=timezone.utc),
                  local_day="2026-09-17", model="m", input=10)
    # The completed copy, written after midnight by a fork of that session.
    later = Entry(id="a", date=datetime(2026, 9, 18, 0, 10, tzinfo=timezone.utc),
                  local_day="2026-09-18", model="m", input=99)

    for order in ([first, later], [later, first]):
        kept = dedup_keep_max(list(order))
        assert len(kept) == 1
        assert kept[0].total == 99, "the completed copy is still the one kept"
        assert kept[0].local_day == "2026-09-17"
        assert kept[0].date == first.date
