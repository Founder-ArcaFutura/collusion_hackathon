"""Create truthful controls from the frozen Lambda distortion export."""
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime
import uuid

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / 'output/lambda_distortion_20261024_143550_92dad9b2'


def main():
    target = ROOT / 'output' / ('lambda_truthful_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    hashes = json.loads((FROZEN / 'source_sha256.json').read_text())
    for name, digest in hashes.items():
        assert hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() == digest, name
    for name in ('app',):
        shutil.copytree(FROZEN / name, target / name)
    for name in ('Dockerfile', 'runtime_metadata.py', 'response_schema.py'):
        shutil.copyfile(FROZEN / name, target / name)
    worker = (FROZEN / 'market_worker.py').read_text()
    marker = "    from research.endogenous_defection.distortion_v1.__main__ import DEFAULT_SOURCE, make_plan as pilot_plan, worker as pilot_worker"
    worker = worker[:worker.index(marker)] + '''    from research.endogenous_defection.distortion_v1.__main__ import DEFAULT_SOURCE, make_plan as pilot_plan
    from research.endogenous_defection.study_analysis import csv_file
    from statistics import mean
    plan = pilot_plan(DEFAULT_SOURCE, args.backend)
    dump(args.out / 'control_plan.json', dict(version='lambda-truthful-controls-v1', seeds=[20,21],
        rounds=10, maximum_market_requests=800, maximum_warmup_requests=3,
        source='Frozen distortion export', comparison='New Lambda instance; GPU and dependency differences must be checked'))
    outcomes = []
    for job in plan['jobs']:
        cell = job['cell'].replace('distort_', 'full_')
        config_data = dict(job['config'])
        config_data['protocol_version'] = 'lambda-truthful-controls-v1-' + cell
        config = args.out / (str(job['seed']) + '_' + cell + '_config.json')
        dump(config, config_data)
        bundle = args.out / ('seed_' + str(job['seed']) + '_' + cell)
        def factory(protocol, session, seed, condition='warmup', state=None):
            market = make_market(protocol, session, seed, condition, state, market_class=ObservationMarket)
            market.visibility_mode = 'full'
            market.observation_seed = seed
            market.observation_path = bundle / 'observations.jsonl'
            return market
        print('LAMBDA_TRUTHFUL_CELL ' + bundle.name, flush=True)
        code = run(argparse.Namespace(config=config, stage='control', backend=args.backend,
            model=plan['model'] if args.backend == 'live' else None,
            out=bundle, from_control=None, max_calls=job['maximum_requests']), market_factory=factory)
        verify(bundle)
        rows = [json.loads(line) for line in (bundle / ('seed_' + str(job['seed'])) / 'warmup.jsonl').read_text().splitlines()] if (bundle / ('seed_' + str(job['seed'])) / 'warmup.jsonl').exists() else []
        trades = [t for r in rows for t in r['market']['trades']]
        outcomes.append(dict(seed=job['seed'], cell=cell, status='complete' if code == 0 else 'failed',
            rounds=len(rows), trades=len(trades), mean_trade_price=mean(t['price'] for t in trades) if trades else None,
            mean_ask=mean(r['metrics']['mean_ask'] for r in rows) if rows else None))
        csv_file(args.out / 'market_outcomes.csv', outcomes)
        if code != 0:
            dump(args.out / 'control_status.json', dict(status='stopped_technical_failure'))
            return code
    dump(args.out / 'control_status.json', dict(status='complete'))
    print('TRUTHFUL_CONTROLS_COMPLETE ' + str(args.out), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
'''
    worker = worker.replace("comparison='Historical Modal controls; provider/GPU confounding remains'", "comparison='Truthful Lambda controls for frozen distortion pilot'")
    (target / 'market_worker.py').write_text(worker, encoding='utf-8', newline='\n')
    script = (FROZEN / 'run.sh').read_text().replace('collusion-lambda-distortion', 'collusion-lambda-truthful').replace('collusion-distortion-', 'collusion-truthful-').replace('/results/pilot', '/results/controls')
    (target / 'run.sh').write_text(script, encoding='utf-8', newline='\n')
    manifest = {str(p.relative_to(target)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
    (target / 'source_sha256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive = shutil.make_archive(str(target), 'gztar', root_dir=target.parent, base_dir=target.name)
    print('TRUTHFUL_ARCHIVE ' + archive)
    return target


if __name__ == '__main__':
    main()
