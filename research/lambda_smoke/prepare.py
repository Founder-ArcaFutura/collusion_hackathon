"""Export a small, credential-free Lambda smoke bundle; no cloud calls."""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]


def prepare():
    target = ROOT / 'output' / ('lambda_smoke_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    for name in ('Dockerfile', 'run.sh', 'smoke.py', 'README.md'):
        shutil.copyfile(Path(__file__).parent / name, target / name)
    for relative, name in (
        ('util/poseidon_compute/runtime_metadata.py', 'runtime_metadata.py'),
        ('research/endogenous_defection/response_schema.py', 'response_schema.py'),
    ):
        shutil.copyfile(ROOT / relative, target / name)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}
    (target / 'source_sha256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive = shutil.make_archive(str(target), 'gztar', root_dir=target.parent, base_dir=target.name)
    print(archive)
    return target


if __name__ == '__main__':
    prepare()
