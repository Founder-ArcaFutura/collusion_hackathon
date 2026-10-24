import json
from pathlib import Path

import pytest

from research.endogenous_defection.auction import Session, make_market, run_rounds, snapshot
from research.endogenous_defection.config import Protocol
from research.endogenous_defection.information_study import make_plan, worker
from research.endogenous_defection.io import dump, read_jsonl, verify
from research.endogenous_defection.observations import DISCLOSURE, ObservationMarket, mask_visible
from research.endogenous_defection.study_analysis import analyze_study
from src.continuous_double_auction.cda_types import MarketRound


def market_fixture(tmp_path, mode='partial', comms=True):
    config=make_plan([20], 'synthetic')['jobs'][0]['config']
    config['seller_comms_enabled']=comms
    protocol=Protocol.model_validate(config)
    session=Session(protocol,None,'synthetic',200,tmp_path/'events.jsonl')
    market=make_market(protocol,session,20,market_class=ObservationMarket)
    market.visibility_mode=mode
    market.observation_seed=20
    market.observation_path=tmp_path/'observations.jsonl'
    return protocol,session,market


def common(market, number=1):
    return dict(round_num=number,bid_queue=list(market.buyer_bid_queue),
        ask_queue=list(market.seller_ask_queue),past_bids_and_asks=market.formatted_past_bids_and_asks,
        past_trades=market.formatted_past_trades)


def test_stable_matched_mask_and_own_quotes_always_visible():
    draws=[mask_visible(s,'Seller A','Seller B',r) for s in range(100) for r in range(10)]
    assert 400<sum(draws)<600
    assert draws==[mask_visible(s,'Seller A','Seller B',r) for s in range(100) for r in range(10)]
    assert all(mask_visible(20,'Seller A','Seller A',r) for r in range(10))


def test_partial_filters_current_and_historical_quotes_without_changing_truth(tmp_path):
    _,_,market=market_fixture(tmp_path)
    asks={s.id:96.11+i*.13 for i,s in enumerate(market.sellers)}
    market.seller_ask_queue=[(v,k) for k,v in asks.items()]
    market.rounds=[MarketRound(round_number=1,seller_asks=asks,buyer_bids={b.id:83.0 for b in market.buyers})]
    observer=market.sellers[0]
    before=snapshot(market)
    original=common(market,2)
    view=market.observation_for(observer,original)
    hidden=[owner for owner in asks if not market.visible(observer.id,owner,1)]
    assert hidden  # Fixed fixture must actually remove information.
    for owner in hidden:
        assert owner not in [k for _,k in view['ask_queue']]
        assert f'{owner} ask $' not in view['past_bids_and_asks']
    assert observer.id in [owner for _,owner in view['ask_queue']]
    assert f'{observer.id} ask $' in view['past_bids_and_asks']
    assert view['past_trades']==original['past_trades']
    assert view['bid_queue']==original['bid_queue']
    assert snapshot(market)==before
    assert original['ask_queue']==market.seller_ask_queue
    assert market.observation_for(market.buyers[0],original)==original
    assert observer.memory_manager.memories=={} and observer.scratch_pad==''


def test_masks_match_across_comms_and_do_not_depend_on_queue_order(tmp_path):
    a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir()
    _,_,on=market_fixture(a,comms=True)
    _,_,off=market_fixture(b,comms=False)
    view_on=on.observation_for(on.sellers[0],common(on))
    raw=common(off); raw['ask_queue'].reverse()
    view_off=off.observation_for(off.sellers[0],raw)
    assert set(map(tuple,view_on['ask_queue']))==set(map(tuple,view_off['ask_queue']))
    on_masks=read_jsonl(a/'observations.jsonl')[0]['current_quote_masks']
    off_masks=read_jsonl(b/'observations.jsonl')[0]['current_quote_masks']
    assert {m['owner']:m['visible'] for m in on_masks}=={m['owner']:m['visible'] for m in off_masks}


