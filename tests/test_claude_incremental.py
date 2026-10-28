import json
from pathlib import Path

import pytest

from poketokenbar.cache import ScanCache
from poketokenbar.providers import claude


def row(ident, amount):
    return json.dumps({'type':'assistant','timestamp':'2026-10-27T01:00:00Z','requestId':ident,
        'message':{'id':ident,'model':'m','usage':{'input_tokens':amount}}})


def setup_log(tmp_path, text):
    path=tmp_path/'.claude/projects/project/session.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(text)
    cache=ScanCache(tmp_path/'scan.db')
    return path,cache,claude.ClaudeProvider(cache=cache,home=tmp_path)


def test_append_reads_only_tail_and_reapplies_latest_cumulative_cost(tmp_path, monkeypatch):
    path,cache,provider=setup_log(tmp_path,row('a',10)+'\n'+json.dumps({'type':'cost-state','modelUsage':{'m':{'costUSD':1}}})+'\n')
    first=provider.scan_entries()
    assert sum(e.explicit_cost for e in first)==1
    calls=[]
    original=claude.parse_line
    monkeypatch.setattr(claude,'parse_line',lambda line:(calls.append(line),original(line))[1])
    with path.open('a') as f:
        f.write(row('a',20)+'\n'+row('b',30)+'\n'+json.dumps({'type':'cost-state','modelUsage':{'m':{'costUSD':8}}})+'\n')
    result=provider.scan_entries()
    assert len(calls)==2
    assert sum(e.total for e in result)==50
    assert sum(e.explicit_cost for e in result)==pytest.approx(8)
    assert sorted((e.id,e.total,e.explicit_cost) for e in result)==sorted((e.id,e.total,e.explicit_cost) for e in claude.parse_file(path))
    cache.close()


def test_partial_record_is_retried_and_not_counted_twice(tmp_path):
    second=row('b',20)
    path,cache,provider=setup_log(tmp_path,row('a',10)+'\n'+second[:len(second)//2])
    assert sum(e.total for e in provider.scan_entries())==10
    with path.open('a') as f:f.write(second[len(second)//2:])
    assert sum(e.total for e in provider.scan_entries())==30
    with path.open('a') as f:f.write('\n')
    assert sum(e.total for e in provider.scan_entries())==30
    cache.close()


@pytest.mark.parametrize('replacement',[row('b',22)+'\n',row('b',2)+'\n',row('different-id',222222)+'\n'])
def test_rewrites_and_truncation_replace_old_entries(tmp_path,replacement):
    path,cache,provider=setup_log(tmp_path,row('a',11)+'\n')
    provider.scan_entries()
    path.write_text(replacement)
    assert [(e.id,e.total) for e in provider.scan_entries()]==[(e.id,e.total) for e in claude.parse_file(path)]
    cache.close()


def test_tail_offset_survives_restart(tmp_path,monkeypatch):
    path,cache,provider=setup_log(tmp_path,row('a',10)+'\n')
    provider.scan_entries();cache.close()
    cache=ScanCache(tmp_path/'scan.db')
    provider=claude.ClaudeProvider(cache=cache,home=tmp_path)
    with path.open('a') as f:f.write(row('b',20)+'\n')
    calls=[];original=claude.parse_line
    monkeypatch.setattr(claude,'parse_line',lambda line:(calls.append(line),original(line))[1])
    assert sum(e.total for e in provider.scan_entries())==30
    assert len(calls)==1
    cache.close()


def test_deleted_logs_prune_both_entry_and_tail_cache(tmp_path):
    path,cache,provider=setup_log(tmp_path,row('a',10)+'\n')
    provider.scan_entries()
    path.unlink()
    assert provider.scan_entries()==[]
    assert cache._db.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]==0
    cache.close()


def test_failed_tail_read_is_retried_without_pinning_new_signature(tmp_path,monkeypatch):
    path,cache,provider=setup_log(tmp_path,row('a',10)+'\n')
    provider.scan_entries()
    with path.open('a') as f:f.write(row('b',20)+'\n')
    original=claude._parse_document
    def fail(*args,**kwargs):raise OSError('temporarily locked')
    monkeypatch.setattr(claude,'_parse_document',fail)
    assert sum(e.total for e in provider.scan_entries())==10
    monkeypatch.setattr(claude,'_parse_document',original)
    assert sum(e.total for e in provider.scan_entries())==30
    cache.close()
