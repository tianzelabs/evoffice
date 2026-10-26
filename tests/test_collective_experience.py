"""Causal episode retrieval and attributed, append-only collective knowledge."""
from datetime import datetime,timedelta,timezone

import pytest
from fastapi.testclient import TestClient

from agents.common.experience import build_atlas,state_features,retrieve,epoch
from server.app import create_app
from server.market import FakeMarket
from server.store import Store
from server import knowledge
from server.evaluator import service

T0=datetime(2020,1,1,tzinfo=timezone.utc)


def dataset(n=5000):
    bars=[{'m':(T0+timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S'),
           'o':100.,'h':100.,'l':100.,'c':100.,'v':1.} for i in range(n)]
    rates={str(int((T0+timedelta(hours=i)).timestamp())):1e-5 for i in range(n//60+2)}
    return {'bars':bars,'funding':rates}


def atlas(data):
    return build_atlas(data,int((T0+timedelta(days=10)).timestamp()),.0005)


def test_features_ignore_every_candle_not_yet_closed():
    d=dataset();cut=int((T0+timedelta(hours=12)).timestamp())
    before=state_features(d['bars'],cut)
    for b in d['bars'][720:]:b['c']=1_000_000.
    assert state_features(d['bars'],cut)==before
    assert before['information_cutoff']==(T0+timedelta(hours=12)).isoformat()


def test_episode_costs_funding_and_intrahold_excursions():
    d=dataset();d['bars'][540].update(h=110.,l=90.)
    a=atlas(d);first=a['episodes'][0]
    assert first['decision_time']==(T0+timedelta(hours=8,minutes=1)).isoformat()
    h=first['outcomes']['4']
    assert h['net_long_proxy_bps']==pytest.approx(-10.4)
    assert h['net_short_proxy_bps']==pytest.approx(-9.6)
    assert h['long_mae_bps']==pytest.approx(1000)
    assert h['short_mae_bps']==pytest.approx(1000)
    assert a['episode_count'] and a['eligible_grid_points']==a['episode_count']


def test_gaps_and_missing_funding_are_not_silently_filled():
    d=dataset();del d['funding'][str(int((T0+timedelta(hours=10)).timestamp()))]
    h=atlas(d)['episodes'][0]['outcomes']['4']
    assert not h['funding_complete'] and h['net_long_proxy_bps'] is None
    assert h['taker_fee_only_long_bps']==pytest.approx(-10)
    d=dataset();del d['bars'][700]
    a=atlas(d)
    assert a['excluded_for_gaps']>0


def test_training_boundary_and_unknown_outcome_cutoff_are_enforced():
    d=dataset()
    with pytest.raises(ValueError,match='boundary'):
        build_atlas(d,int(T0.timestamp()),.0005)
    a=atlas(d)
    early=state_features(d['bars'],int((T0+timedelta(hours=9)).timestamp()))
    assert retrieve(a,early)['analogues']==[]


def test_matching_never_uses_profit_to_choose_cases():
    d=dataset();a=atlas(d)
    state=state_features(d['bars'],epoch(d['bars'][-1]['m'])+60)
    original=[e['id'] for e in retrieve(a,state,5)['analogues']]
    for i,e in enumerate(a['episodes']):
        for outcome in e['outcomes'].values():outcome['net_long_proxy_bps']=i*10000
    assert [e['id'] for e in retrieve(a,state,5)['analogues']]==original


@pytest.fixture
def api(tmp_path):
    store=Store(str(tmp_path/'o.db'));market=FakeMarket()
    tokens={'m':{'id':'manager','role':'manager'},'t':{'id':'trader-1','role':'trader'}}
    return TestClient(create_app(store,market,tokens,backstop_every_s=0)),store


def entry(**overrides):
    return {'topic':'holding-thesis','perspective':'trend','kind':'hypothesis','claim':'An explicit conjecture',
            'information_cutoff':T0.isoformat(),'evidence':['train:example'], 'parent_ids':[],
            'limitations':'Unproved; shared source is not independent evidence',**overrides}


def test_contributors_cannot_impersonate_or_rewrite_each_other(api):
    c,_=api
    assert c.get('/knowledge').status_code==401
    first=c.post('/knowledge',json=entry(actor='someone-else'),headers={'Authorization':'Bearer m'}).json()
    assert first['actor']=='manager' and first['payload']['provenance']=='agent_submitted'
    correction=c.post('/knowledge',json=entry(kind='correction',parent_ids=[first['id']],claim='A counterexample'),
                      headers={'Authorization':'Bearer t'})
    assert correction.status_code==200
    rows=c.get('/knowledge',params={'topic':'holding-thesis'},headers={'Authorization':'Bearer m'}).json()
    assert rows[0]['actor']=='trader-1' and rows[1]['payload']['claim']=='An explicit conjecture'
    assert c.delete('/knowledge/'+str(first['id']),headers={'Authorization':'Bearer m'}).status_code in [404,405]


def test_future_claims_and_unknown_parents_are_rejected(api):
    c,_=api;headers={'Authorization':'Bearer m'}
    future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    assert c.post('/knowledge',json=entry(information_cutoff=future),headers=headers).status_code==422
    assert c.post('/knowledge',json=entry(parent_ids=[999999]),headers=headers).status_code==422
    later=c.post('/knowledge',json=entry(information_cutoff=(T0+timedelta(days=1)).isoformat()),headers=headers).json()
    assert c.post('/knowledge',json=entry(parent_ids=[later['id']]),headers=headers).status_code==422


def test_actual_trade_results_are_automatically_available_as_measured_memory(api):
    c,store=api;h={'Authorization':'Bearer t'}
    p=c.post('/positions/open',json={'side':'long','size':.001},headers=h).json()
    assert 'id' in p
    close=c.post(f"/positions/{p['id']}/close",headers=h)
    assert close.status_code==200
    rows=c.get('/knowledge',params={'topic':'paper-execution'},headers=h).json()
    assert rows[0]['payload']['provenance']=='office_measured'
    assert rows[0]['payload']['measured']['pnl']<0
    # Retrieval does not write another copy of the outcome.
    n=store.q('SELECT COUNT(*) AS n FROM events')[0]['n']
    c.get('/knowledge',headers=h)
    assert store.q('SELECT COUNT(*) AS n FROM events')[0]['n']==n


def test_experience_service_reads_only_development_source(tmp_path,monkeypatch):
    source=tmp_path/'train.json';source.write_text(__import__('json').dumps(dataset()))
    monkeypatch.setattr(service,'CACHE',tmp_path)
    monkeypatch.setattr(service,'train_file',lambda market:source)
    def forbidden(market):raise AssertionError('heldout must never be opened')
    monkeypatch.setattr(service,'heldout_file',forbidden)
    class Development(FakeMarket):
        def bars(self,pair,minutes):return dataset()['bars'][-minutes:]
    report=knowledge.experience(Development())
    assert report['source_kind']=='development_train'
    assert report['bars']==5000 and report['source_sha256']
