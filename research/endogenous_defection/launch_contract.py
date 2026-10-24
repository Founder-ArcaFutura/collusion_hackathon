"""Run local safeguards, then optionally host a two-call API contract probe."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .launch_baseline import DEFAULT_CONFIG, ROOT, preflight


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--region-multiplier", type=float, required=True)
    p.add_argument("--verified-remaining-modal-credits-usd", type=float, required=True)
    p.add_argument("--ready-timeout", type=int, default=900)
    p.add_argument("--run-timeout", type=int, default=300)
    p.set_defaults(max_calls=200)
    p.set_defaults(max_calls=200)
    return p


def host_command(args):
    host = Path(sys.executable).with_name("poseidon-host.exe")
    if not host.exists():
        raise FileNotFoundError(f"Modal host CLI is not installed at {host}")
    return [
        str(host), "--model", args.model, "--gpu", "A10G",
        "--ready-timeout", str(args.ready_timeout),
        "--run-timeout", str(args.run_timeout), "--",
        sys.executable, "-m", "research.endogenous_defection.contract_test",
        "--config", str(Path(args.config)), "--model", args.model,
        "--out", str(args.out),
    ]


def launch(args, host_runner=None):
    # Reuse the full A-v2 approval, hash, model, 200-call budget estimate,
    # reserve, timeout and output preflight before starting the Modal host.
    result = preflight(args)
    print(
        json.dumps({"preflight": "passed", "probe_request_ceiling": 2, **result}, indent=2),
        flush=True,
    )
    command = host_command(args)
    runner = host_runner or subprocess.run
    return runner(command, cwd=ROOT, check=False).returncode


def main():
    args = parser().parse_args()
    try:
        return launch(args)
    except (ValueError, RuntimeError, FileExistsError, FileNotFoundError) as exc:
        print(f"Contract preflight stopped before Modal startup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
