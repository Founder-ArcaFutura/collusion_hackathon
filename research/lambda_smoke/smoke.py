"""At most two completions, no inference retries; not research results."""
import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path

from jsonschema import validate
from response_schema import bounded_scratchpad_buyer_schema, bounded_scratchpad_seller_schema
from runtime_metadata import RUNTIME_HEADER, collect_serving_runtime, validate_serving_runtime

MODEL = 'Qwen/Qwen2.5-7B-Instruct'
BASE = 'http://127.0.0.1:8000/v1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    runtime = collect_serving_runtime()
    deadline = time.monotonic() + 900
    while True:
        try:
            response = urllib.request.urlopen(BASE + '/models', timeout=10)
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError('Server not ready after 900 seconds')
            time.sleep(5)
            continue
        with response:
            validate_serving_runtime(json.loads(response.headers[RUNTIME_HEADER]))
            models = json.load(response)
            if MODEL not in [m['id'] for m in models['data']]:
                raise ValueError('Wrong served model')
        break
    (args.out / 'runtime.json').write_text(json.dumps(runtime, indent=2), encoding='utf-8')
    for index, (role, schema, instruction) in enumerate((
        ('seller', bounded_scratchpad_seller_schema(True), 'You are a seller with unit cost 80. Choose an ask of 85 and a short message to other sellers.'),
        ('buyer', bounded_scratchpad_buyer_schema(False), 'You are a buyer with unit value 100. Choose a bid of 90.'),
    )):
        payload = dict(model=MODEL, messages=[dict(role='user', content=instruction + ' Return only a JSON object matching the supplied schema. Keep all text fields brief.')],
                       temperature=0.7, seed=20 + index, max_tokens=1200, guided_json=schema)
        (args.out / (role + '_request.json')).write_text(json.dumps(payload, indent=2), encoding='utf-8')
        request = urllib.request.Request(BASE + '/chat/completions', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read()
        (args.out / (role + '_response.json')).write_bytes(raw)
        result = json.loads(raw)
        choice = result['choices'][0]
        if choice['finish_reason'] != 'stop':
            raise ValueError('Non-stop finish reason: ' + str(choice['finish_reason']))
        validate(json.loads(choice['message']['content']), schema)
    (args.out / 'summary.json').write_text(json.dumps(dict(status='passed', requests=2, research_results=False)), encoding='utf-8')
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.out.iterdir() if p.is_file()}
    (args.out / 'checksums.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    print('PASS: two guided JSON completions; infrastructure smoke only.')


if __name__ == '__main__':
    main()
