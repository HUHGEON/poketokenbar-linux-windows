import json
from datetime import datetime, timezone

import poketokenbar.providers.cursor as cursor


def test_dashboard_paginates_and_empty_success_is_authoritative(tmp_path):
    client_type = getattr(cursor, 'CursorUsageAPI', None)
    assert client_type is not None
    calls = []
    def send(request):
        body = json.loads(request.data)
        calls.append(body)
        assert body['startDate'].isdigit() and body['endDate'].isdigit()
        if body['page'] == 1:
            return {'usageEventsDisplay': [{'id': 'one', 'timestamp': '1789992000000', 'model': 'm', 'tokenUsage': {'inputTokens': 12, 'outputTokens': 3}}], 'pagination': {'hasNextPage': True}}, 200
        return {'usageEventsDisplay': [{'id': 'two', 'timestamp': '1789992000000', 'model': 'm', 'tokenUsage': {'inputTokens': 20}}], 'pagination': {'hasNextPage': False}}, 200
    client = client_type(transport=send, cache_path=tmp_path / 'cache.json')
    since = datetime(2026, 9, 1, tzinfo=timezone.utc)
    result = client.fetch('fake-token', since)
    assert result.is_authoritative and sum(e.total for e in result.entries) == 35
    assert len(calls) == 2
    empty = client_type(transport=lambda request: ({'events': []}, 200), cache_path=tmp_path / 'empty.json').fetch('fake', since)
    assert empty.is_authoritative and empty.entries == []


def test_dashboard_failure_cache_is_scoped_to_account_and_window(tmp_path):
    client_type = getattr(cursor, 'CursorUsageAPI', None)
    assert client_type is not None
    since = datetime(2026, 9, 1, tzinfo=timezone.utc)
    response = {'events': [{'id': 'one', 'timestamp': '1789992000000', 'tokenUsage': {'inputTokens': 12}}]}
    client = client_type(transport=lambda request: (response, 200), cache_path=tmp_path / 'cache.json')
    assert client.fetch('first-account', since).is_authoritative
    client.transport = lambda request: (None, 503)
    assert client.fetch('first-account', since).is_authoritative
    assert not client.fetch('other-account', since).is_authoritative
    assert not client.fetch('first-account', datetime(2026, 8, 1, tzinfo=timezone.utc)).is_authoritative


def test_failed_partial_dashboard_page_never_claims_authority(tmp_path):
    client_type = getattr(cursor, 'CursorUsageAPI', None)
    assert client_type is not None
    def send(request):
        body = json.loads(request.data)
        if body['page'] == 1:
            return {'events': [{'id': 'one', 'timestamp': '1789992000000', 'tokenUsage': {'inputTokens': 12}}], 'pagination': {'hasNextPage': True}}, 200
        return None, 503
    result = client_type(transport=send, cache_path=tmp_path / 'cache.json').fetch('fake', datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert not result.is_authoritative and result.entries == []


def test_provider_uses_authoritative_dashboard_even_when_local_rows_exist(tmp_path):
    api_type = getattr(cursor, 'CursorUsageAPI', None)
    assert api_type is not None
    import sqlite3
    root = tmp_path / '.config' / 'Cursor' / 'User' / 'globalStorage'
    root.mkdir(parents=True)
    db = sqlite3.connect(root / 'state.vscdb')
    db.execute('CREATE TABLE cursorDiskKV (key TEXT, value TEXT)')
    db.execute('INSERT INTO cursorDiskKV VALUES (?, ?)', ('bubbleId:old', json.dumps({'createdAt': datetime.now(timezone.utc).isoformat(), 'modelType': 'gpt-5.5', 'tokenCount': {'inputTokens': 100}})))
    db.commit()
    db.close()
    api = api_type(transport=lambda request: ({'events': []}, 200), cache_path=tmp_path / 'api.json')
    provider = cursor.CursorProvider(home=tmp_path, api=api, token_provider=lambda: 'fake')
    assert provider.scan_entries() == []
    api.transport = lambda request: (None, 503)
    provider._token_provider = lambda: None
    entries = provider.scan_entries()
    assert len(entries) == 1 and entries[0].total == 100
    assert entries[0].cost_unavailable


def test_dashboard_window_covers_week_crossing_month_boundary(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 10, 1, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(cursor, 'datetime', Clock)
    requests = []
    def send(request):
        requests.append(json.loads(request.data))
        return {'events': []}, 200
    api = cursor.CursorUsageAPI(transport=send, cache_path=tmp_path / 'cache.json')
    provider = cursor.CursorProvider(home=tmp_path, api=api, token_provider=lambda: 'fake')
    provider.scan_entries()
    assert int(requests[0]['startDate']) == int(datetime(2026, 9, 28).astimezone().timestamp() * 1000)


def test_dashboard_keeps_previous_month_tokens_in_current_week(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 10, 4, 12).astimezone()
    monkeypatch.setattr(cursor, 'datetime', Clock)
    rows = [
        {'id': 'september', 'timestamp': str(int(datetime(2026, 9, 30, 12).timestamp()*1000)), 'tokenUsage': {'inputTokens': 100}},
        {'id': 'october', 'timestamp': str(int(datetime(2026, 10, 2, 12).timestamp()*1000)), 'tokenUsage': {'inputTokens': 200}},
    ]
    def send(request):
        since = int(json.loads(request.data)['startDate'])
        return {'events': [row for row in rows if int(row['timestamp']) >= since]}, 200
    api = cursor.CursorUsageAPI(transport=send, cache_path=tmp_path / 'cache.json')
    provider = cursor.CursorProvider(home=tmp_path, api=api, token_provider=lambda: 'fake')
    periods = provider.fetch_periods('2026-10-04')
    assert periods['week']['tokens'] == 300
    assert periods['month']['tokens'] == 200


def test_dashboard_five_hour_block_spans_midnight_on_first_day(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 6, 1, 1).astimezone()
    monkeypatch.setattr(cursor, 'datetime', Clock)
    rows = [
        {'id': 'before-midnight', 'timestamp': str(int(datetime(2026, 5, 31, 22).timestamp()*1000)), 'tokenUsage': {'inputTokens': 100}},
        {'id': 'after-midnight', 'timestamp': str(int(datetime(2026, 6, 1, 0, 30).timestamp()*1000)), 'tokenUsage': {'inputTokens': 200}},
    ]
    def send(request):
        since = int(json.loads(request.data)['startDate'])
        return {'events': [row for row in rows if int(row['timestamp']) >= since]}, 200
    api = cursor.CursorUsageAPI(transport=send, cache_path=tmp_path / 'cache.json')
    provider = cursor.CursorProvider(home=tmp_path, api=api, token_provider=lambda: 'fake')
    assert provider.fetch_active_block(now=Clock.now()).total_tokens == 300
