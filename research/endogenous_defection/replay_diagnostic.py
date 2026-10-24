"""Four fixed requests using sealed seller/buyer prompts; never runs a market."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from .auction import AdapterClient, Session
from .config import load_protocol
from .io import append, dump, provenance, read_jsonl, seal, serving_runtime_metadata, sha256, utc_now, verify
from .response_schema import SCHEMA_VERSION, schema_for

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / 'results/factorial_3x5_comms_off_v4_guided_2048'
REQUEST_CEILING = 4


def prepare(source, out):
    source, out = Path(source).resolve(), Path(out).resolve()
    if out.exists():
        raise FileExistsError(f'Output already exists: {out}')
    if source == out or source in out.parents:
        raise ValueError('Diagnostic output must be outside the sealed source bundle')
    verify(source)
    for filename in ('auction.py', 'response_schema.py'):
        original = source / 'source_snapshot/research/endogenous_defection' / filename
        if not original.is_file() or sha256(original) != sha256(HERE / filename):
            raise ValueError(f'{filename} differs from the sealed serving/validation contract')
    meta = json.loads((source / 'bundle.json').read_text(encoding='utf-8'))
    protocol = load_protocol(source / 'protocol.json')
    if (meta['backend'] != 'live' or meta['status'] != 'failed'
            or meta['model'] != protocol.model_id or not protocol.execution_enabled
            or protocol.response_schema_version != SCHEMA_VERSION
            or protocol.max_tokens != 2048 or protocol.provider_seed):
        raise ValueError('Expected a failed live guided-v1, 2048-token, unseeded source')
    events = read_jsonl(source / 'events.jsonl')
    failures = [e for e in events if e['event'] == 'response_validation_failed'
                and e.get('finish_reason') == 'length' and e['agent'].startswith('Seller ')]
    if len(failures) != 1:
        raise ValueError('Expected exactly one truncated seller response')
    failure = failures[0]
    responses = [e for e in events if e['event'] == 'response']
    seller = next(e for e in responses if e['call'] == failure['call'])
    buyer = next(e for e in responses if e['agent'].startswith('Buyer ')
                 and e['seed'] == seller['seed'] and e['round'] == seller['round']
                 and e['finish_reason'] == 'stop')
    cases = []
    # Fixed contrasts, not retries or a search for a successful response. All four
    # are attempted even when the first response is rejected by the validator.
    for mode in ('guided', 'unguided'):
        for role, event in (('seller', seller), ('buyer', buyer)):
            cases.append(dict(case=f'{role}_{mode}', role=role, mode=mode,
                              agent=event['agent'], seed=event['seed'], round=event['round'],
                              source_call=event['call'], prompt=event['prompt'],
                              prompt_sha256=hashlib.sha256(event['prompt'].encode()).hexdigest()))
    plan = dict(diagnostic_version='failed-prompt-replay-v1', source=str(source),
                source_checksums_sha256=sha256(source / 'checksums.json'),
                source_protocol_sha256=sha256(source / 'protocol.json'),
                source_serving_runtime=meta['modal_serving_runtime'],
                model=protocol.model_id, temperature=protocol.temperature,
                max_tokens=protocol.max_tokens, provider_seed=protocol.provider_seed,
                request_ceiling=REQUEST_CEILING, maximum_completion_tokens=8192,
                request_timeout_seconds=90, sdk_retries=0, scientific_run=False,
                cases=cases, output=str(out))
    return protocol, plan


def execute(source, out):
    protocol, plan = prepare(source, out)
    runtime = serving_runtime_metadata()
    if runtime is None:
        raise ValueError('Use the Modal host launcher; serving runtime metadata is required')
    from poseidon_compute.runtime_metadata import validate_serving_runtime
    validate_serving_runtime(runtime)
    for key in ('vllm', 'outlines', 'xgrammar', 'guided_decoding_backend'):
        if runtime.get(key) != plan['source_serving_runtime'].get(key):
            raise ValueError('Serving runtime differs from the sealed source; no requests sent')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    session = None
    results = []
    fatal_error = None
    summary = {}
    try:
        dump(out / 'plan.json', plan)
        dump(out / 'source_protocol.json', protocol.model_dump(mode='json'))
        dump(out / 'provenance.json', provenance())
        # Preserve the exact diagnostic implementation as well as its hash.
        (out / 'replay_diagnostic.py').write_bytes(Path(__file__).read_bytes())
        session = Session(protocol, plan['model'], 'live', REQUEST_CEILING, out / 'events.jsonl')
        if session.route != 'modal-hosted':
            raise ValueError('Diagnostic requires the Modal route; refusing provider substitution')
        for index, case in enumerate(plan['cases']):
            guided = case['mode'] == 'guided'
            session.protocol = protocol.model_copy(update={
                'response_schema_version': SCHEMA_VERSION if guided else 'unconstrained-v1'})
            request = dict(model=plan['model'], messages=[{'role': 'user', 'content': case['prompt']}],
                           temperature=protocol.temperature, max_tokens=protocol.max_tokens)
            if guided:
                request['extra_body'] = {'guided_json': schema_for(case['role'], protocol)}
            dump(out / f'{index + 1:02d}_{case["case"]}_request.json', request)
            adapter = AdapterClient(session, case['seed'], case['agent'], 0,
                                    case['role'], case['case'])
            adapter.round_num = case['round']
            before = session.calls
            previous_events = len(read_jsonl(out / 'events.jsonl')) if (out / 'events.jsonl').exists() else 0
            started = time.perf_counter()
            accepted, error_type = False, None
            try:
                adapter.generate(request['messages'])
                accepted = True
            except Exception as exc:
                # The shared Session records safe provider error metadata and raw
                # responses. Exception strings may contain secrets: do not print them.
                error_type = type(exc).__name__
            elapsed = time.perf_counter() - started
            events = read_jsonl(out / 'events.jsonl') if (out / 'events.jsonl').exists() else []
            call_events = events[previous_events:]
            response = next((e for e in call_events if e['event'] == 'response'), {})
            failed = next((e for e in call_events if e['event'] in
                           ('request_failed', 'response_validation_failed')), {})
            if response and response.get('returned_model') != plan['model']:
                accepted = False
                failed = {'error_category': 'model_identity_mismatch',
                          'validation_error': 'Returned model differs from the sealed source model'}
            row = dict(case=case['case'], role=case['role'], prompt_sha256=case['prompt_sha256'],
                       source_call=case['source_call'], call=session.calls,
                       request_attempted=session.calls == before + 1, accepted=accepted,
                       response_received=bool(response), elapsed_seconds=round(elapsed, 3),
                       finish_reason=response.get('finish_reason'), usage=response.get('usage'),
                       returned_model=response.get('returned_model'),
                       error_type=failed.get('error_type', error_type),
                       error_category=failed.get('error_category'),
                       validation_error=failed.get('validation_error'))
            results.append(row)
            append(out / 'case_results.jsonl', row)
            print('DIAGNOSTIC_CASE ' + json.dumps(row, sort_keys=True), flush=True)
    except BaseException as exc:
        fatal_error = type(exc).__name__
        raise
    finally:
        status = ('incomplete' if fatal_error or len(results) != REQUEST_CEILING else
                  'transport_failure' if any(not r['response_received'] for r in results) else
                  'completed_with_rejections' if any(not r['accepted'] for r in results) else
                  'all_responses_valid')
        summary = dict(status=status, fatal_error_type=fatal_error, cases=results,
                       requests=session.calls if session else 0, request_ceiling=REQUEST_CEILING,
                       serving_runtime=runtime, scientific_run=False, market_rounds=0,
                       gate_result='not_evaluated', finished_at=utc_now(),
                       interpretation='Diagnostic contrasts only; one sample per case cannot isolate causality')
        dump(out / 'diagnostic_summary.json', summary)
        seal(out)
        print('DIAGNOSTIC_SUMMARY ' + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary['status'] == 'all_responses_valid' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['plan', 'live'], default='plan')
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.stage == 'plan':
            _, plan = prepare(args.source, args.out)
            print(json.dumps(plan, indent=2))
            return 0
        return execute(args.source, args.out)
    except Exception as exc:
        # Preflight errors here only describe files/protocols; provider errors
        # inside execute are recorded with safe exception types, never secrets.
        print(f'Diagnostic stopped ({type(exc).__name__}); inspect the source bundle and diagnostic summary.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
