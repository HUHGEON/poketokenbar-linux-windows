"""Cursor dashboard usage with complete-page and account-scoped cache semantics."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen

from ..cache import _decode, _encode
from ..models import Entry
from .base import dedup_keep_max, to_int
from .sqlite_source import date_value, make_entry

URL = 'https://cursor.com/api/dashboard/get-filtered-usage-events'


@dataclass(slots=True)
class UsageResult:
    entries: list[Entry]
    is_authoritative: bool = False


def _subject(token: str) -> str | None:
    try:
        encoded = token.split('.')[1]
        payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        subject = payload.get('sub')
        return subject if isinstance(subject, str) and subject else None
    except (IndexError, ValueError, TypeError, AttributeError):
        return None


def account_identifier(token: str) -> str:
    decoded = unquote(token)
    subject = decoded.split('::', 1)[0] if '::' in decoded else _subject(decoded)
    return 'subject:' + subject if subject else 'token:' + hashlib.sha256(decoded.encode()).hexdigest()


def _send(request: Request):
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response), response.status
    except HTTPError as exc:
        return None, exc.code
    except (OSError, URLError, ValueError):
        return None, 0


def _tokens(value):
    if isinstance(value, str):
        try:
            value = int(value.replace(',', ''))
        except ValueError:
            return 0
    return to_int(value)


def parse_event(event: dict, index: int, since: datetime) -> Entry | None:
    from .base import parse_iso
    raw = event.get('timestamp')
    try:
        date = date_value(float(raw))
    except (TypeError, ValueError, OverflowError):
        date = parse_iso(raw)
    if date is None or date.astimezone() < since.astimezone():
        return None
    usage = event.get('tokenUsage')
    if not isinstance(usage, dict):
        return None
    model = event.get('model') or 'unknown'
    model = str(model)
    ident = event.get('id') or event.get('eventId') or event.get('requestId') or f'{date.isoformat()}|{model}|{index}'
    try:
        cost = float(usage['totalCents']) / 100
    except (KeyError, TypeError, ValueError, OverflowError):
        cost = None
    return make_entry(f'cursor|api|{ident}', date, model,
                      input=_tokens(usage.get('inputTokens')), output=_tokens(usage.get('outputTokens')),
                      cache_write=_tokens(usage.get('cacheWriteTokens')), cache_read=_tokens(usage.get('cacheReadTokens')),
                      cost=cost)


class CursorUsageAPI:
    def __init__(self, *, transport=None, cache_path: Path | None = None):
        self.transport = transport or _send
        self.cache_path = cache_path
        self._cache = None

    def _network(self, token: str, since: datetime, on_rejected=None) -> list[Entry] | None:
        entries = []
        bearer = False
        refreshed = False
        index = 0
        deadline = time.monotonic() + 120
        page = 1
        while page <= 200 and time.monotonic() < deadline:
            body = {'teamId': 0, 'startDate': str(round(since.timestamp() * 1000)),
                    'endDate': str(round(time.time() * 1000)), 'page': page, 'pageSize': 100}
            headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0',
                       'Origin': 'https://cursor.com', 'Referer': 'https://cursor.com/dashboard/usage'}
            if bearer:
                headers['Authorization'] = 'Bearer ' + unquote(token).split('::', 1)[-1]
            else:
                decoded = unquote(token)
                subject = _subject(decoded)
                cookie = f'{subject}::{decoded}' if subject and '::' not in decoded else token
                headers['Cookie'] = f'WorkosCursorSessionToken={cookie}'
            try:
                payload, status = self.transport(Request(URL, data=json.dumps(body).encode(), headers=headers))
            except (OSError, ValueError):
                return None
            if status in (401, 403) and not bearer:
                bearer = True
                continue
            if status in (401, 403) and not refreshed and on_rejected:
                refreshed = True
                replacement = on_rejected(token)
                if replacement:
                    token = replacement
                    bearer = False
                    continue
            if not 200 <= status < 300 or not isinstance(payload, dict):
                return None
            events = next((payload[key] for key in ('usageEventsDisplay', 'usageEvents', 'events')
                           if isinstance(payload.get(key), list)), None)
            if events is None or any(not isinstance(event, dict) for event in events):
                return None
            for event in events:
                parsed = parse_event(event, index, since)
                if parsed is not None:
                    entries.append(parsed)
                index += 1
            pagination = payload.get('pagination')
            pagination = pagination if isinstance(pagination, dict) else {}
            if isinstance(pagination.get('hasNextPage'), bool):
                more = pagination['hasNextPage']
            elif isinstance(pagination.get('numPages'), int):
                more = page < pagination['numPages']
            elif isinstance(payload.get('totalUsageEventsCount'), (int, str)):
                more = page * 100 < _tokens(payload['totalUsageEventsCount'])
            else:
                more = len(events) >= 100
            if not more:
                return dedup_keep_max(entries)
            if not events:
                return None
            page += 1
        return None

    def fetch(self, token: str, since: datetime, *, on_rejected=None) -> UsageResult:
        identity = account_identifier(token)
        entries = self._network(token, since, on_rejected)
        if entries is not None:
            self._cache = {'account': identity, 'fetched_at': time.time(),
                           'since': since.timestamp(), 'entries': _encode(entries)}
            if self.cache_path:
                try:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.cache_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(self._cache), encoding='utf-8')
                    temporary.replace(self.cache_path)
                except OSError:
                    pass
            return UsageResult(entries, True)
        cached = self._cache
        if cached is None and self.cache_path:
            try:
                cached = json.loads(self.cache_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        try:
            if (cached and cached['account'] == identity and
                    0 <= time.time() - cached['fetched_at'] <= 6 * 3600 and
                    cached['since'] <= since.timestamp()):
                return UsageResult([e for e in _decode(cached['entries']) if e.date.astimezone() >= since.astimezone()], True)
        except (KeyError, TypeError, ValueError):
            pass
        return UsageResult([])
