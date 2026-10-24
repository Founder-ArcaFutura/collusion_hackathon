"""Versioned information study continuation with a bounded scratchpad schema."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime
import uuid
import os
import urllib.request

from research.endogenous_defection import information_study as study
from research.endogenous_defection.config import Protocol
from research.endogenous_defection.io import dump, utc_now

original_plan = study.make_plan


def warm_schemas(plan, root, opener=urllib.request.urlopen):
    """Compile each distinct schema once; at most three non-market requests."""
    from research.endogenous_defection.response_schema import schema_for
    warmup = root / 'schema_warmup'
    warmup.mkdir(exist_ok=False)
    seen = set()
    for job in plan['jobs']:
        protocol = Protocol.model_validate(job['config'])
        for role in ('buyer', 'seller'):
            schema = schema_for(role, protocol)
            signature = json.dumps(schema, sort_keys=True)
            if signature in seen:
                continue
            if len(seen) >= 3:
                raise ValueError('Schema warmup exceeds three-request budget')
            seen.add(signature)
            label = str(len(seen)) + '_' + role
            payload = dict(model=plan['model'], messages=[dict(role='user', content='Return a brief valid JSON action. Use empty strings for text fields.')],
                guided_json=schema, max_tokens=128, temperature=0.7, seed=90)
            dump(warmup / (label + '_request.json'), payload)
            print('SCHEMA_WARMUP ' + label + ': maximum 900 seconds; excluded from market outcomes', flush=True)
            request = urllib.request.Request(os.environ['LLM_BASE_URL'].rstrip('/') + '/chat/completions',
                data=json.dumps(payload).encode(), headers={'Content-Type':'application/json',
                'Authorization':'Bearer ' + os.environ['LLM_API_KEY']})
            try:
                with opener(request, timeout=900) as response:
                    raw = response.read()
                (warmup / (label + '_response.json')).write_bytes(raw)
                result = json.loads(raw)
                if not result.get('choices'):
                    raise ValueError('Warmup returned no choices')
            except Exception as exc:
                dump(warmup / 'status.json', dict(status='failed', requests=len(seen), error_type=type(exc).__name__))
                raise
    dump(warmup / 'status.json', dict(status='complete', requests=len(seen), market_requests=False))


def make_plan(seeds, backend, rounds=10):
    plan = original_plan(seeds, backend, rounds)
    plan['version'] = 'information-communication-v2-bounded-scratchpad'
    plan['inference'] = 'Separate repaired protocol; do not pool silently with v1 markets'
    plan['market_request_timeout_seconds'] = 300
    plan['timing_policy'] = '300-second client timeout; no additional retries; three separate schema warmups'
    for job in plan['jobs']:
        job['config']['response_schema_version'] = 'agent-action-json-v3-bounded-scratchpad'
        job['config']['protocol_version'] += '-v2-bounded-scratchpad'
        Protocol.model_validate(job['config'])
    return plan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', choices=['plan', 'run', 'worker'], default='plan')
    p.add_argument('--backend', choices=['live', 'synthetic'], default='live')
    p.add_argument('--seeds', type=int, nargs='+', default=[24,25])
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    if args.stage == 'worker':
        study.make_plan = make_plan
        root = args.out.resolve()
        plan = json.loads((root / 'study_plan.json').read_text(encoding='utf-8'))
        from research.endogenous_defection import auction
        auction.INFERENCE_REQUEST_TIMEOUT_SECONDS = plan['market_request_timeout_seconds']
        if plan['backend'] == 'live':
            warm_schemas(plan, root)
        return study.worker(root)
    plan = make_plan(args.seeds, args.backend)
    print(json.dumps(plan, indent=2), flush=True)
    if args.stage == 'plan':
        return 0
    if args.backend == 'live':
        # Modal endpoint identity is shared with other Modal study launchers.
        from research.endogenous_defection.distortion_v1.__main__ import guard_idle
        guard_idle()
    root = (args.out or study.ROOT / 'output' / ('information_study_bounded_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])).resolve()
    root.mkdir(parents=True, exist_ok=False)
    dump(root / 'study_plan.json', plan)
    # This additional wrapper sits outside the shared provenance glob.
    (root / 'continuation_launcher.py').write_bytes(Path(__file__).read_bytes())
    dump(root / 'execution_budget.json', dict(maximum_market_requests=plan['maximum_requests'],
        maximum_schema_warmup_requests=3, maximum_total_requests=plan['maximum_requests']+3,
        market_request_timeout_seconds=plan['market_request_timeout_seconds'], schema_warmup_timeout_seconds=900))
    print('OUTPUT ' + str(root), flush=True)
    if args.backend == 'synthetic':
        return study.worker(root)
    command = [sys.executable, '-X', 'utf8', '-c', 'from poseidon_compute.hosted_model import main; main()',
        '--model', plan['model'], '--gpu', 'A10G', '--ready-timeout', '600', '--run-timeout', '14400', '--',
        sys.executable, '-X', 'utf8', '-m', 'research.lambda_smoke.modal_bounded', '--stage', 'worker', '--out', str(root)]
    with (root / 'host.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=study.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace')
        try:
            for line in process.stdout:
                log.write(line); log.flush(); print(line, end='', flush=True)
            code = process.wait()
        except BaseException:
            process.terminate(); process.wait(timeout=30)
            raise
    dump(root / 'host_exit.json', dict(exit_code=code, finished_at=utc_now()))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
