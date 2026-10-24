"""Wait for a sealed market run, then produce a fresh offline evidence review."""
import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from .analyze import analyze
from .io import dump, read_jsonl, utc_now, verify
from .run_missing_cell import compare


def wait_for_bundle(run, timeout, interval=5):
    bundle = run / 'bundle' if (run / 'bundle').is_dir() else run
    deadline = time.monotonic() + timeout
    last = None
    while True:
        try:
            meta = json.loads((bundle / 'bundle.json').read_text(encoding='utf-8'))
            if meta['status'] != 'running' and (bundle / 'checksums.json').exists():
                verify(bundle)
                return bundle, meta
            rounds = {}
            for path in bundle.glob('seed_*/warmup.jsonl'):
                rounds[path.parent.name] = len(path.read_text(encoding='utf-8').splitlines())
            progress = (meta['status'], tuple(sorted(rounds.items())))
            if progress != last:
                print('WAITING ' + json.dumps(dict(status=meta['status'], completed_rounds=rounds)), flush=True)
                last = progress
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # A final metadata/checksum write can briefly be incomplete.
        if time.monotonic() >= deadline:
            raise TimeoutError('Run is not sealed yet; no live evidence was analyzed or changed')
        time.sleep(min(interval, max(0, deadline-time.monotonic())))


def review(run, out, timeout=0):
    bundle, meta = wait_for_bundle(Path(run), timeout)
    out = Path(out)
    if bundle.resolve() == out.resolve() or bundle.resolve() in out.resolve().parents:
        raise ValueError('Review output must be outside the sealed evidence bundle')
    out.mkdir(parents=True, exist_ok=False)
    analyze(bundle, out / 'analysis')
    compare(bundle, out)
    events = read_jsonl(bundle / 'events.jsonl')
    accepted = {e['call'] for e in events if e['event'] == 'action_accepted'}
    responses = [e for e in events if e['event'] == 'response']
    audit = []
    for path in sorted(bundle.glob('seed_*/warmup.jsonl')):
        rounds = read_jsonl(path)
        bids_above_value = [dict(round=r['metrics']['round'], agent=buyer, bid=bid,
                                 value=r['buyer_values'][buyer])
                            for r in rounds for buyer,bid in r['market']['buyer_bids'].items()
                            if bid > r['buyer_values'][buyer]]
        trades = [t for r in rounds for t in r['market']['trades']]
        audit.append(dict(seed=path.parent.name, completed_rounds=len(rounds),
            bids_above_value=bids_above_value, maximum_executed_price=max(
                (t['price'] for t in trades), default=None),
            accounting_consistent=all(abs(r['metrics']['seller_profit'] +
                r['metrics']['buyer_surplus'] - r['metrics']['total_welfare']) < 1e-8 for r in rounds)))
    summary = dict(reviewed_at=utc_now(), bundle=str(bundle.resolve()), checksum_verified=True,
        status=meta['status'], scientific_claim='Exploratory market observations',
        final_summary=meta['final_summary'], seed_audit=audit,
        accepted_response_calls=len(accepted), saved_response_count=len(responses),
        files=dict(results=str(out/'RESULTS.md'), comparison=str(out/'comparison.csv'),
                   analysis=str(out/'analysis')))
    dump(out / 'review.json', summary)
    print('REVIEW_SUMMARY ' + json.dumps(summary, sort_keys=True), flush=True)
    print('RESULTS: ' + str(out / 'RESULTS.md'), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--wait-seconds', type=int, default=0)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.wait_seconds < 0:
        parser.error('--wait-seconds must be nonnegative')
    parent = args.run if (args.run/'bundle').is_dir() else args.run.parent
    out = args.out or parent / ('review_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    review(args.run, out, args.wait_seconds)


if __name__ == '__main__':
    main()
