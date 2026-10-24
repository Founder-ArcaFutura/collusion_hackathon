"""Paired current-book quote interventions on four saved seller states."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from research.endogenous_defection.io import dump, read_jsonl, verify, seal, utc_now, serving_runtime_metadata
from research.endogenous_defection.response_schema import seller_schema
from research.endogenous_defection.auction import validate_response

ROOT = Path(__file__).resolve().parents[2]
PATTERN = re.compile(r'(## Current Status of Ask Queue\s*\n)(\[[^\n]*\])')


def guard_paired_hosts(output):
    for path in output.glob('paired_quote_*/plan.json'):
        root = path.parent
        # Legacy local fixtures created by this implementation's offline validation.
        # Never ignore a fixture if it contains any evidence of a real host launch.
        mock = root.name in ('paired_quote_mock_validation', 'paired_quote_mock_validation_v2')
        host_evidence = any((root / name).exists() for name in ('live_launch.json', 'host.log', 'counterfactual_source.py'))
        if mock and not host_evidence:
            continue
        if not (root / 'host_exit.json').exists():
            raise ValueError('Previous paired host shutdown unconfirmed: ' + root.name)


def plan():
    states = []
    for seed in (20,21):
        bundle = ROOT / f'output/information_study_20261024_095806_35d3842f/cells/seed_{seed}_full_on'
        verify(bundle)
        events = read_jsonl(bundle / 'events.jsonl')
        for number in (2,5):
            candidates = []
            for e in events:
                if e.get('event') != 'response' or e.get('round') != number or not e.get('agent','').startswith('Seller '):
                    continue
                match = PATTERN.search(e['prompt'])
                if match and any(owner != e['agent'] for _,owner in ast.literal_eval(match[2])):
                    candidates.append(e)
            event = sorted(candidates, key=lambda e:(e['agent'], e['call']))[0]
            match = PATTERN.search(event['prompt'])
            queue = ast.literal_eval(match[2])
            rival = min((float(price),owner) for price,owner in queue if owner != event['agent'])
            variants = {}
            for mode in ('truthful','masked','up10','down10'):
                changed = [(round(float(price)+(10 if mode=='up10' else -10 if mode=='down10' else 0),2), owner)
                    if owner==rival[1] else (price,owner) for price,owner in queue
                    if not (mode=='masked' and owner==rival[1])]
                # Preserve identities/order except masked quote; isolate its displayed value.
                variants[mode] = event['prompt'][:match.start(2)] + (match[2] if mode=='truthful' else repr(changed)) + event['prompt'][match.end(2):]
            assert variants['truthful'] == event['prompt']
            states.append(dict(seed=seed, round=number, agent=event['agent'], rival=list(rival),
                source=str(bundle), source_seal_sha256=hashlib.sha256((bundle/'checksums.json').read_bytes()).hexdigest(),
                variants=variants))
    return dict(version='paired-current-quote-v1', model='Qwen/Qwen2.5-7B-Instruct',
        selection='For each seed 20/21, rounds 2/5: alphabetically first seller with rival quote; lowest rival price, owner tie-break',
        sampling_seeds=[901,902,903], states=states, decisions=48, maximum_requests=49,
        scope='Current ask queue only; history, memory and messages fixed. Rank/order is fixed; resulting ordering contradictions are possible. Selected states are not representative.',
        schema='agent-action-json-v1', max_tokens=1200, temperature=0.7, sdk_retries=0)


def execute(root):
    import urllib.request
    from poseidon_compute.runtime_metadata import validate_serving_runtime
    from research.endogenous_defection.study_analysis import csv_file
    saved = json.loads((root/'plan.json').read_text())
    assert saved == plan(), 'Saved sources or plan changed'
    dump(root/'runtime.json', validate_serving_runtime(serving_runtime_metadata()))
    schema = seller_schema(True)
    calls, results = 0, []
    def request(payload, timeout):
        nonlocal calls
        if calls >= 49:
            raise ValueError('Request ceiling exhausted')
        calls += 1
        dump(root/f'request_{calls:02d}.json',payload)
        req=urllib.request.Request(os.environ['LLM_BASE_URL'].rstrip('/')+'/chat/completions',
            data=json.dumps(payload).encode(), headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['LLM_API_KEY']})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw=response.read()
        (root/f'response_{calls:02d}.json').write_bytes(raw)
        return json.loads(raw)
    status='failed'
    try:
        request(dict(model=saved['model'],messages=[dict(role='user',content='Return a brief valid JSON action with empty text fields.')],
            guided_json=schema,max_tokens=128,temperature=0.7,seed=900),900)
        for index,state in enumerate(saved['states']):
            for sampling_seed in saved['sampling_seeds']:
                modes=['truthful','masked','up10','down10']
                offset=(index+sampling_seed)%4
                modes=modes[offset:]+modes[:offset]
                for mode in modes:
                    result=request(dict(model=saved['model'],messages=[dict(role='user',content=state['variants'][mode])],
                        guided_json=schema,max_tokens=1200,temperature=0.7,seed=sampling_seed),300)
                    choice=result['choices'][0]
                    row=dict(state=index,market_seed=state['seed'],round=state['round'],agent=state['agent'],
                        sampling_seed=sampling_seed,mode=mode,ask=None,accepted=False,finish_reason=choice['finish_reason'],error=None)
                    try:
                        if choice['finish_reason']!='stop': raise ValueError('Incomplete generation')
                        parsed=validate_response(choice['message']['content'],'ask',allow_numeric_strings=True,role='seller',comms_enabled=True)
                        row.update(ask=parsed['ask'],accepted=True)
                    except (ValueError,RuntimeError) as exc:
                        row['error']=str(exc)
                    results.append(row)
                    csv_file(root/'decisions.csv',results)
                    print('PAIRED_DECISION '+json.dumps(row),flush=True)
        status='complete'
    finally:
        dump(root/'status.json',dict(status=status,requests=calls,maximum_requests=49,finished_at=utc_now()))
        seal(root)
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=['plan','run','worker'],default='plan')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if args.stage=='worker': return execute(args.out.resolve())
    design=plan()
    print(json.dumps({k:v for k,v in design.items() if k!='states'},indent=2),flush=True)
    if args.stage=='plan': return 0
    from research.endogenous_defection.distortion_v1.__main__ import guard_idle
    guard_idle()
    guard_paired_hosts(ROOT/'output')
    root=(args.out or ROOT/'output'/('paired_quote_'+uuid.uuid4().hex[:10])).resolve()
    root.mkdir(parents=True,exist_ok=False)
    dump(root/'live_launch.json',dict(backend='live',created_at=utc_now()))
    dump(root/'plan.json',design)
    (root/'counterfactual_source.py').write_bytes(Path(__file__).read_bytes())
    cmd=[sys.executable,'-X','utf8','-c','from poseidon_compute.hosted_model import main; main()',
        '--model',design['model'],'--gpu','A10G','--ready-timeout','600','--run-timeout','5400','--',
        sys.executable,'-X','utf8','-m','research.lambda_smoke.counterfactual','--stage','worker','--out',str(root)]
    with (root/'host.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
        try:
            for line in process.stdout: log.write(line);log.flush();print(line,end='',flush=True)
            code=process.wait()
        except BaseException:
            process.terminate();process.wait(timeout=30);raise
    dump(root/'host_exit.json',dict(exit_code=code,finished_at=utc_now()))
    # Preserve the worker-time seal; finalize only after the host log closes.
    if (root/'checksums.json').exists():
        (root/'worker_checksums.json').write_bytes((root/'checksums.json').read_bytes())
    seal(root)
    print('PAIRED_RESULTS '+str(root),flush=True)
    return code


if __name__=='__main__': raise SystemExit(main())
