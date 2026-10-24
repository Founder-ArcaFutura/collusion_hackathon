"""Export the bounded four-market distortion pilot for an existing Lambda VM."""
import hashlib
import json
import shutil
from pathlib import Path

from research.lambda_smoke.prepare_market import prepare, HERE, ROOT


def main():
    target = prepare()
    renamed = target.with_name(target.name.replace('lambda_market_', 'lambda_distortion_'))
    target.rename(renamed)
    target = renamed
    source = ROOT / 'output/information_study_20261024_095806_35d3842f'
    from research.endogenous_defection.distortion_v1.__main__ import make_plan
    make_plan(source, 'live')  # verify original seals and shared scientific source before export
    shutil.copytree(source, target / 'app/output' / source.name)
    worker = (HERE / 'market_worker.py').read_text(encoding='utf-8')
    worker = worker.replace("job = make_plan([90], args.backend, rounds=2)['jobs'][0]", "job = make_plan([20], args.backend, rounds=10)['jobs'][0]")
    worker = worker.replace("decisions=20, maximum_market_requests=40, maximum_warmup_requests=2,\n         seed=90, rounds=2, cell='full_on'", "decisions=400, maximum_market_requests=800, maximum_warmup_requests=3,\n         seeds=[20,21], rounds=10, comparison='Historical Modal controls; provider/GPU confounding remains'")
    worker = worker.replace("for role in ('seller', 'buyer'):", "for label, role, comms in (('seller_on','seller',True),('buyer_off','buyer',False),('seller_off','seller',False)):\n            protocol.seller_comms_enabled = comms")
    worker = worker.replace("(role + '_warmup_", "(label + '_warmup_")
    worker = worker[:worker.index("    config = args.out / 'config.json'")] + '''    from research.endogenous_defection.distortion_v1.__main__ import DEFAULT_SOURCE, make_plan as pilot_plan, worker as pilot_worker
    plan = pilot_plan(DEFAULT_SOURCE, args.backend)
    dump(args.out / 'pilot_plan.json', plan)
    print('LAMBDA DISTORTION PILOT: 400 decisions, at most 800 market requests plus 3 warmups.', flush=True)
    return pilot_worker(args.out)


if __name__ == '__main__':
    raise SystemExit(main())
'''
    (target / 'market_worker.py').write_text(worker, encoding='utf-8', newline='\n')
    script = (target / 'run.sh').read_text().replace('collusion-lambda-market', 'collusion-lambda-distortion').replace('collusion-market-', 'collusion-distortion-').replace('3600 python market_worker.py --out /results/market', '10800 python market_worker.py --out /results/pilot')
    script = script.replace('Smoke passed. Evidence:', 'Pilot completed. Evidence:')
    (target / 'run.sh').write_text(script, encoding='utf-8', newline='\n')
    hashes = {str(p.relative_to(target)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file() and p.name != 'source_sha256.json'}
    (target / 'source_sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    archive = shutil.make_archive(str(target), 'gztar', root_dir=target.parent, base_dir=target.name)
    print('DISTORTION_ARCHIVE ' + archive)
    return target


if __name__ == '__main__':
    main()
