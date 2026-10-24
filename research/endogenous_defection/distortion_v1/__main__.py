"""Plan or run four observation-corruption markets after the active study ends."""
import argparse
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from statistics import mean

from ..auction import make_market
from ..config import Protocol
from ..io import dump, read_jsonl, serving_runtime_metadata, sha256, utc_now, verify
from ..run_experiment import run
from ..study_analysis import csv_file
from .observation import DistortionMarket

ROOT=Path(__file__).resolve().parents[3]
PACKAGE=Path(__file__).resolve().parent
DEFAULT_SOURCE=ROOT/'output/information_study_20261024_095806_35d3842f'


def make_plan(source, backend):
    source=Path(source).resolve()
    original=json.loads((source/'study_plan.json').read_text(encoding='utf-8'))
    if original['version']!='information-communication-v1' or original['backend']!='live':
        raise ValueError('Controls must be the completed live information-v1 study')
    controls=[]
    control_runtime=None
    jobs=[]
    for seed in (20,21):
        for cell in ('full_on','full_off','partial_on','partial_off'):
            job=next(j for j in original['jobs'] if j['seed']==seed and j['cell']==cell)
            bundle=source/'cells'/job['id']
            verify(bundle)
            meta=json.loads((bundle/'bundle.json').read_text(encoding='utf-8'))
            if meta['status']!='complete' or meta['actual_requests']!=100:
                raise ValueError('This pilot is pinned to the complete 100-request control markets')
            if control_runtime is None:
                control_runtime=meta['modal_serving_runtime']
            elif meta['modal_serving_runtime']!=control_runtime:
                raise ValueError('Matched controls used different serving runtimes')
            controls.append(dict(seed=seed,cell=cell,bundle=str(bundle),
                checksums_sha256=sha256(bundle/'checksums.json')))
        order=('on','off') if seed==20 else ('off','on')
        for comms in order:
            base=next(j for j in original['jobs'] if j['seed']==seed and j['cell']=='full_'+comms)
            config=dict(base['config'])
            config['protocol_version']='observation-corruption-v1-up10-'+comms
            protocol=Protocol.model_validate(config)
            jobs.append(dict(id=f'seed_{seed}_distort_{comms}',seed=seed,cell='distort_'+comms,
                config=config,maximum_requests=protocol.call_estimate()['control']))
    # Check shared executable contracts against the controls; new isolated pilot
    # files are snapshotted separately inside each new evidence bundle.
    hashes=json.loads((source/'study_source_hashes.json').read_text(encoding='utf-8'))
    for relative in ('research/endogenous_defection/auction.py',
                     'research/endogenous_defection/observations.py',
                     'research/endogenous_defection/response_schema.py',
                     'research/endogenous_defection/config.py'):
        if sha256(ROOT/relative)!=hashes[relative]:
            raise ValueError('Shared scientific code differs from the matched controls')
    return dict(version='observation-corruption-v1',backend=backend,source=str(source),
        seeds=[20,21],rounds=10,decisions=400,maximum_requests=800,jobs=jobs,controls=controls,
        model=original['model'],control_runtime=control_runtime,
        selection='Complement of existing mask_visible, same observer/quote seed rule',
        transformation='Displayed rival ask = true ask + 10.00; no clipping',
        interpretation='Exploratory matched observation-corruption pilot; not actual order spoofing')


def guard_idle():
    for path in (ROOT/'output').glob('information_study_*/study_plan.json'):
        plan=json.loads(path.read_text(encoding='utf-8'))
        if plan['backend']=='live' and not (path.parent/'host_exit.json').exists():
            raise ValueError(f'Live study is active or shutdown is unconfirmed: {path.parent.name}')
    for path in (ROOT/'output').glob('distortion_pilot_*/pilot_plan.json'):
        if json.loads(path.read_text(encoding='utf-8'))['backend']=='live' and not (path.parent/'host_exit.json').exists():
            raise ValueError('Another distortion pilot is active or shutdown is unconfirmed')


