"""Exercise the detail UI using species data, including reference-only entries."""
import copy
import os
import sys
from pathlib import Path

import pytest
pytest.importorskip('PySide6')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton
from poketokenbar import commands, l10n
from poketokenbar.ui.app import Window
from poketokenbar.ui.reader import StateReader
from poketokenbar.ui.widgets import Sprite

_APP = QApplication.instance() or QApplication([])
sys._pokemon_details_app = (_APP, [])


def sample_state():
    return {'strings': l10n.catalogue('ko'), 'config': {'language': 'ko'},
      'today': {}, 'companion': {}, 'catch_log': [], 'dex': [{
      'species_id': 1, 'name': '이상해씨', 'rarity': 'common', 'types': ['grass','poison'],
      'profiles': [{'level': 10, 'gender': 'male', 'nature': 'hardy', 'ability': '심록',
        'moves': [{'name':'tackle','display_name':'몸통박치기','learned_at':1}],
        'ivs': {'hp': 31}, 'stats': [{'name':'hp','value':33}]}],
      'details_status': 'ready', 'details': {'height':7, 'weight':69, 'base_stat_total':318,
        'base_stats': {'hp':45,'attack':49,'defense':49,'special-attack':65,'special-defense':65,'speed':45},
        'abilities': [{'name':'overgrow','display_name':'심록','is_hidden':False},
                      {'name':'chlorophyll','display_name':'엽록소','is_hidden':True}],
        'moves': [{'name':'tackle','display_name':'몸통박치기','learn_methods':[{'method':'level-up','level':1}]},
                  {'name':'solar-beam','display_name':'솔라빔','learn_methods':[{'method':'machine','level':0}]},
                  {'name':'skull-bash','display_name':'로케트박치기','learn_methods':[{'method':'egg','level':0}]}]}}]}


@pytest.fixture
def ui(monkeypatch,tmp_path):
    queue=[]
    monkeypatch.setattr(commands,'enqueue',lambda name,args:queue.append((name,args)))
    reader=StateReader(tmp_path/'unused.json')
    reader.state=sample_state()
    window=Window(reader)
    sys._pokemon_details_app[1].append(window)
    window.refresh(reader.state)
    window.show_tab('collection')
    yield window,reader,queue
    window.close()


def texts(panel):
    return [w.text() for w in panel.findChildren(QLabel)]


def test_complete_moves_methods_species_data_and_stats(ui):
    window,reader,queue=ui
    panel=window.panels['collection']
    panel._open_detail(reader.state['dex'][0])
    shown=texts(panel)
    assert all(t in shown for t in ['전체 기술 (3개)','솔라빔','로케트박치기','기술머신','교배','0.7 m','6.9 kg','318'])
    assert any('엽록소' in t for t in shown)
    assert panel.findChildren(QProgressBar)
    assert queue==[('load_pokemon_details',{'species_id':1})]


def test_reference_only_stage_keeps_base_stats_and_complete_moves(ui):
    window,reader,_=ui
    entry=reader.state['dex'][0]
    entry['profiles']=[]
    panel=window.panels['collection']
    panel._open_detail(entry)
    assert '종족값' in texts(panel)
    assert '솔라빔' in texts(panel)
    assert len(panel.findChildren(QProgressBar))==6


def test_retry_button_queues_detail_request(ui):
    window,reader,queue=ui
    entry=reader.state['dex'][0]
    entry['details_status']='error'
    entry['details']=None
    panel=window.panels['collection']
    panel._open_detail(entry)
    retry=next(b for b in panel.findChildren(QPushButton) if b.text()=='상세 정보 다시 불러오기')
    retry.click()
    assert len(queue)==2
    assert '포켓몬 상세 정보를 불러오지 못했어요.' in texts(panel)


def test_home_sprite_links_to_collected_entry(ui):
    window,reader,queue=ui
    reader.state['dex'][0]['profiles'].append({**reader.state['dex'][0]['profiles'][0], 'instance_id':'active'})
    reader.state['companion']={'stage':'raising','species_id':1,'profile':{'types':['grass'],'instance_id':'active'}}
    window.refresh(reader.state)
    window.show_tab('home')
    QTest.mouseClick(window.panels['home'].sprite,Qt.LeftButton)
    assert window.panels['collection']._detail_species==1
    assert window.panels['collection']._profile_index==1
    assert queue[-1]==('load_pokemon_details',{'species_id':1})


def test_wheel_pages_grid_without_scrolling_detail(ui):
    window,reader,_=ui
    first=reader.state['dex'][0]
    reader.state['dex']=[{**copy.deepcopy(first),'species_id':sid} for sid in range(1,34)]
    panel=window.panels['collection']
    panel.refresh(reader.state,force=True)
    def wheel():
        event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(),QPoint(0,-120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
        QApplication.sendEvent(panel.scroll.viewport(),event)
    wheel()
    assert panel._page==1
    panel._open_detail(reader.state['dex'][0])
    wheel()
    assert panel._page==1
    panel._close_detail()
    assert panel._page==1
