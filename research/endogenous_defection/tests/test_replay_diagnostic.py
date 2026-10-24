import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.endogenous_defection import replay_diagnostic as replay
from research.endogenous_defection.auction import Session
from research.endogenous_defection.io import dump, read_jsonl, seal, verify


@pytest.fixture
def source(tmp_path):
    source = tmp_path / 'sealed_source'
    source.mkdir()
    protocol = json.loads((replay.DEFAULT_SOURCE / 'protocol.json').read_text())
    dump(source / 'protocol.json', protocol)
    dump(source / 'bundle.json', {'backend': 'live', 'status': 'failed',
                                 'model': protocol['model_id'], 'modal_serving_runtime': RUNTIME})
    snapshot = source / 'source_snapshot/research/endogenous_defection'
    snapshot.mkdir(parents=True)
    for name in ('auction.py', 'response_schema.py'):
        (snapshot / name).write_bytes((replay.HERE / name).read_bytes())
    events = [
        dict(event='response', call=1, agent='Buyer Ana', seed=10, round=1,
             finish_reason='stop', prompt='Exact buyer prompt\nwith original whitespace.  '),
        dict(event='response', call=7, agent='Seller Theo', seed=10, round=1,
             finish_reason='length', prompt='Exact seller prompt\nincluding its original scratchpad.'),
        dict(event='response_validation_failed', call=7, agent='Seller Theo',
             seed=10, round=1, finish_reason='length'),
    ]
    (source / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
    seal(source)
    return source


RUNTIME = dict(vllm='0.6.6', outlines='0.1.11', xgrammar='0.1.13',
               guided_decoding_backend='outlines', required_api_available=True,
               required_api='vllm guided_json via outlines backend')


def fake_session(monkeypatch, failures=None, returned_model=None):
    calls = []
    failures = failures or {}

    def create(**kwargs):
        calls.append(kwargs)
        outcome = failures.get(len(calls))
        if outcome == 'timeout':
            raise TimeoutError('SECRET provider exception must not be recorded')
        role = 'ask' if 'seller prompt' in kwargs['messages'][0]['content'] else 'bid'
        raw = json.dumps(dict(reflection='observations', plan_for_this_hour='plan',
                              new_memory='memory', scratch_pad_update='scratchpad', **{role: 83.32}))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw),
                                     finish_reason='length' if outcome == 'length' else 'stop')],
            model=returned_model or kwargs['model'], system_fingerprint=None,
            usage=SimpleNamespace(model_dump=lambda: dict(prompt_tokens=30, completion_tokens=50)))

    def factory(protocol, model, backend, max_calls, event_path):
        assert backend == 'live' and max_calls == 4
        session = Session(protocol, model, 'synthetic', max_calls, event_path)
        session.backend, session.route = 'live', 'modal-hosted'
        session.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        return session

    monkeypatch.setattr(replay, 'Session', factory)
    monkeypatch.setattr(replay, 'serving_runtime_metadata', lambda: RUNTIME)
    return calls


def test_plan_no_inference_preserves_prompts_and_only_varies_guidance(source, tmp_path, monkeypatch):
    monkeypatch.setattr(replay, 'Session', lambda *a, **k: pytest.fail('plan started inference'))
    out = tmp_path / 'new_output'
    _, plan = replay.prepare(source, out)
    assert not out.exists()
    assert plan['request_ceiling'] == 4 and plan['maximum_completion_tokens'] == 8192
    assert [c['case'] for c in plan['cases']] == [
        'seller_guided', 'buyer_guided', 'seller_unguided', 'buyer_unguided']
    assert plan['cases'][0]['prompt'] == plan['cases'][2]['prompt']
    assert plan['cases'][1]['prompt'].endswith('  ')
    assert plan['cases'][1]['prompt_sha256'] == plan['cases'][3]['prompt_sha256']


def test_rejections_are_recorded_without_retries_or_aborting_fixed_contrasts(source, tmp_path, monkeypatch):
    calls = fake_session(monkeypatch, {1: 'length', 2: 'timeout'})
    out = tmp_path / 'probe'
    assert replay.execute(source, out) == 2
    assert len(calls) == 4
    for index in (0, 1):
        assert 'guided_json' in calls[index]['extra_body']
        unguided = dict(calls[index + 2])
        guided = dict(calls[index])
        guided.pop('extra_body')
        assert guided == unguided
    summary = json.loads((out / 'diagnostic_summary.json').read_text())
    assert summary['status'] == 'transport_failure'
    assert summary['cases'][0]['error_category'] == 'incomplete_generation'
    assert summary['cases'][0]['finish_reason'] == 'length'
    assert summary['cases'][1]['error_type'] == 'TimeoutError'
    assert summary['cases'][2]['accepted'] and summary['cases'][3]['accepted']
    assert summary['market_rounds'] == 0 and not summary['scientific_run']
    assert summary['requests'] == 4
    assert 'SECRET' not in (out / 'events.jsonl').read_text()
    assert len([e for e in read_jsonl(out / 'events.jsonl') if e['event'] == 'request_started']) == 4
    verify(out)
    verify(source)


def test_success_is_diagnostic_only_and_model_substitution_fails(source, tmp_path, monkeypatch):
    fake_session(monkeypatch)
    assert replay.execute(source, tmp_path / 'success') == 0
    fake_session(monkeypatch, returned_model='another-model')
    out = tmp_path / 'wrong_model'
    assert replay.execute(source, out) == 2
    assert all(c['error_category'] == 'model_identity_mismatch'
               for c in json.loads((out / 'diagnostic_summary.json').read_text())['cases'])


def test_tampering_existing_output_and_missing_runtime_block_before_requests(source, tmp_path, monkeypatch):
    calls = fake_session(monkeypatch)
    with pytest.raises(FileExistsError):
        replay.prepare(source, source)
    with pytest.raises(ValueError, match='outside'):
        replay.prepare(source, source / 'nested')
    monkeypatch.setattr(replay, 'serving_runtime_metadata', lambda: None)
    with pytest.raises(ValueError, match='runtime metadata'):
        replay.execute(source, tmp_path / 'missing_runtime')
    assert not (tmp_path / 'missing_runtime').exists()
    (source / 'protocol.json').write_text('{}')
    with pytest.raises(ValueError, match='checksums'):
        replay.prepare(source, tmp_path / 'tampered')
    assert calls == []


def test_changed_schema_snapshot_and_runtime_block_before_requests(source, tmp_path, monkeypatch):
    calls = fake_session(monkeypatch)
    monkeypatch.setattr(replay, 'serving_runtime_metadata', lambda: {**RUNTIME, 'xgrammar': 'other'})
    with pytest.raises(ValueError, match='Serving runtime differs'):
        replay.execute(source, tmp_path / 'runtime_drift')
    assert not (tmp_path / 'runtime_drift').exists()
    (source / 'source_snapshot/research/endogenous_defection/response_schema.py').write_text('# changed')
    seal(source)
    with pytest.raises(ValueError, match='response_schema.py differs'):
        replay.prepare(source, tmp_path / 'schema_drift')
    assert calls == []
