import json
from types import SimpleNamespace

import pytest

from research.endogenous_defection.auction import AdapterClient, Session
from research.endogenous_defection.config import Protocol
from research.endogenous_defection.io import read_jsonl


VALID = json.dumps(dict(ask=83.32, reflection='r', plan_for_this_hour='p',
                        new_memory='m', scratch_pad_update='s'))


def setup_session(tmp_path, outputs, cap=2):
    protocol = Protocol(max_action_attempts=2, seller_comms_enabled=False)
    session = Session(protocol, 'model', 'synthetic', cap, tmp_path / 'events.jsonl')
    session.backend = 'live'
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        raw, finish = outputs[len(requests) - 1]
        if finish == 'provider_error':
            raise TimeoutError('PRIVATE HEADER')
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=raw), finish_reason=finish)],
            model='model', usage=None)

    session.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return session, AdapterClient(session, 10, 'Seller Theo', 1, 'seller', 'warmup'), requests


@pytest.mark.parametrize('raw,finish', [('truncated', 'length'), ('{"ask":1,}', 'stop')])
def test_only_format_failures_get_one_recorded_regeneration(tmp_path, raw, finish):
    session, adapter, requests = setup_session(tmp_path, [(raw, finish), (VALID, 'stop')])
    messages = [{'role': 'user', 'content': 'UNCHANGED PROMPT'}]
    assert json.loads(adapter.generate(messages))['ask'] == 83.32
    assert len(requests) == session.calls == 2
    assert requests[0]['messages'] == requests[1]['messages'] == messages
    assert 'seed' not in requests[0] and isinstance(requests[1]['seed'], int)
    events = read_jsonl(session.event_path)
    assert [e['raw'] for e in events if e['event'] == 'response'] == [raw, VALID]
    assert len([e for e in events if e['event'] == 'format_recovery_scheduled']) == 1
    assert events[-1]['event'] == 'action_accepted' and events[-1]['generation_attempt'] == 2


@pytest.mark.parametrize('outputs,cap,expected_calls', [
    ([('bad', 'length'), ('bad again', 'length')], 2, 2),
    ([('bad', 'length')], 1, 1),
    ([('bad', 'provider_error')], 2, 1),
    ([(VALID.replace('83.32', '-1'), 'stop')], 2, 1),
])
def test_no_unbounded_retry_no_provider_retry_no_semantic_repair(tmp_path, outputs, cap, expected_calls):
    session, adapter, requests = setup_session(tmp_path, outputs, cap)
    with pytest.raises(RuntimeError):
        adapter.generate([{'role': 'user', 'content': 'prompt'}])
    assert session.calls == len(requests) == expected_calls
    assert 'PRIVATE HEADER' not in session.event_path.read_text()
    assert not any(e['event'] == 'action_accepted' for e in read_jsonl(session.event_path))


def test_new_control_budget_counts_worst_case_requests():
    from research.endogenous_defection.config import load_protocol
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    old = load_protocol(root / 'configs/factorial_3x5_comms_off_v1.json')
    new = load_protocol(root / 'configs/factorial_3x5_comms_off_v5_format_recovery.json')
    assert old.call_estimate()['control'] == 160
    assert new.call_estimate()['control'] == 320
    assert old.model_dump(exclude={'max_action_attempts', 'protocol_version'}) == new.model_dump(
        exclude={'max_action_attempts', 'protocol_version'})


def test_recovered_generation_flows_through_real_round_and_analysis(tmp_path):
    from pathlib import Path
    from research.endogenous_defection.auction import make_market, run_rounds
    from research.endogenous_defection.config import load_protocol
    root = Path(__file__).resolve().parents[1]
    protocol = load_protocol(root / 'configs/factorial_3x5_comms_off_v5_format_recovery.json')
    session = Session(protocol, protocol.model_id, 'synthetic', 320, tmp_path / 'events.jsonl')
    session.backend = 'live'
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        key = 'ask' if 'ask' in kwargs['extra_body']['guided_json']['properties'] else 'bid'
        raw = json.dumps(dict(reflection='r', plan_for_this_hour='p', new_memory='m',
                              scratch_pad_update='s', **{key: 85.0}))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw),
            finish_reason='length' if len(requests) == 1 else 'stop')],
            model=protocol.model_id, usage=None)

    session.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    market = make_market(protocol, session, 10)
    rows = run_rounds(market, 1, protocol, tmp_path / 'rounds.jsonl', 'warmup', market.sellers[0].id)
    assert session.calls == len(requests) == 9  # Eight decisions, one rejected generation.
    assert len(rows) == 1 and rows[0]['metrics']['round'] == 1
    assert rows[0]['market']['seller_asks'] == {seller.id: 85.0 for seller in market.sellers}
    assert len([e for e in read_jsonl(session.event_path) if e['event'] == 'action_accepted']) == 8
    assert requests[0]['messages'] == requests[1]['messages']
