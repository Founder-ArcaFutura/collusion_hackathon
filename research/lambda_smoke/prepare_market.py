"""Export existing auction sources without credentials or historical outputs."""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def prepare():
    target = ROOT / 'output' / ('lambda_market_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    app = target / 'app'
    for relative in ('research/endogenous_defection', 'llm-agent-collusion/src', 'util/poseidon_compute'):
        for source in (ROOT / relative).rglob('*'):
            if source.is_file() and source.suffix in ('.py', '.jinja2', '.json', '.md') and '__pycache__' not in source.parts:
                dest = app / source.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
    for name in ('runtime_metadata.py', 'response_schema.py'):
        source = ROOT / ('util/poseidon_compute/' if name == 'runtime_metadata.py' else 'research/endogenous_defection/') / name
        shutil.copyfile(source, target / name)
    shutil.copyfile(HERE / 'market_worker.py', target / 'market_worker.py')
    docker = (HERE / 'Dockerfile').read_text().replace('COPY runtime_metadata.py response_schema.py smoke.py ./',
        'RUN pip install --no-cache-dir "pydantic>=2.6,<3" "openai>=1.60" python-dotenv jinja2 backoff tqdm pandas matplotlib\nCOPY runtime_metadata.py response_schema.py market_worker.py ./\nCOPY app /app\nENV PYTHONPATH=/app:/app/llm-agent-collusion:/app/util')
    (target / 'Dockerfile').write_text(docker, encoding='utf-8', newline='\n')
    script = (HERE / 'run.sh').read_text().replace('collusion-lambda-smoke', 'collusion-lambda-market').replace('collusion-smoke-', 'collusion-market-').replace('docker exec "$NAME" python smoke.py --out /results',
        'docker exec "$NAME" timeout --signal=INT --kill-after=30s 3600 python market_worker.py --out /results/market')
    (target / 'run.sh').write_text(script, encoding='utf-8', newline='\n')
    hashes = {str(p.relative_to(target)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
    (target / 'source_sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    print(shutil.make_archive(str(target), 'gztar', root_dir=target.parent, base_dir=target.name))
    return target


if __name__ == '__main__':
    prepare()
