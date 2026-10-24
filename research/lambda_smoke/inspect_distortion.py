"""Read sealed pilot trajectories; write derived tables outside evidence bundles."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean

from research.endogenous_defection.io import read_jsonl, verify


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    trajectories, decisions, messages = [], [], []
    checks = dict(bundles=0, observations=0, selected_current_quotes=0, current_quotes=0,
                  selected_historical_quotes=0, buyer_observations_unchanged=True)
    for bundle in sorted((args.pilot / 'cells').iterdir()):
        verify(bundle); checks['bundles'] += 1
        rounds = read_jsonl(next(bundle.glob('seed_*/warmup.jsonl')))
        by_round = {r['metrics']['round']: r for r in rounds}
        for record in read_jsonl(bundle / 'distortions.jsonl'):
            checks['observations'] += 1
            if record['role'] == 'buyer':
                assert record['rendered_observation'] == record['true_observation']
                continue
            true, shown = record['true_observation'], record['rendered_observation']
            assert true['bid_queue'] == shown['bid_queue'] and true['past_trades'] == shown['past_trades']
            assert len(true['ask_queue']) == len(shown['ask_queue'])
            for field in ('current_quotes', 'historical_quotes'):
                for q in record[field]:
                    assert abs(q['displayed_price'] - q['true_price'] - (10 if q['selected'] else 0)) < 1e-8
                    assert q['owner'] != record['observer'] or not q['selected']
                    if field == 'current_quotes':
                        checks['current_quotes'] += 1
                        checks['selected_current_quotes'] += int(q['selected'])
                    else:
                        checks['selected_historical_quotes'] += int(q['selected'])
            r = by_round[record['round']]
            decisions.append(dict(cell=bundle.name, round=record['round'], seller=record['observer'],
                true_min_ask=min((q[0] for q in true['ask_queue']), default=None),
                shown_min_ask=min((q[0] for q in shown['ask_queue']), default=None),
                selected=sum(q['selected'] for q in record['current_quotes']),
                own_ask=r['market']['seller_asks'].get(record['observer']),
                message=r['market']['seller_messages'].get(record['observer'])))
        for r in rounds:
            m, metrics = r['market'], r['metrics']
            bids = [v for v in m['buyer_bids'].values() if isinstance(v, (float, int))]
            trajectories.append(dict(cell=bundle.name, round=metrics['round'], mean_ask=metrics['mean_ask'],
                mean_submitted_bid=mean(bids) if bids else None, trades=metrics['trade_count'],
                mean_trade_price=metrics['mean_trade_price'], seller_profit=metrics['seller_profit'],
                asks_ge_95=sum(v >= 95 for v in m['seller_asks'].values() if isinstance(v, (float,int)))))
            for seller, text in m['seller_messages'].items():
                messages.append(dict(cell=bundle.name, round=metrics['round'], seller=seller, message=text))
    write_csv(args.out / 'round_trajectories.csv', trajectories)
    write_csv(args.out / 'exposure_decisions.csv', decisions)
    write_csv(args.out / 'seller_messages.csv', messages)
    (args.out / 'audit.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
