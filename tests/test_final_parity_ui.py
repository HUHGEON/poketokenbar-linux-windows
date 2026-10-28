import time
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from poketokenbar import l10n
from poketokenbar.ui.pet import DesktopPet
from poketokenbar.ui.reader import StateReader
from poketokenbar.ui.app import Window,TrayApp
from poketokenbar.notify import Notifier


def test_pet_context_menu_and_recent_limit_bubble(qt_app):
    opened=[];hidden=[]
    pet=DesktopPet(on_activate=lambda:opened.append(1),on_hide=lambda:hidden.append(1))
    state={'config':{'language':'ko'},'limit_alert':{'id':'a','created_at':time.time(),'title':'한도 경고','body':'Codex 80%'}}
    pet.update_state(state)
    assert pet._bubble.isVisible()
    assert pet._bubble.textFormat()==Qt.PlainText
    assert 'Codex 80%' in pet._bubble.text()
    assert pet.size().width()==pet.size().height()==96
    menu=pet.context_menu()
    assert [a.text() for a in menu.actions()]==['열기','펫 숨기기']
    menu.actions()[0].trigger();menu.actions()[1].trigger()
    assert opened==hidden==[1]
    pet._bubble.hide();pet.update_state(state)
    assert not pet._bubble.isVisible()
    pet.close();menu.close()


def test_stale_or_disabled_limit_notifications_do_not_show_bubble(qt_app):
    pet=DesktopPet()
    state={'config':{},'limit_alert':{'id':'old','created_at':time.time()-60,'title':'old','body':'old'}}
    pet.update_state(state)
    assert not pet._bubble.isVisible()
    state['config']['limit_notifications']=False
    state['limit_alert']={'id':'fresh','created_at':time.time(),'title':'fresh','body':'fresh'}
    pet.update_state(state)
    assert not pet._bubble.isVisible()
    pet.close()


def test_home_has_labeled_recap_on_quiet_days(qt_app,tmp_path):
    reader=StateReader(tmp_path/'unused')
    reader.state={'config':{'language':'ko'},'strings':l10n.catalogue('ko'),
                  'periods':{'week':{'tokens_compact':'0'},'month':{'tokens_compact':'1M'}}}
    w=Window(reader);w.refresh(reader.state)
    opener=w.panels['home'].findChild(QPushButton,'home_open_recap')
    assert opener and opener.text()=='사용량 돌아보기'
    opener.click()
    assert w.stack.currentWidget() is w.recap
    w.close()


def test_tray_has_summary_and_direct_shortcuts(qt_app,tmp_path,monkeypatch):
    reader=StateReader(tmp_path/'unused')
    reader.state={'strings':l10n.catalogue('ko'),'today':{'tokens_compact':'1M'},'config':{'floating_pet_enabled':True}}
    tray=TrayApp(qt_app,reader);tray._relabel_menu()
    assert '1M' in tray._summary_action.text() and not tray._summary_action.isEnabled()
    assert {'pokedex','settings','floating_pet'} <= tray._menu_actions.keys()
    assert tray._menu_actions['floating_pet'].text()=='펫 숨기기'
    monkeypatch.setattr(tray,'toggle_window',lambda:tray.window.show())
    tray._menu_actions['pokedex'].trigger()
    assert tray.window.stack.currentWidget() is tray.window.panels['collection']
    tray._menu_actions['settings'].trigger()
    assert tray.window.stack.currentWidget() is tray.window.settings
    tray.tray.hide();tray.window.close();tray.timer.stop()


def test_limit_alert_is_emitted_once_per_threshold_crossing():
    notifier=Notifier(send_fn=lambda *a,**k:None)
    notifier.limits({'codex:session':81},80,95,'ko')
    first=notifier.last_limit_alert
    assert 'Codex' in first['body']
    notifier.limits({'codex:session':82},80,95,'ko')
    assert notifier.last_limit_alert is first
    notifier.limits({'codex:session':96},80,95,'ko')
    assert notifier.last_limit_alert['id']!=first['id']
    assert notifier.last_limit_alert['critical']