def analyze(root):
    plan=json.loads((root/'pilot_plan.json').read_text(encoding='utf-8'))
    references=[(r['seed'],r['cell'],Path(r['bundle']),r['checksums_sha256']) for r in plan['controls']]
    new=[(j['seed'],j['cell'],root/'cells'/j['id'],None) for j in plan['jobs']]
    outcomes=[]
    exposure=[]
    for seed,cell,bundle,digest in references+new:
        if not (bundle/'bundle.json').exists():
            outcomes.append(dict(seed=seed,cell=cell,status='not_attempted',rounds=0,trades=None,
                mean_trade_price=None,mean_ask=None,seller_profit_per_seller=None,buyer_surplus=None,welfare=None))
            continue
        verify(bundle)
        if digest is not None and sha256(bundle/'checksums.json')!=digest:
            raise ValueError('Matched control seal changed')
        meta=json.loads((bundle/'bundle.json').read_text(encoding='utf-8'))
        p=bundle/f'seed_{seed}/warmup.jsonl'
        rows=read_jsonl(p) if p.exists() else []
        trades=[t for r in rows for t in r['market']['trades']]
        outcomes.append(dict(seed=seed,cell=cell,status=meta['status'],rounds=len(rows),trades=len(trades),
            mean_trade_price=mean(t['price'] for t in trades) if trades else None,
            mean_ask=mean(r['metrics']['mean_ask'] for r in rows) if rows else None,
            seller_profit_per_seller=sum(r['metrics']['seller_profit'] for r in rows)/5,
            buyer_surplus=sum(r['metrics']['buyer_surplus'] for r in rows),
            welfare=sum(r['metrics']['total_welfare'] for r in rows)))
        if (bundle/'distortions.jsonl').exists():
            by_round={r['metrics']['round']:r for r in rows}
            for record in read_jsonl(bundle/'distortions.jsonl'):
                if record['role']!='seller': continue
                r=by_round.get(record['round'])
                exposure.append(dict(seed=seed,cell=cell,round=record['round'],observer=record['observer'],
                    selected_quotes=sum(q['selected'] for q in record['current_quotes']),
                    total_offset=sum(q['offset'] for q in record['current_quotes']),
                    ask=r['market']['seller_asks'].get(record['observer']) if r else None,
                    message=r['market']['seller_messages'].get(record['observer']) if r else None))
    out=root/'analysis'; out.mkdir(exist_ok=False)
    csv_file(out/'market_outcomes.csv',outcomes)
    csv_file(out/'exposure_decisions.csv',exposure)
    contrasts=[]
    if plan['backend']=='live':
        for seed in plan['seeds']:
            for comms in ('on','off'):
                pair={r['cell']:r for r in outcomes if r['seed']==seed and r['status']=='complete' and r['rounds']==10}
                a,b=pair.get('distort_'+comms),pair.get('full_'+comms)
                if a and b:
                    contrasts.append(dict(seed=seed,communication=comms,
                        price_distorted_minus_full=a['mean_trade_price']-b['mean_trade_price'] if a['mean_trade_price'] is not None and b['mean_trade_price'] is not None else None,
                        ask_distorted_minus_full=a['mean_ask']-b['mean_ask'],
                        trades_distorted_minus_full=a['trades']-b['trades']))
    csv_file(out/'matched_contrasts.csv',contrasts)
    dump(out/'analysis.json',dict(backend=plan['backend'],outcomes=outcomes,contrasts=contrasts))
    text=['# Observation-corruption pilot','',
          '**Exploratory live results**' if plan['backend']=='live' else '**SYNTHETIC VALIDATION ONLY: new cells are fixtures, not comparable to live controls**','',
          'Selected rival quotes are displayed $10 higher in current book and history. The engine receives true orders. '
          'See market_outcomes.csv, matched_contrasts.csv and exposure_decisions.csv. '
          'This pilot cannot establish broad information integration, human differences or collusion.']
    (out/'RESULTS.md').write_text('\n'.join(text)+'\n',encoding='utf-8')


