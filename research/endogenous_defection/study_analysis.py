"""Offline market-level outcomes and paired contrasts for the information study."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean

from .io import dump, read_jsonl, verify


def csv_file(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ['status'])
        writer.writeheader()
        writer.writerows(rows)


def analyze_study(root, out):
    root, out = Path(root), Path(out)
    plan = json.loads((root / 'study_plan.json').read_text(encoding='utf-8'))
    outcomes, observation_rows, messages = [], [], []
    for job in plan['jobs']:
        bundle = root / 'cells' / job['id']
        if not (bundle / 'bundle.json').exists():
            outcomes.append(dict(job=job['id'], seed=job['seed'], cell=job['cell'],
                status='not_attempted', completed_rounds=0, planned_rounds=plan['rounds'],
                mean_trade_price=None, trades=None, trade_capacity_rate=None, seller_profit_per_seller=None,
                buyer_surplus=None, welfare=None, requests=None, rejected_responses=None))
            continue
        meta = json.loads((bundle / 'bundle.json').read_text(encoding='utf-8'))
        if meta['status'] == 'running' or not (bundle / 'checksums.json').exists():
            raise ValueError(f'Cell is not sealed: {job["id"]}')
        verify(bundle)
        path = bundle / f'seed_{job["seed"]}/warmup.jsonl'
        rounds = read_jsonl(path) if path.exists() else []
        events_path = bundle / 'events.jsonl'
        events = read_jsonl(events_path) if events_path.exists() else []
        trades = [t for r in rounds for t in r['market']['trades']]
        outcomes.append(dict(job=job['id'], seed=job['seed'], cell=job['cell'],
            status=meta['status'], completed_rounds=len(rounds), planned_rounds=plan['rounds'],
            mean_trade_price=mean(t['price'] for t in trades) if trades else None,
            trades=len(trades), trade_capacity_rate=len(trades)/(5*len(rounds)) if rounds else None,
            seller_profit_per_seller=sum(r['metrics']['seller_profit'] for r in rounds)/5,
            buyer_surplus=sum(r['metrics']['buyer_surplus'] for r in rounds),
            welfare=sum(r['metrics']['total_welfare'] for r in rounds),
            requests=meta['actual_requests'],
            rejected_responses=sum(e['event']=='response_validation_failed' for e in events)))
        for r in rounds:
            for seller, text in r['market']['seller_messages'].items():
                if text:
                    messages.append(dict(job=job['id'], seed=job['seed'], round=r['metrics']['round'],
                        sender=seller, text=text, category='UNREVIEWED', accurate_fact='UNREVIEWED',
                        novel_to_recipient='UNREVIEWED', subsequent_use='UNREVIEWED'))
        obs = bundle / 'observations.jsonl'
        for row in read_jsonl(obs) if obs.exists() else []:
            if row['role'] == 'seller':
                masks = [m for m in row['current_quote_masks'] if m['owner'] != row['observer']]
                observation_rows.append(dict(job=job['id'], seed=job['seed'], round=row['round'],
                    observer=row['observer'], mode=row['mode'], rival_quotes=len(masks),
                    hidden_rival_quotes=sum(not m['visible'] for m in masks),
                    historical_hidden=sum(not m['visible'] for m in row['historical_quote_masks'])))
    contrasts = []
    metrics = ['mean_trade_price','trades','trade_capacity_rate','seller_profit_per_seller','buyer_surplus','welfare']
    for seed in plan['seeds']:
        complete = {r['cell']:r for r in outcomes if r['seed']==seed and r['status']=='complete'
                    and r['completed_rounds']==r['planned_rounds']}
        for metric in metrics:
            def diff(mode):
                a,b=complete.get(mode+'_on'),complete.get(mode+'_off')
                return a[metric]-b[metric] if a and b and a[metric] is not None and b[metric] is not None else None
            full, partial = diff('full'), diff('partial')
            contrasts.append(dict(seed=seed, metric=metric, full_on_minus_off=full,
                partial_on_minus_off=partial, interaction=partial-full if full is not None and partial is not None else None))
    out.mkdir(parents=True, exist_ok=False)
    csv_file(out/'market_outcomes.csv', outcomes)
    csv_file(out/'paired_contrasts.csv', contrasts)
    csv_file(out/'observation_checks.csv', observation_rows)
    csv_file(out/'messages_for_coding.csv', messages)
    summary = dict(synthetic=plan['backend']=='synthetic', outcomes=outcomes, paired_contrasts=contrasts,
                   inference='Exploratory market-level contrasts; no equivalence or significance claim')
    dump(out/'analysis.json', summary)
    text=['# Information × communication study', '',
          '**SYNTHETIC VALIDATION ONLY**' if summary['synthetic'] else '**Exploratory live results**', '',
          'Each row is one market. Missing/failed cells are retained. Zero-trade market prices are undefined. '
          'Paired contrasts use complete matched cells only; no trade-level independence is assumed.', '',
          '| Seed | Cell | Status | Rounds | Trades | Mean executed price |',
          '| --- | --- | --- | ---: | ---: | ---: |']
    for r in outcomes:
        price='NA' if r['mean_trade_price'] is None else f"{r['mean_trade_price']:.2f}"
        text.append(f"| {r['seed']} | {r['cell']} | {r['status']} | {r['completed_rounds']}/{r['planned_rounds']} | {r['trades']} | {price} |")
    text += ['', 'The interaction is (partial ON − partial OFF) − (full ON − full OFF). '
             'See paired_contrasts.csv for each seed and outcome. Message categories remain UNREVIEWED until coded.']
    (out/'RESULTS.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('study',type=Path)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    analyze_study(args.study,args.out)


if __name__=='__main__':
    main()
