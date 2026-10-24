"""Run the missing exploratory cell once, then analyze and compare saved results."""
import argparse
import csv
import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from .analyze import analyze, direct_metrics
from .config import load_protocol
from .io import dump, read_jsonl, utc_now, verify
from .run_experiment import validate_live_request

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'research/endogenous_defection/configs/factorial_3x5_comms_off_v5_format_recovery.json'
RESULTS = ROOT / 'research/endogenous_defection/results'
PRIOR = [('5x5_on', 'baseline_A_v2_full_001'),
         ('5x5_off', 'factorial_5x5_comms_off_v1'),
         ('3x5_on', 'factorial_3x5_comms_on_v1')]


def compare(bundle, out):
    rows = []
    sources = [(label, RESULTS / name) for label, name in PRIOR] + [('3x5_off_recovery', bundle)]
    for label, source in sources:
        verify(source)
        meta = json.loads((source / 'bundle.json').read_text(encoding='utf-8'))
        protocol = load_protocol(source / 'protocol.json')
        if source == bundle and protocol.max_action_attempts == 1:
            label = '3x5_off_failed_original'
        events = read_jsonl(source / 'events.jsonl')
        for seed in protocol.seeds:
            path = source / f'seed_{seed}/warmup.jsonl'
            rounds = [direct_metrics(r) for r in read_jsonl(path)] if path.exists() else []
            trades = [t for r in rounds for t in r['market']['trades']]
            seed_events = [e for e in events if e.get('seed') == seed]
            rows.append(dict(cell=label, seed=seed, bundle_status=meta['status'],
                protocol=protocol.protocol_version, max_action_attempts=protocol.max_action_attempts,
                completed_rounds=len(rounds), planned_rounds=protocol.warmup_rounds,
                requests=sum(e['event'] == 'request_started' for e in seed_events),
                rejected_responses=sum(e['event'] == 'response_validation_failed' for e in seed_events),
                format_recoveries=sum(e['event'] == 'format_recovery_scheduled' for e in seed_events),
                trade_count=len(trades),
                transaction_weighted_mean_price=sum(t['price'] for t in trades)/len(trades) if trades else None,
                mean_ask=sum(r['metrics']['mean_ask'] for r in rounds)/len(rounds) if rounds else None,
                seller_profit=sum(r['metrics']['seller_profit'] for r in rounds),
                buyer_surplus=sum(r['metrics']['buyer_surplus'] for r in rounds),
                gate=meta['final_summary']['gate']['result']))
    dump(out / 'comparison.json', rows)
    with (out / 'comparison.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    text = ['# Exploratory results', '',
        'A v5 recovery run, when present, permits one bounded format regeneration; the older cells do not. '
        'The failed original cell remains missing unless a completed replacement is recorded below. '
        'Comparisons across execution policies are descriptive, not a clean causal 2x2 estimate. '
        'Failed/partial runs remain labelled and are not counted as complete cells.', '',
        '| Cell | Seed | Rounds | Trades | Mean executed price | Rejected responses | Gate |',
        '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in rows:
        price = row['transaction_weighted_mean_price']
        text.append(f"| {row['cell']} | {row['seed']} | {row['completed_rounds']}/{row['planned_rounds']} "
                    f"| {row['trade_count']} | {price:.2f} | {row['rejected_responses']} | {row['gate']} |"
                    if price is not None else
                    f"| {row['cell']} | {row['seed']} | {row['completed_rounds']}/{row['planned_rounds']} "
                    f"| {row['trade_count']} | NA | {row['rejected_responses']} | {row['gate']} |")
    (out / 'RESULTS.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Start the bounded paid Modal run; default is local preflight only')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    out = args.out or ROOT / 'output' / ('missing_cell_' + run_id)
    if out.exists():
        raise FileExistsError(f'Output exists: {out}')
    bundle = out / 'bundle'
    protocol = load_protocol(CONFIG)
    validated = argparse.Namespace(backend='live', stage='control', model=protocol.model_id,
        max_calls=320, out=bundle)
    validate_live_request(validated, protocol)
    command = [sys.executable, '-X', 'utf8', '-c',
        'from poseidon_compute.hosted_model import main; main()', '--model', protocol.model_id,
        '--gpu', 'A10G', '--ready-timeout', '600', '--run-timeout', '7200', '--',
        sys.executable, '-X', 'utf8', '-m', 'research.endogenous_defection.run_experiment',
        '--config', str(CONFIG), '--stage', 'control', '--backend', 'live', '--model', protocol.model_id,
        '--max-calls', '320', '--out', str(bundle)]
    plan = dict(decisions=160, maximum_requests=320, max_action_attempts=2, max_tokens=1200,
                model=protocol.model_id, protocol=protocol.protocol_version,
                output=str(out), paid_run=args.run, created_at=utc_now())
    print(json.dumps(plan, indent=2), flush=True)
    if not args.run:
        return 0
    out.mkdir(parents=True, exist_ok=False)
    dump(out / 'launch_plan.json', plan)
    with (out / 'host.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace')
        try:
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)
            code = process.wait()
        except BaseException:
            process.terminate()
            process.wait(timeout=30)
            raise
    dump(out / 'host_exit.json', dict(exit_code=code, finished_at=utc_now()))
    if (bundle / 'checksums.json').exists():
        analyze(bundle, out / 'analysis')
        compare(bundle, out)
        print('RESULTS: ' + str(out / 'RESULTS.md'), flush=True)
    else:
        print('Host failed before a sealed experiment bundle; inspect ' + str(out / 'host.log'), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
