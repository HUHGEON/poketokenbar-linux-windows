"""Codex rollout parsing and ownership-aware fork/subagent replay resolution."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from ..models import Entry
from .base import ScanningProvider, loads, local_day, parse_iso, to_int

PARSER_VERSION = 2
_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
           'output_tokens', 'reasoning_output_tokens', 'total_tokens')


def _vector(raw: dict) -> tuple[int, ...]:
    return tuple(to_int(raw.get(key)) for key in _FIELDS)


def _components(vector: tuple[int, ...]) -> int:
    return max(0, vector[0] - vector[1]) + vector[1] + vector[3]


@dataclass(slots=True)
class UsageEvent:
    entry: Entry
    state: tuple[tuple[int, ...], tuple[int, ...]] | None
    session_id: str | None


@dataclass(slots=True)
class ParsedRollout:
    entries: list[Entry]
    session_id: str | None
    path: str = ''
    parent_session_id: str | None = None
    is_subagent: bool = False
    events: list[UsageEvent] = field(default_factory=list)


def parse_rollout(path: Path) -> ParsedRollout:
    result = ParsedRollout([], None, str(path))
    model = 'codex'
    current_session = None
    previous_state = None
    turn = 0
    try:
        with path.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                if not any(marker in line for marker in ('session_meta', '"model"', 'token_count')):
                    continue
                try:
                    obj = loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                payload = obj.get('payload')
                if not isinstance(payload, dict):
                    continue
                if obj.get('type') == 'session_meta':
                    session = payload.get('id') or payload.get('session_id')
                    session = session if isinstance(session, str) else None
                    if result.session_id is None:
                        result.session_id = session
                        parent = payload.get('forked_from_id') or payload.get('parent_thread_id')
                        result.parent_session_id = parent if isinstance(parent, str) else None
                        source = payload.get('source')
                        result.is_subagent = payload.get('thread_source') == 'subagent' or (
                            isinstance(source, dict) and 'subagent' in source)
                    if session and session != current_session:
                        current_session = session
                        previous_state = None
                candidate_model = payload.get('model') or obj.get('model')
                if isinstance(candidate_model, str) and candidate_model:
                    model = candidate_model
                if payload.get('type') != 'token_count':
                    continue
                info = payload.get('info')
                if not isinstance(info, dict) or not isinstance(info.get('last_token_usage'), dict):
                    continue
                date = parse_iso(obj.get('timestamp'))
                if date is None:
                    continue
                last = _vector(info['last_token_usage'])
                raw_total = info.get('total_token_usage')
                cumulative = _vector(raw_total) if isinstance(raw_total, dict) else None
                state = (cumulative, last) if cumulative is not None else None
                positional_id = f'codex|{path}|{turn}'
                turn += 1
                if state is not None and current_session:
                    if previous_state == (current_session, state):
                        continue
                    previous_state = (current_session, state)
                else:
                    previous_state = None
                input_tokens, cached, output = max(0, last[0] - last[1]), last[1], last[3]
                total_only = input_tokens + cached + output == 0 and last[5] > 0
                if total_only and (cumulative is None or
                                   (_components(cumulative) == 0 and cumulative[5] > 0) or
                                   cumulative[5] == last[5]):
                    input_tokens = last[5]
                entry = Entry(positional_id, date, local_day(date), model,
                              input=input_tokens, output=output, cache_read=cached,
                              cost_unavailable=total_only)
                result.events.append(UsageEvent(entry, state, current_session))
    except OSError:
        return ParsedRollout([], None, str(path))
    result.entries = [event.entry for event in result.events]
    return result


def _fallback_replay_count(rollout: ParsedRollout) -> int:
    if rollout.is_subagent or not rollout.events:
        return 0
    count = 1
    while count < len(rollout.events):
        gap = (rollout.events[count].entry.date - rollout.events[count - 1].entry.date).total_seconds()
        if gap >= 1:
            break
        count += 1
    return count


def _owned(rollout: ParsedRollout, replay_count: int, inherited=()):
    history = list(inherited)
    entries = []
    epoch, previous_cumulative, previous_owner = 0, None, None
    for event in rollout.events[replay_count:]:
        owner = rollout.session_id if rollout.parent_session_id else (event.session_id or rollout.session_id)
        if owner != previous_owner:
            epoch, previous_cumulative, previous_owner = 0, None, owner
        prior = previous_cumulative
        if event.state:
            cumulative, last = event.state
            if prior and any(value < old for value, old in zip(cumulative, prior)):
                epoch += 1
            previous_cumulative = cumulative
        else:
            previous_cumulative = None
        entry = event.entry
        if owner and event.state:
            cumulative, last = event.state
            if entry.total == 0 and _components(last) == 0 and last[5] > 0 and prior and cumulative[5] > prior[5]:
                entry = replace(entry, input=last[5], cost_unavailable=True)
            fingerprint = '|'.join(','.join(map(str, vector)) for vector in event.state)
            entry = replace(entry, id=f'codex|{owner}|{epoch}|{fingerprint}')
        entries.append(entry)
        history.append(UsageEvent(entry, event.state, owner))
    return history, entries


def dedup_entries(entries: list[Entry]) -> list[Entry]:
    by_id = {}
    for entry in entries:
        previous = by_id.get(entry.id)
        if previous is None or entry.date.astimezone() < previous.date.astimezone():
            by_id[entry.id] = entry
    return list(by_id.values())


def resolve_rollouts(rollouts: list[ParsedRollout]) -> list[Entry]:
    by_session: dict[str, list[ParsedRollout]] = {}
    for rollout in rollouts:
        if rollout.session_id:
            by_session.setdefault(rollout.session_id, []).append(rollout)
    memo = {}

    def resolve(rollout, visiting):
        if rollout.path in memo:
            return memo[rollout.path]
        if rollout.path in visiting:
            return _owned(rollout, _fallback_replay_count(rollout))
        visiting = visiting | {rollout.path}
        best_count, best_history = 0, []
        for parent in by_session.get(rollout.parent_session_id, []):
            if parent.path == rollout.path:
                continue
            history, _ = resolve(parent, visiting)
            count = 0
            for child_event, parent_event in zip(rollout.events, history):
                if child_event.state is None or parent_event.state is None:
                    count = 0
                    break
                if child_event.state != parent_event.state:
                    break
                count += 1
            if count > best_count:
                best_count, best_history = count, history[:count]
        if not best_count and rollout.parent_session_id:
            best_count = _fallback_replay_count(rollout)
        result = _owned(rollout, best_count, best_history)
        memo[rollout.path] = result
        return result

    entries = []
    for rollout in sorted(rollouts, key=lambda r: r.path):
        entries.extend(resolve(rollout, set())[1])
    return dedup_entries(entries)


def session_roots(home: Path | None = None) -> list[Path]:
    root = (home or Path.home()) / '.codex'
    return [path for path in (root / 'sessions', root / 'archived_sessions') if path.is_dir()]


class CodexProvider(ScanningProvider):
    id = 'codex'
    display_name = 'Codex'
    reports_cost = True
    PARSER_VERSION = PARSER_VERSION

    def curated_roots(self) -> list[Path]:
        return session_roots(self._home)

    def parse_file(self, path: Path) -> list[Entry]:
        return resolve_rollouts([parse_rollout(path)])

    def scan_entries(self) -> list[Entry]:
        from ..cache import _decode, _encode
        rollouts = []
        live = set()
        for root in self.roots():
            for path in sorted(self.files(root)):
                key = str(path.resolve())
                if key in live:
                    continue
                live.add(key)
                signature = self.file_signature(path)
                if signature is None:
                    continue
                raw = self._cache.get_document('codex-rollout', path, *signature, self.PARSER_VERSION) if self._cache else None
                if raw is not None:
                    entries = _decode(raw['entries'])
                    events = [UsageEvent(entry,
                                        tuple(tuple(v) for v in state) if state else None, owner)
                              for entry, state, owner in zip(entries, raw['states'], raw['owners'])]
                    rollout = ParsedRollout(entries, raw['session'], str(path), raw['parent'], raw['subagent'], events)
                else:
                    rollout = parse_rollout(path)
                    if self._cache:
                        self._cache.put_document('codex-rollout', path, *signature, self.PARSER_VERSION, {
                            'entries': _encode(rollout.entries), 'session': rollout.session_id,
                            'parent': rollout.parent_session_id, 'subagent': rollout.is_subagent,
                            'states': [e.state for e in rollout.events],
                            'owners': [e.session_id for e in rollout.events],
                        })
                rollouts.append(rollout)
        if self._cache:
            self._cache.prune('codex-rollout', {r.path for r in rollouts})
        return resolve_rollouts(rollouts)

    dedup = staticmethod(dedup_entries)
    dedup_entries = staticmethod(dedup_entries)