def worker(root):
    plan=json.loads((root/'pilot_plan.json').read_text(encoding='utf-8'))
    if plan!=make_plan(plan['source'],plan['backend']):
        raise ValueError('Saved pilot plan differs from its versioned design')
    if plan['backend']=='live':
        from poseidon_compute.runtime_metadata import validate_serving_runtime
        runtime=validate_serving_runtime(serving_runtime_metadata())
        for key in ('vllm','outlines','xgrammar','guided_decoding_backend'):
            if runtime.get(key)!=plan['control_runtime'].get(key):
                raise ValueError('Serving runtime differs from matched controls')
    (root/'cells').mkdir(exist_ok=False); (root/'configs').mkdir(exist_ok=False)
    source_hashes={str(p):sha256(p) for p in PACKAGE.glob('*.py')}
    dump(root/'pilot_source_hashes.json',source_hashes)
    for job in plan['jobs']:
        if any(sha256(Path(p))!=digest for p,digest in source_hashes.items()):
            raise ValueError('Pilot source changed during batch')
        if make_plan(plan['source'],plan['backend'])!=plan:
            raise ValueError('Shared code or controls changed during batch')
        bundle=root/'cells'/job['id']; config=root/'configs'/(job['id']+'.json')
        dump(config,job['config'])
        def factory(protocol,session,seed,condition='warmup',state=None):
            market=make_market(protocol,session,seed,condition,state,market_class=DistortionMarket)
            market.visibility_mode='full'; market.observation_seed=seed
            market.distortion_log=bundle/'distortions.jsonl'
            dump(bundle/'distortion_spec.json',dict(transformation=plan['transformation'],
                selection=plan['selection'],true_engine_unchanged=True,display_sort='descending displayed price',
                same_disclosure_as_controls=True))
            target=bundle/'distortion_source'; target.mkdir()
            for path in PACKAGE.glob('*.py'): shutil.copyfile(path,target/path.name)
            dump(target/'sha256.json',{p.name:sha256(p) for p in target.glob('*.py')})
            return market
        args=argparse.Namespace(config=config,stage='control',backend=plan['backend'],
            model=plan['model'] if plan['backend']=='live' else None,from_control=None,
            max_calls=job['maximum_requests'],out=bundle)
        code=run(args,market_factory=factory)
        if code!=0:
            dump(root/'pilot_status.json',dict(status='stopped_technical_failure',finished_at=utc_now()))
            analyze(root)
            return code
    dump(root/'pilot_status.json',dict(status='complete',finished_at=utc_now()))
    analyze(root)
    print('PILOT_RESULTS '+str(root/'analysis/RESULTS.md'),flush=True)
    return 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',choices=['plan','run','worker'],default='plan')
    p.add_argument('--backend',choices=['live','synthetic'],default='live')
    p.add_argument('--source-study',type=Path,default=DEFAULT_SOURCE)
    p.add_argument('--out',type=Path)
    args=p.parse_args()
    if args.stage=='worker':
        if args.out is None: p.error('worker requires --out')
        return worker(args.out.resolve())
    plan=make_plan(args.source_study,args.backend)
    out=(args.out or ROOT/'output'/('distortion_pilot_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])).resolve()
    if out.exists(): raise FileExistsError(str(out))
    print(json.dumps({k:v for k,v in plan.items() if k not in ('jobs','controls')},indent=2),flush=True)
    if args.stage=='plan': return 0
    if args.backend=='live': guard_idle()
    out.mkdir(parents=True,exist_ok=False); dump(out/'pilot_plan.json',plan)
    print('OUTPUT '+str(out),flush=True)
    if args.backend=='synthetic': return worker(out)
    command=[sys.executable,'-X','utf8','-c','from poseidon_compute.hosted_model import main; main()',
        '--model',plan['model'],'--gpu','A10G','--ready-timeout','600','--run-timeout','7200','--',
        sys.executable,'-X','utf8','-m','research.endogenous_defection.distortion_v1',
        '--stage','worker','--out',str(out)]
    with (out/'host.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf-8',errors='replace')
        try:
            for line in process.stdout:
                log.write(line); log.flush(); print(line,end='',flush=True)
            code=process.wait()
        except BaseException:
            process.terminate(); process.wait(timeout=30); raise
    dump(out/'host_exit.json',dict(exit_code=code,finished_at=utc_now()))
    return code


if __name__=='__main__':
    raise SystemExit(main())
