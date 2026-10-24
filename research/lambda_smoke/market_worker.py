"""One two-round 5x5 auction; Lambda infrastructure validation only."""
import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['live', 'synthetic'], default='live')
    parser.add_argument('--out', type=Path, default=Path('/results/market'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ['LLM_BASE_URL'] = 'http://127.0.0.1:8000/v1'
    os.environ['LLM_API_KEY'] = 'lambda-loopback-only'
    os.environ['LLM_MODEL'] = 'Qwen/Qwen2.5-7B-Instruct'
    from research.endogenous_defection.information_study import make_plan
    from research.endogenous_defection.config import Protocol
    from research.endogenous_defection.response_schema import schema_for
    from research.endogenous_defection.io import dump, verify
    from research.endogenous_defection.run_experiment import run
    from research.endogenous_defection.auction import make_market
    from research.endogenous_defection.observations import ObservationMarket
    job = make_plan([90], args.backend, rounds=2)['jobs'][0]
    protocol = Protocol.model_validate(job['config'])
    dump(args.out / 'smoke_design.json', dict(provider='lambda', research_results=False,
         decisions=20, maximum_market_requests=40, maximum_warmup_requests=2,
         seed=90, rounds=2, cell='full_on'))
    if args.backend == 'live':
        from runtime_metadata import collect_serving_runtime, validate_serving_runtime, RUNTIME_HEADER
        import time
        deadline = time.monotonic() + 900
        while True:
            try:
                response = urllib.request.urlopen(os.environ['LLM_BASE_URL'] + '/models', timeout=10)
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Model readiness exceeded 900 seconds')
                time.sleep(5)
                continue
            with response:
                runtime = validate_serving_runtime(json.loads(response.headers[RUNTIME_HEADER]))
                models = json.load(response)
                assert os.environ['LLM_MODEL'] in [m['id'] for m in models['data']]
            break
        os.environ['MODAL_SERVING_RUNTIME'] = json.dumps(runtime)  # legacy metadata field, provider labelled above
        dump(args.out / 'runtime.json', collect_serving_runtime())
        dump(args.out / 'gpu.json', dict(nvidia_smi=subprocess.check_output(['nvidia-smi', '-q'], text=True)))
        # Compile both exact market schemas before the unchanged 90-second market timeout.
        # These are explicit fixture requests, excluded from market outcomes.
        for role in ('seller', 'buyer'):
            payload = dict(model=os.environ['LLM_MODEL'], messages=[dict(role='user', content='Return a brief valid JSON action. Use empty strings for text fields.')],
                           guided_json=schema_for(role, protocol), max_tokens=128, temperature=0.7, seed=90)
            dump(args.out / (role + '_warmup_request.json'), payload)
            print('Compiling/warming ' + role + ' schema (maximum 900 seconds)...', flush=True)
            request = urllib.request.Request(os.environ['LLM_BASE_URL'] + '/chat/completions', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=900) as response:
                (args.out / (role + '_warmup_response.json')).write_bytes(response.read())
    config = args.out / 'config.json'
    dump(config, job['config'])
    bundle = args.out / 'bundle'
    def factory(protocol, session, seed, condition='warmup', state=None):
        market = make_market(protocol, session, seed, condition, state, market_class=ObservationMarket)
        market.visibility_mode = 'full'
        market.observation_seed = seed
        market.observation_path = bundle / 'observations.jsonl'
        return market
    print('Running real auction: 5 sellers, 5 buyers, 2 rounds, at most 40 market requests.', flush=True)
    code = run(argparse.Namespace(config=config, stage='control', backend=args.backend,
        model=os.environ['LLM_MODEL'] if args.backend == 'live' else None,
        out=bundle, from_control=None, max_calls=40), market_factory=factory)
    verify(bundle)
    print('MARKET_SMOKE_EXIT ' + str(code) + '; infrastructure validation only', flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