@pytest.mark.parametrize('mode',['full','partial','shuffled'])
def test_actual_round_uses_observation_hook_and_keeps_synthetic_clearing_identical(tmp_path,mode):
    first=tmp_path/'base'; second=tmp_path/'study'; first.mkdir(); second.mkdir()
    p,s,study=market_fixture(second,mode)
    base_session=Session(p,None,'synthetic',200,first/'events.jsonl')
    baseline=make_market(p,base_session,20)
    run_rounds(baseline,2,p,first/'rounds.jsonl','warmup',baseline.sellers[0].id)
    run_rounds(study,2,p,second/'rounds.jsonl','warmup',study.sellers[0].id)
    assert [r.model_dump() for r in baseline.rounds]==[r.model_dump() for r in study.rounds]
    observations=read_jsonl(second/'observations.jsonl')
    assert len(observations)==20
    if mode=='partial':
        assert any(not m['visible'] for r in observations for m in r['current_quote_masks'])
        events=read_jsonl(second/'events.jsonl')
        for obs in [r for r in observations if r['role']=='seller' and r['round']==1]:
            prompt=next(e['prompt'] for e in events if e.get('agent')==obs['observer'] and e.get('round')==1)
            assert obs['observer'] in prompt
            for hidden in [m for m in obs['current_quote_masks'] if not m['visible']]:
                assert hidden['owner'] not in prompt
    if mode=='shuffled':
        assert all(set(map(tuple,r['true_observation']['ask_queue']))==
                   set(map(tuple,r['rendered_observation']['ask_queue'])) for r in observations)
    if mode=='full':
        assert all(r['true_observation']['ask_queue']==r['rendered_observation']['ask_queue'] for r in observations)
    for obs in observations:
        if obs['role']=='buyer':
            assert obs['true_observation']==obs['rendered_observation']
        else:
            assert DISCLOSURE in obs['rendered_observation']['past_bids_and_asks']


def test_plan_budget_and_complete_synthetic_factorial_with_automatic_analysis(tmp_path):
    plan=make_plan([20,21],'synthetic',rounds=2)
    assert plan['decisions']==160 and plan['maximum_requests']==320
    assert make_plan([20,21],'live')['maximum_requests']==1600
    assert [j['cell'] for j in plan['jobs'][:4]]==list(reversed([j['cell'] for j in plan['jobs'][4:]]))
    root=tmp_path/'batch'; root.mkdir()
    dump(root/'study_plan.json',plan)
    assert worker(root)==0
    result=json.loads((root/'analysis/analysis.json').read_text())
    assert result['synthetic'] and len(result['outcomes'])==8
    assert all(r['completed_rounds']==2 and r['status']=='complete' for r in result['outcomes'])
    assert all(r['requests']==0 for r in result['outcomes'])
    assert len(result['paired_contrasts'])==12
    assert 'SYNTHETIC VALIDATION ONLY' in (root/'analysis/RESULTS.md').read_text()
    for job in plan['jobs']:
        verify(root/'cells'/job['id'])
    assert (root/'analysis/observation_checks.csv').is_file()
    assert (root/'analysis/messages_for_coding.csv').is_file()
    assert read_jsonl(root/'cells'/plan['jobs'][0]['id']/'observations.jsonl')


def test_analysis_retains_unattempted_cells_and_refuses_live_partial_bundle(tmp_path):
    root=tmp_path/'batch'; root.mkdir()
    plan=make_plan([20],'synthetic',rounds=2)
    dump(root/'study_plan.json',plan)
    result=analyze_study(root,tmp_path/'no_cells')
    assert all(r['status']=='not_attempted' and r['trades'] is None for r in result['outcomes'])
    cell=root/'cells'/plan['jobs'][0]['id']; cell.mkdir(parents=True)
    dump(cell/'bundle.json',{'status':'running'})
    with pytest.raises(ValueError,match='not sealed'):
        analyze_study(root,tmp_path/'must_not_exist')
    assert not (tmp_path/'must_not_exist').exists()
