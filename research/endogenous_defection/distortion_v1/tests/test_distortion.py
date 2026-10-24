from pathlib import Path

from research.endogenous_defection.auction import Session, make_market, run_rounds, snapshot
from research.endogenous_defection.config import Protocol
from research.endogenous_defection.information_study import make_plan
from research.endogenous_defection.io import read_jsonl
from research.endogenous_defection.observations import ObservationMarket, mask_visible
from research.endogenous_defection.distortion_v1.observation import DistortionMarket
from src.continuous_double_auction.cda_types import MarketRound


def fixture(tmp_path, cls=DistortionMarket):
    protocol=Protocol.model_validate(make_plan([20],'synthetic')['jobs'][0]['config'])
    session=Session(protocol,None,'synthetic',200,tmp_path/'events.jsonl')
    market=make_market(protocol,session,20,market_class=cls)
    market.observation_seed=20
    return protocol,session,market


def common(market, number=1):
    return dict(round_num=number,bid_queue=list(market.buyer_bid_queue),
        ask_queue=list(market.seller_ask_queue),past_bids_and_asks=market.formatted_past_bids_and_asks,
        past_trades=market.formatted_past_trades)


def test_distortion_preserves_count_identities_own_quotes_and_true_state(tmp_path):
    _,_,market=fixture(tmp_path)
    market.distortion_log=tmp_path/'distortions.jsonl'
    observer=market.sellers[0]
    asks={s.id:83.0+i*.1 for i,s in enumerate(market.sellers)}
    market.seller_ask_queue=sorted([(v,k) for k,v in asks.items()],reverse=True)
    market.rounds=[MarketRound(round_number=1,seller_asks=asks,buyer_bids={b.id:82.0 for b in market.buyers})]
    before=snapshot(market)
    original=common(market,2)
    rendered=market.observation_for(observer,original)
    assert len(rendered['ask_queue'])==len(original['ask_queue'])
    shown={owner:price for price,owner in rendered['ask_queue']}
    assert set(shown)==set(asks) and shown[observer.id]==asks[observer.id]
    selected=[k for k in asks if k!=observer.id and not mask_visible(20,observer.id,k,1)]
    assert selected
    for owner,price in asks.items():
        expected=round(price+10,2) if owner in selected else price
        assert shown[owner]==expected
        assert f'{owner} ask ${expected}' in rendered['past_bids_and_asks']
    assert rendered['ask_queue']==sorted(rendered['ask_queue'],reverse=True)
    assert rendered['bid_queue']==original['bid_queue']
    assert rendered['past_trades']==original['past_trades']
    assert snapshot(market)==before
    assert market.observation_for(market.buyers[0],original)==original
    records=read_jsonl(market.distortion_log)
    r=records[0]
    assert all(q['offset'] in (0,10) for q in r['current_quotes'])
    assert {q['owner']:q['displayed_price'] for q in r['current_quotes']}=={
        q['owner']:q['displayed_price'] for q in r['historical_quotes']}


def test_no_clipping_or_own_quote_falsification(tmp_path):
    _,_,market=fixture(tmp_path)
    seller=market.sellers[0].id
    rival=next(s.id for s in market.sellers if s.id!=seller and not mask_visible(20,seller,s.id,0))
    assert market.quote(seller,rival,0,98.5)['displayed_price']==108.5
    assert market.quote(seller,seller,0,98.5)['displayed_price']==98.5


def test_disabled_distortion_matches_truthful_parent_rendering(tmp_path):
    first=tmp_path/'a'; second=tmp_path/'b'; first.mkdir(); second.mkdir()
    _,_,original=fixture(first,ObservationMarket)
    _,_,distortion=fixture(second)
    distortion.distortion_enabled=False
    for a,b in zip(original.sellers+original.buyers,distortion.sellers+distortion.buyers):
        assert original.observation_for(a,common(original))==distortion.observation_for(b,common(distortion))


def test_real_market_clears_true_orders_under_fabricated_observations(tmp_path):
    a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir()
    protocol,_,truth=fixture(a,ObservationMarket)
    _,_,distorted=fixture(b)
    distorted.distortion_log=b/'distortions.jsonl'
    run_rounds(truth,2,protocol,a/'rounds.jsonl','warmup',truth.sellers[0].id)
    run_rounds(distorted,2,protocol,b/'rounds.jsonl','warmup',distorted.sellers[0].id)
    assert [r.model_dump() for r in truth.rounds]==[r.model_dump() for r in distorted.rounds]
    records=read_jsonl(distorted.distortion_log)
    assert len(records)==20
    assert any(q['selected'] for r in records for q in r['current_quotes'])
    events=read_jsonl(b/'events.jsonl')
    for obs in [r for r in records if r['round']==1 and r['role']=='seller']:
        prompt=next(e['prompt'] for e in events if e.get('agent')==obs['observer'] and e.get('round')==1)
        for quote in obs['current_quotes']:
            if quote['selected']:
                assert str(quote['displayed_price']) in prompt


def test_reference_plan_budget_and_shared_source_integrity():
    from research.endogenous_defection.distortion_v1.__main__ import DEFAULT_SOURCE, make_plan as pilot_plan
    plan=pilot_plan(DEFAULT_SOURCE,'synthetic')
    assert plan['decisions']==400 and plan['maximum_requests']==800
    assert len(plan['jobs'])==4 and len(plan['controls'])==8
    assert [j['cell'] for j in plan['jobs']]==['distort_on','distort_off','distort_off','distort_on']


def test_complete_synthetic_pilot_retains_source_and_labels_analysis(tmp_path):
    import json
    from research.endogenous_defection.io import dump, verify
    from research.endogenous_defection.distortion_v1.__main__ import DEFAULT_SOURCE, make_plan as pilot_plan, worker
    root=tmp_path/'pilot'; root.mkdir()
    plan=pilot_plan(DEFAULT_SOURCE,'synthetic')
    dump(root/'pilot_plan.json',plan)
    assert worker(root)==0
    for job in plan['jobs']:
        bundle=root/'cells'/job['id']
        verify(bundle)
        assert (bundle/'distortion_source/observation.py').exists()
        assert (bundle/'distortions.jsonl').exists()
    result=json.loads((root/'analysis/analysis.json').read_text())
    assert result['backend']=='synthetic' and result['contrasts']==[]
    assert 'SYNTHETIC VALIDATION ONLY' in (root/'analysis/RESULTS.md').read_text()
    assert len(result['outcomes'])==12


def test_active_host_guard_without_starting_any_compute(tmp_path,monkeypatch):
    import pytest
    from research.endogenous_defection.io import dump
    from research.endogenous_defection.distortion_v1 import __main__ as driver
    monkeypatch.setattr(driver,'ROOT',tmp_path)
    active=tmp_path/'output/information_study_active'; active.mkdir(parents=True)
    dump(active/'study_plan.json',{'backend':'live'})
    with pytest.raises(ValueError,match='active or shutdown'):
        driver.guard_idle()
    dump(active/'host_exit.json',{'exit_code':0})
    driver.guard_idle()
