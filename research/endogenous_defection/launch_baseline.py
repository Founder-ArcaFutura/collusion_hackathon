"""Preflight an approved baseline locally, then optionally start its Modal host."""

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

from .config import load_protocol
from .run_experiment import validate_live_request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GUIDED_CONFIG = HERE / "configs" / "baseline_A_qwen_v2_guided.json"
DEFAULT_CONFIG = GUIDED_CONFIG
LEGACY_CONFIG = HERE / "configs" / "baseline_A_qwen_v1.json"
ESTIMATES = HERE / "BASELINE_BUDGET_ESTIMATES.json"
EXPECTED_A_VERSION = "baseline-A-v1-exploratory-archive-5x5-qwen"
EXPECTED_A_GUIDED_VERSION = "baseline-A-v2-guided-json-archive-5x5-qwen"


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    p.add_argument("--max-calls", type=int, default=200)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument(
        "--region-multiplier",
        type=float,
        required=True,
        help="verified Modal regional price multiplier for the selected workspace/region",
    )
    p.add_argument(
        "--verified-remaining-modal-credits-usd",
        type=float,
        required=True,
        help="verified available Modal credits after checking the account dashboard",
    )
    p.add_argument("--ready-timeout", type=int, default=900)
    p.add_argument("--run-timeout", type=int, default=7200)
    return p


def validate_approved_config_digest(config_path, expected_sha256):
    actual = hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise ValueError(
            "Baseline A config differs from the versioned approved file; re-review and reapprove changes"
        )
    return actual


def preflight(args):
    """Fail closed before invoking poseidon-host or provisioning Modal resources."""
    config = Path(args.config).resolve()
    if config not in (DEFAULT_CONFIG.resolve(), LEGACY_CONFIG.resolve()):
        raise ValueError("This approved launcher is restricted to versioned baseline A")

    budget = json.loads(ESTIMATES.read_text(encoding="utf-8"))
    approval_key = "A_guided_v2" if config == GUIDED_CONFIG.resolve() else "A"
    a_budget = (
        {**budget["A"], **budget["A_guided_v2"]}
        if approval_key == "A_guided_v2"
        else budget["A"]
    )
    validate_approved_config_digest(config, a_budget["approved_config_sha256"])
    protocol = load_protocol(config)
    expected_version = (
        EXPECTED_A_GUIDED_VERSION
        if approval_key == "A_guided_v2"
        else EXPECTED_A_VERSION
    )
    if protocol.protocol_version != expected_version:
        raise ValueError("Baseline A protocol version does not match the approved version")

    planned = validate_live_request(
        argparse.Namespace(
            backend="live",
            stage="preflight",
            model=args.model,
            max_calls=args.max_calls,
            out=args.out,
        ),
        protocol,
    )
    if planned != 200 or args.max_calls != 200:
        raise ValueError("Approved baseline A requires exactly 200 planned requests and a 200-call cap")
    if args.ready_timeout <= 0 or args.run_timeout <= 0:
        raise ValueError("Readiness and run timeouts must be positive")

    envelope = float(a_budget["proposed_planning_envelope_usd"])
    multiplier_low, multiplier_high = a_budget["regional_modifier_sensitivity"]["listed_range"]
    multiplier = float(args.region_multiplier)
    if not math.isfinite(multiplier) or not multiplier_low <= multiplier <= multiplier_high:
        raise ValueError(
            f"--region-multiplier must be verified within {multiplier_low}..{multiplier_high}"
        )
    remaining = float(args.verified_remaining_modal_credits_usd)
    if not math.isfinite(remaining) or remaining <= 0:
        raise ValueError("Verified remaining Modal credits must be a positive USD amount")

    base_high = max(
        float(scenario["total_usd_assuming_1_core_16_gib"])
        for scenario in a_budget["scenarios"]
    )
    regional_estimate = round(base_high * multiplier, 2)
    if regional_estimate > envelope:
        raise ValueError(
            f"Estimated high scenario ${regional_estimate:.2f} exceeds A's ${envelope:.2f} planning envelope"
        )
    if regional_estimate > remaining / 2:
        raise ValueError(
            f"Estimated high scenario ${regional_estimate:.2f} would use more than half of verified remaining Modal credits"
        )
    if not a_budget["execution_enabled"]:
        raise ValueError("Budget approval record does not authorize baseline A")
    if args.out.exists():
        raise FileExistsError(f"Output bundle already exists: {args.out}")

    return {
        "protocol_version": protocol.protocol_version,
        "planned_requests": planned,
        "max_calls": args.max_calls,
        "region_multiplier": multiplier,
        "estimated_high_cost_usd": regional_estimate,
        "planning_envelope_usd": envelope,
        "verified_remaining_modal_credits_usd": remaining,
        "replication_reserve_usd": round(remaining / 2, 2),
        "run_timeout_seconds": args.run_timeout,
        "ready_timeout_seconds": args.ready_timeout,
    }


def host_command(args):
    host = Path(sys.executable).with_name("poseidon-host.exe")
    if not host.exists():
        raise FileNotFoundError(f"Modal host CLI is not installed at {host}")
    experiment = [
        sys.executable,
        "-m",
        "research.endogenous_defection.run_experiment",
        "--config",
        str(Path(args.config)),
        "--stage",
        "control",
        "--backend",
        "live",
        "--model",
        args.model,
        "--max-calls",
        str(args.max_calls),
        "--out",
        str(args.out),
    ]
    return [
        str(host),
        "--model",
        args.model,
        "--gpu",
        "A10G",
        "--ready-timeout",
        str(args.ready_timeout),
        "--run-timeout",
        str(args.run_timeout),
        "--",
        *experiment,
    ]


def launch(args, host_runner=None):
    # This must remain the first operation with external effects. All config,
    # authorization, cap, output-path and budget checks finish before Modal starts.
    result = preflight(args)
    print(json.dumps({"preflight": "passed", **result}, indent=2), flush=True)
    command = host_command(args)
    runner = host_runner or subprocess.run
    return runner(command, cwd=ROOT, check=False).returncode


def main():
    args = parser().parse_args()
    try:
        return launch(args)
    except (ValueError, RuntimeError, FileExistsError, FileNotFoundError) as exc:
        print(f"Preflight stopped before Modal startup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
