import json
import sqlite3
from datetime import datetime,timezone

import pytest
from poketokenbar import cursor_auth,cursor_limits,limits
from poketokenbar.providers.cursor_api import CursorUsageAPI


def login(root,access='old',refresh='one'):
    root.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(root/'state.vscdb') as db:
        db.execute('CREATE TABLE IF NOT EXISTS ItemTable(key TEXT PRIMARY KEY,value TEXT)')
        db.executemany('INSERT OR REPLACE INTO ItemTable VALUES(?,?)',[
            ('cursorAuth/accessToken',access),('cursorAuth/refreshToken',refresh)])


def test_usage_refresh_is_shared_with_quota_and_preserves_sqlite(tmp_path):
    root=tmp_path/'login';login(root);env={'CURSOR_DATA_DIR':str(root)}
    credential=cursor_auth.current(tmp_path,env);grants=[]
    def grant(request):
        grants.append(json.loads(request.data)['refresh_token'])
        return {'access_token':'fresh','refresh_token':'two'}
    def refresh(token):
        return cursor_auth.refresh(credential,home=tmp_path,env=env,http=grant).access_token
    headers=[]
    def send(request):
        header=request.get_header('Cookie') or request.get_header('Authorization');headers.append(header)
        return ({'events':[]},200) if 'fresh' in header else (None,401)
    result=CursorUsageAPI(transport=send).fetch('old',datetime(2026,10,1,tzinfo=timezone.utc),on_rejected=refresh)
    assert result.is_authoritative and grants==['one']
    def quota(request):
        assert request.get_header('Authorization')=='Bearer fresh'
        return {'planUsage':{'limit':100,'includedSpend':25}}
    assert cursor_limits.CursorProvider(tmp_path,env,quota).fetch()['utilization']==25
    assert cursor_limits.read_auth(tmp_path,env)['accessToken']=='old'
    second=cursor_auth.current(tmp_path,env)
    cursor_auth.refresh(second,home=tmp_path,env=env,http=grant)
    assert grants==['one','two']


def test_quota_refresh_is_shared_with_usage_and_root_changes_clear_it(tmp_path):
    root=tmp_path/'first';login(root);env={'CURSOR_DATA_DIR':str(root)}
    def http(request):
        if request.full_url==cursor_auth.TOKEN_URL:return {'access_token':'fresh'}
        if request.get_header('Authorization')=='Bearer old':raise limits.HTTPStatusError(403)
        return {'planUsage':{'limit':100,'includedSpend':20}}
    cursor_limits.CursorProvider(tmp_path,env,http).fetch()
    assert cursor_auth.current(tmp_path,env).access_token=='fresh'
    other=tmp_path/'other';login(other,'old','unrelated')
    assert cursor_auth.current(tmp_path,{'CURSOR_DATA_DIR':str(other)}).access_token=='old'
    login(root,'changed','new-refresh')
    assert cursor_auth.current(tmp_path,env).access_token=='changed'


def test_override_is_not_refreshed_and_account_change_during_grant_is_rejected(tmp_path):
    root=tmp_path/'login';login(root);env={'CURSOR_DATA_DIR':str(root),'CURSOR_SESSION_TOKEN':'manual'}
    rejected=cursor_auth.current(tmp_path,env)
    with pytest.raises(limits.AuthExpiredError):
        cursor_auth.refresh(rejected,home=tmp_path,env=env,http=lambda r:pytest.fail('must not refresh'))
    env.pop('CURSOR_SESSION_TOKEN');rejected=cursor_auth.current(tmp_path,env)
    def grant(request):
        login(root,'new-account','other-refresh')
        return {'access_token':'wrong-account'}
    with pytest.raises(limits.AuthExpiredError):cursor_auth.refresh(rejected,home=tmp_path,env=env,http=grant)
    assert cursor_auth.current(tmp_path,env).access_token=='new-account'


def test_failed_grant_retains_refresh_for_retry_and_logout_discards_grant(tmp_path):
    root=tmp_path/'login';login(root);env={'CURSOR_DATA_DIR':str(root)}
    rejected=cursor_auth.current(tmp_path,env)
    def failure(request):raise limits.HTTPStatusError(503)
    with pytest.raises(limits.HTTPStatusError):cursor_auth.refresh(rejected,home=tmp_path,env=env,http=failure)
    fresh=cursor_auth.refresh(rejected,home=tmp_path,env=env,http=lambda r:{'access_token':'fresh'})
    assert fresh.refresh_token=='one'
    with sqlite3.connect(root/'state.vscdb') as db:db.execute('DELETE FROM ItemTable')
    assert cursor_auth.current(tmp_path,env) is None
    login(root)
    assert cursor_auth.current(tmp_path,env).access_token=='old'
