"""Append-only events, provenance and tamper-evident result bundles."""

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def serving_runtime_metadata():
    """Return validated package versions relayed by the actual Modal server."""
    raw = os.environ.get("MODAL_SERVING_RUNTIME")
    if raw is None:
        return None
    runtime = json.loads(raw)
    required = {
        "vllm",
        "xgrammar",
        "outlines",
        "guided_decoding_backend",
        "required_api",
        "required_api_available",
    }
    if not isinstance(runtime, dict) or not required.issubset(runtime):
        raise ValueError("Modal serving runtime metadata is incomplete")
    return runtime


def dump(path, value):
    Path(path).write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")


def read_jsonl(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state_sha256(value):
    # Normalize tuples and integer dictionary keys through the checkpoint format.
    normalized = json.loads(json.dumps(value, allow_nan=False))
    return hashlib.sha256(
        json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def git(*args):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def provenance():
    try:
        commit, status = git("rev-parse", "HEAD"), git("status", "--porcelain")
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit, status = None, "unavailable"
    paths = [
        *Path(__file__).parent.glob("*.py"),
        *Path(__file__).parent.glob("tests/*.py"),
        *Path(__file__).parent.glob("*.md"),
        *Path(__file__).parent.glob("configs/*.json"),
        *(ROOT / "llm-agent-collusion/src").rglob("*.py"),
        *(ROOT / "llm-agent-collusion/src").rglob("*.jinja2"),
        *(ROOT / "util/poseidon_compute").glob("*.py"),
    ]
    packages = {}
    for name in (
        "pydantic",
        "openai",
        "numpy",
        "jinja2",
        "backoff",
        "python-dotenv",
        "modal",
        "poseidon-compute",
        "llm-agent-collusion",
    ):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "not installed"
    return {
        "created_at": utc_now(),
        "git_commit": commit,
        "git_dirty": bool(status),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        "modal_serving_runtime": serving_runtime_metadata(),
        "source_sha256": {
            str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p)
            for p in sorted(paths)
        },
    }


def seal(directory):
    directory = Path(directory)
    files = sorted(
        p for p in directory.rglob("*") if p.is_file() and p.name != "checksums.json"
    )
    dump(
        directory / "checksums.json",
        {p.relative_to(directory).as_posix(): sha256(p) for p in files},
    )


def verify(directory):
    directory = Path(directory)
    expected = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
    actual_paths = {
        p.relative_to(directory).as_posix()
        for p in directory.rglob("*")
        if p.is_file() and p.name != "checksums.json"
    }
    if set(expected) != actual_paths or any(
        sha256(directory / p) != digest for p, digest in expected.items()
    ):
        raise ValueError("Bundle files/checksums changed; refusing continuation")
