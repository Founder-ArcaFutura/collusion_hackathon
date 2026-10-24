"""Recipient-level evidence extraction; lexical tags are review aids, not semantic judgments."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from collections import Counter

from research.endogenous_defection.io import read_jsonl, verify, dump

ROOT=Path(__file__).resolve().parents[2]
SOURCES=['information_study_20261024_095806_35d3842f','information_study_20261024_122407_31b6457e']


def csv_file(path, rows):
    if not rows: return
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    messages=[];recipients=[];inventory=[];outcomes=[];contrasts=[]
    for name in SOURCES:
        study=ROOT/'output'/name
        outcomes+=list(csv.DictReader((study/'analysis/market_outcomes.csv').open()))
        contrasts+=list(csv.DictReader((study/'analysis/paired_contrasts.csv').open()))
        for bundle in sorted((study/'cells').iterdir()):
            verify(bundle)
            meta=json.loads((bundle/'bundle.json').read_text())
            inventory.append(dict(source=str(bundle),status=meta['status'],seal_sha256=hashlib.sha256((bundle/'checksums.json').read_bytes()).hexdigest()))
            if meta['status']!='complete' or not bundle.name.endswith('_on'):continue
            seed=int(bundle.name.split('_')[1]);cell='_'.join(bundle.name.split('_')[2:])
            rounds=read_jsonl(bundle/f'seed_{seed}/warmup.jsonl')
            observations=read_jsonl(bundle/'observations.jsonl')
            obs={(o['round'],o['observer']):o for o in observations if o['role']=='seller'}
            agents=sorted({o['observer'] for o in observations if o['role']=='seller'})
            for r in rounds:
                market=r['market'];number=r['metrics']['round']
                for sender,text in market['seller_messages'].items():
                    if not text:continue
                    message_id=f'{seed}_{cell}_{number}_{sender}'
                    prices=sorted(set(float(v) for v in re.findall(r'\$\s*(\d+(?:\.\d{1,2})?)',text)))
                    own=market['seller_asks'].get(sender)
                    # Intentionally conservative: numbers alone do not identify their referent or factual status.
                    tags=[]
                    for tag,pattern in [('lower_price',r'lower|undercut|降低'),('liquidity',r'liquid|trade volume|流动|交易量'),
                        ('higher_price',r'rais|upward|increas.{0,15}price|提高价格'),('coordination',r'coordinat|together|collaborat|共同|协调')]:
                        if re.search(pattern,text,re.I):tags.append(tag)
                    messages.append(dict(id=message_id,seed=seed,cell=cell,round=number,sender=sender,text=text,
                        dollar_prices=json.dumps(prices),submitted_ask=own,
                        own_ask_among_mentioned_prices=own in prices if own is not None else False,
                        lexical_tags=';'.join(tags),contains_non_ascii=any(ord(c)>127 for c in text),
                        semantic_review='UNREVIEWED',factual_claim_review='UNREVIEWED'))
                    for recipient in agents:
                        if recipient==sender:continue
                        next_obs=obs.get((number+1,recipient))
                        if next_obs is None:continue # final-round messages have no measured recipient decision
                        hidden=[q for q in next_obs['historical_quote_masks'] if not q['visible'] and q['quote_round']==number
                            and float(q['price']) in prices]
                        for q in hidden:
                            # A price match is only a candidate: ownership, intended timing and prior knowledge require review.
                            recipients.append(dict(message_id=message_id,seed=seed,cell=cell,sent_round=number,
                                received_round=number+1,sender=sender,recipient=recipient,quote_owner=q['owner'],
                                quote_price=q['price'],matches_sender_own_quote=q['owner']==sender,
                                directly_masked_in_history=True,
                                current_quote_also_hidden=any(x['owner']==q['owner'] and x['quote_round']==number and not x['visible'] for x in next_obs['current_quote_masks']),
                                recipient_next_ask=rounds[number]['market']['seller_asks'].get(recipient),
                                message=text,referent_accuracy_and_novelty='UNREVIEWED'))
    csv_file(args.out/'messages.csv',messages);csv_file(args.out/'recipient_hidden_price_candidates.csv',recipients)
    csv_file(args.out/'market_outcomes.csv',outcomes);csv_file(args.out/'paired_contrasts.csv',contrasts)
    dump(args.out/'evidence_inventory.json',inventory)
    summary={}
    for cell in ('full_on','partial_on'):
        subset=[m for m in messages if m['cell']==cell]
        summary[cell]=dict(messages=len(subset),dollar_price_messages=sum(m['dollar_prices']!='[]' for m in subset),
            lexical_tags=dict(Counter(t for m in subset for t in m['lexical_tags'].split(';') if t)),
            candidate_messages=len({r['message_id'] for r in recipients if r['cell']==cell}),
            recipient_quote_candidate_rows=sum(r['cell']==cell for r in recipients))
    dump(args.out/'summary.json',summary)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
