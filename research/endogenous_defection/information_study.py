"""Plan/run the 2x2 information × communication screen, with automatic analysis."""
import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from .auction import make_market
from .config import Protocol
from .io import dump, provenance, serving_runtime_metadata, sha256, utc_now
from .observations import ObservationMarket
from .run_experiment import run
from .study_analysis import analyze_study

ROOT=Path(__file__).resolve().parents[2]
BASE=Path(__file__).resolve().parent/'designs/information_controls_v1/full_off_REVIEW_ONLY.json'


def make_plan(seeds, backend, rounds=10):
    if not seeds or len(set(seeds))!=len(seeds) or any(s<20 or s>99 for s in seeds):
        raise ValueError('Use unique exploratory seeds 20–99; 10/11 and confirmation seeds are reserved')
    base=json.loads(BASE.read_text(encoding='utf-8'))
    jobs=[]
    order=['full_on','partial_off','full_off','partial_on']
    for index,seed in enumerate(seeds):
        sequence=order if index%2==0 else list(reversed(order))
        for cell in sequence:
            visibility,comms=cell.split('_')
            config=dict(base)
            config.update(execution_enabled=True,seeds=[seed],warmup_rounds=rounds,
                announced_rounds=rounds,window=min(5,rounds),min_qualifying_seeds=1,
                seller_comms_enabled=comms=='on',protocol_version='information-v1-'+cell)
            protocol=Protocol.model_validate(config)
            jobs.append(dict(id=f'seed_{seed}_{cell}',seed=seed,cell=cell,visibility=visibility,
                             config=config,maximum_requests=protocol.call_estimate()['control']))
    return dict(version='information-communication-v1',backend=backend,seeds=seeds,rounds=rounds,jobs=jobs,
                model=base['model_id'],decisions=len(seeds)*4*rounds*10,
                maximum_requests=sum(j['maximum_requests'] for j in jobs),
                mask='sha256(observer,quote-owner,quote-origin-round,market-seed), 50% omission',
                sampling='provider_seed=true; common role/round seed mapping across cells',
                run_order='Fixed sequence, reversed in alternating seed blocks',
                inference='Exploratory interaction; historical cells are not pooled into this factorial')


def worker(root):
    plan=json.loads((root/'study_plan.json').read_text(encoding='utf-8'))
    if plan['backend']=='live':
        from poseidon_compute.runtime_metadata import validate_serving_runtime
        runtime=serving_runtime_metadata()
        if runtime is None:
            raise ValueError('Run live worker through the ephemeral Modal host')
        validate_serving_runtime(runtime)
    (root/'cells').mkdir(exist_ok=False)
    (root/'configs').mkdir(exist_ok=False)
    status='running'
    source_hashes={k:v for k,v in provenance()['source_sha256'].items() if k.endswith(('.py','.jinja2'))}
    dump(root/'study_source_hashes.json',source_hashes)
    try:
        for job in plan['jobs']:
            for path,digest in source_hashes.items():
                if sha256(ROOT/path)!=digest:
                    raise ValueError('Executable source changed during batch; stopping before another cell')
            bundle=root/'cells'/job['id']
            config=root/'configs'/(job['id']+'.json')
            dump(config,job['config'])

            def factory(protocol,session,seed,condition='warmup',state=None):
                market=make_market(protocol,session,seed,condition,state,market_class=ObservationMarket)
                market.visibility_mode=job['visibility']
                market.observation_seed=seed
                market.observation_path=bundle/'observations.jsonl'
                dump(bundle/'observation_spec.json',dict(mode=job['visibility'],mask=plan['mask'],
                     current_and_historical_quotes=True,own_information_preserved=True,
                     buyers_unchanged=True,realized_trades_preserved=True,
                     messages_may_relay_hidden_information=True))
                return market

            args=argparse.Namespace(config=config,stage='control',backend=plan['backend'],
                model=plan['model'] if plan['backend']=='live' else None,out=bundle,
                from_control=None,max_calls=job['maximum_requests'])
            print('STUDY_CELL '+job['id'],flush=True)
            code=run(args,market_factory=factory)
            if code!=0:
                status='stopped_technical_failure'
                return code
        status='complete'
        return 0
    finally:
        dump(root/'study_status.json',dict(status=status if status!='running' else 'interrupted_or_failed',finished_at=utc_now()))
        # Do not read a partial/unsealed cell if interruption occurred mid-write.
        if status!='running':
            analyze_study(root,root/'analysis')
            print('STUDY_RESULTS '+str(root/'analysis/RESULTS.md'),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',choices=['plan','run','worker'],default='plan')
    p.add_argument('--backend',choices=['live','synthetic'],default='live')
    p.add_argument('--seeds',type=int,nargs='+',default=[20,21])
    p.add_argument('--out',type=Path)
    args=p.parse_args()
    if args.stage=='worker':
        if args.out is None:
            p.error('worker requires --out')
        return worker(args.out.resolve())
    plan=make_plan(args.seeds,args.backend)
    root=(args.out or ROOT/'output'/('information_study_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])).resolve()
    if root.exists():
        raise FileExistsError(f'Output already exists: {root}')
    print(json.dumps({k:v for k,v in plan.items() if k!='jobs'},indent=2),flush=True)
    print('OUTPUT '+str(root),flush=True)
    if args.stage=='plan':
        return 0
    root.mkdir(parents=True,exist_ok=False)
    dump(root/'study_plan.json',plan)
    if args.backend=='synthetic':
        return worker(root)
    command=[sys.executable,'-X','utf8','-c','from poseidon_compute.hosted_model import main; main()',
        '--model',plan['model'],'--gpu','A10G','--ready-timeout','600','--run-timeout','14400','--',
        sys.executable,'-X','utf8','-m','research.endogenous_defection.information_study',
        '--stage','worker','--out',str(root)]
    with (root/'host.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                 text=True,encoding='utf-8',errors='replace')
        try:
            for line in process.stdout:
                log.write(line); log.flush()
                print(line,end='',flush=True)
            code=process.wait()
        except BaseException:
            process.terminate()
            process.wait(timeout=30)
            raise
    dump(root/'host_exit.json',dict(exit_code=code,finished_at=utc_now()))
    return code


if __name__=='__main__':
    raise SystemExit(main())
