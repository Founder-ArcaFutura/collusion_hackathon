"""Plan, validate offline, establish controls, then continue matched interventions."""

import argparse
import json
import random
import shutil
from pathlib import Path

from .config import load_protocol
from .economics import positive_control
from .io import (
    ROOT,
    append,
    dump,
    provenance,
    read_jsonl,
    seal,
    sha256,
    state_sha256,
    utc_now,
    verify,
)
from .response_schema import (
    BOUNDED_SCRATCHPAD_SCHEMA_VERSION,
    BOUNDED_TEXT_SCHEMA_VERSION,
    SCHEMA_VERSION,
)

HERE = Path(__file__).resolve().parent


def safe_failure_reason(exc):
    """Return a bounded, non-sensitive reason suitable for manifests and logs."""
    known = {
        "Invalid model response; raw output retained; no retry or invented action":
            "Invalid model response; raw output retained; no retry or invented action",
        "Incomplete model response; run retained as failed":
            "Incomplete model response; run retained as failed",
        "Inference request budget exhausted": "Inference request budget exhausted",
        "Invalid model response; bounded format recovery exhausted":
            "Invalid model response; bounded format recovery exhausted",
    }
    return known.get(str(exc), type(exc).__name__)


def build_final_summary(out, meta, protocol, session_calls):
    """Summarize durable execution evidence; incomplete rounds do not count."""
    manifest_path = out / "manifest.jsonl"
    records = read_jsonl(manifest_path) if manifest_path.exists() else []
    events_path = out / "events.jsonl"
    events = read_jsonl(events_path) if events_path.exists() else []
    round_counts = {seed: 0 for seed in protocol.seeds}
    for seed in protocol.seeds:
        seed_dir = out / f"seed_{seed}"
        if not seed_dir.exists():
            continue
        for name in ("warmup.jsonl", "rounds.jsonl"):
            for path in seed_dir.rglob(name):
                round_counts[seed] += len(read_jsonl(path))

    by_seed = {}
    failures = []
    for seed in protocol.seeds:
        seed_records = [record for record in records if record.get("seed") == seed]
        calls = [event for event in events if event.get("seed") == seed]
        failed_records = [record for record in seed_records if record.get("status") == "failed"]
        if failed_records:
            status = "failed"
        elif any(record.get("status") == "running" for record in seed_records):
            status = "incomplete"
        elif seed_records and all(record.get("status") == "complete" for record in seed_records):
            status = "complete"
        elif calls or seed_records:
            status = "incomplete"
        else:
            status = "not_attempted"
        manifest_reason = next(
            (record.get("failure_reason") for record in failed_records if record.get("failure_reason")),
            None,
        )
        diagnostic = None
        if failed_records:
            diagnostic = next(
                (
                    event
                    for event in reversed(calls)
                    if event.get("event")
                    in ("response_validation_failed", "request_failed")
                ),
                None,
            )
        reason = (
            (diagnostic or {}).get("validation_error")
            or (
                f"Inference request failed ({diagnostic['error_type']})"
                if diagnostic and diagnostic.get("event") == "request_failed"
                else None
            )
            or manifest_reason
        )
        if failed_records:
            failures.append(
                {
                    "seed": seed,
                    "reason": reason or "Failure reason unavailable",
                    "call": (diagnostic or {}).get("call"),
                    "agent": (diagnostic or {}).get("agent"),
                    "round": (diagnostic or {}).get("round"),
                    "finish_reason": (diagnostic or {}).get("finish_reason"),
                    "error_category": (diagnostic or {}).get("error_category")
                    or (
                        "inference_request_failed"
                        if diagnostic and diagnostic.get("event") == "request_failed"
                        else None
                    ),
                    "error_type": (diagnostic or {}).get("error_type"),
                    "request_timeout_seconds": (diagnostic or {}).get(
                        "request_timeout_seconds"
                    ),
                    "schema_version": (diagnostic or {}).get("schema_version"),
                }
            )
        by_seed[str(seed)] = {
            "status": status,
            "requests": sum(event.get("event") == "request_started" for event in calls),
            "completed_rounds": round_counts[seed],
            "failure_reason": reason,
        }

    attempted = [seed for seed in protocol.seeds if by_seed[str(seed)]["status"] != "not_attempted"]
    completed = [seed for seed in protocol.seeds if by_seed[str(seed)]["status"] == "complete"]
    failed = [seed for seed in protocol.seeds if by_seed[str(seed)]["status"] == "failed"]
    unattempted = [seed for seed in protocol.seeds if by_seed[str(seed)]["status"] == "not_attempted"]
    gate_passed = meta.get("positive_control_gate_passed")
    gate_result = (
        "not_evaluated"
        if meta.get("status") in ("failed", "incomplete") or gate_passed is None
        else "passed"
        if gate_passed is True
        else "failed"
    )
    failure_reason = failures[0]["reason"] if failures else meta.get("failure_reason")
    return {
        "status": meta.get("status", "unknown"),
        "requests": session_calls,
        "planned_requests": meta.get("planned_max_requests"),
        "request_ceiling": meta.get("max_calls"),
        "max_action_attempts": protocol.max_action_attempts,
        "format_recoveries_scheduled": sum(e.get("event") == "format_recovery_scheduled" for e in events),
        "rejected_responses": sum(e.get("event") == "response_validation_failed" for e in events),
        "accepted_actions": sum(e.get("event") == "action_accepted" for e in events),
        "completed_rounds": sum(round_counts.values()),
        "completed_rounds_by_seed": {str(seed): round_counts[seed] for seed in protocol.seeds},
        "seeds": {
            "planned": list(protocol.seeds),
            "attempted": attempted,
            "completed": completed,
            "failed": failed,
            "unattempted": unattempted,
            "by_seed": by_seed,
        },
        "gate": {
            "result": gate_result,
            "passed": gate_passed,
            "qualifying_seeds": meta.get("qualifying_seeds", 0),
            "required_qualifying_seeds": protocol.min_qualifying_seeds,
        },
        "failure_reason": failure_reason,
        "failure_reasons": failures,
    }


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=HERE / "configs/pilot.json")
    p.add_argument(
        "--stage",
        choices=["plan", "preflight", "control", "interventions", "pilot"],
        default="plan",
    )
    p.add_argument("--backend", choices=["synthetic", "live"], default="synthetic")
    p.add_argument(
        "--model", help="Exact model ID; required for live calls; no implicit default"
    )
    p.add_argument("--out", type=Path, help="New bundle directory, never overwritten")
    p.add_argument(
        "--from-control", type=Path, help="Sealed control bundle to continue"
    )
    p.add_argument(
        "--max-calls",
        type=int,
        default=1200,
        help="Hard request cap; provider retries disabled",
    )
    return p


def validate_live_request(args, protocol):
    """Validate a live control request without creating a client or output bundle."""
    if args.backend != "live":
        raise ValueError("Preflight requires --backend live")
    if args.stage not in ("preflight", "control"):
        raise ValueError("Live baseline preflight only allows the control stage")
    if not protocol.execution_enabled:
        raise ValueError("Review-only configuration: user approval is required before live execution")
    if protocol.response_schema_version not in (
        SCHEMA_VERSION,
        BOUNDED_TEXT_SCHEMA_VERSION,
        BOUNDED_SCRATCHPAD_SCHEMA_VERSION,
    ):
        raise ValueError("Live execution requires the versioned guided JSON response protocol")
    if protocol.allow_continuations or any(
        condition.kind != "control" for condition in protocol.conditions
    ):
        raise ValueError("Approved baseline must be control-only with continuations disabled")
    if not args.model:
        raise ValueError("Live execution requires an explicit --model")
    if protocol.model_id and args.model != protocol.model_id:
        raise ValueError("--model must exactly match the approved protocol")
    if args.max_calls < 0:
        raise ValueError("--max-calls must be nonnegative")
    planned = protocol.call_estimate()["control"]
    if planned > args.max_calls:
        raise ValueError(
            f"Plan needs up to {planned} requests; cap is {args.max_calls}. Reduce the config or raise the cap."
        )
    if args.out is None:
        raise ValueError("Preflight requires --out pointing to a new bundle directory")
    if args.out.exists():
        raise FileExistsError(f"Output bundle already exists: {args.out}")
    return planned


def run(args, market_factory=None):
    protocol = load_protocol(args.config)
    if args.max_calls < 0:
        raise ValueError("--max-calls must be nonnegative")
    if args.stage == "preflight":
        planned = validate_live_request(args, protocol)
        print(
            json.dumps(
                {
                    "preflight": "passed",
                    "protocol_version": protocol.protocol_version,
                    "model": args.model,
                    "planned_requests": planned,
                    "max_calls": args.max_calls,
                    "output": str(args.out),
                    "inference_started": False,
                },
                indent=2,
            )
        )
        return 0
    if args.stage == "interventions" and not args.from_control:
        raise ValueError("Interventions require --from-control")
    if args.stage != "interventions" and args.from_control:
        raise ValueError("--from-control is only for the interventions stage")
    estimate = protocol.call_estimate()
    if args.stage == "plan":
        print(
            json.dumps(
                {
                    "protocol": protocol.model_dump(),
                    "calls": estimate,
                    "note": "No inference, credentials or Modal access performed.",
                },
                indent=2,
            )
        )
        return 0
    if not args.out:
        raise ValueError("Execution requires --out pointing to a new directory")
    if not protocol.allow_continuations and args.stage != "control":
        raise ValueError(
            "This baseline protocol is control-only; continuations are disabled"
        )
    if args.backend == "live" and not protocol.execution_enabled:
        raise ValueError(
            "Review-only configuration: user approval is required before enabling live execution"
        )
    if args.backend == "live" and protocol.response_schema_version not in (
        SCHEMA_VERSION,
        BOUNDED_TEXT_SCHEMA_VERSION,
        BOUNDED_SCRATCHPAD_SCHEMA_VERSION,
    ):
        raise ValueError("Live execution requires the versioned guided JSON response protocol")
    if args.backend == "live" and protocol.model_id and args.model != protocol.model_id:
        raise ValueError(
            "--model must exactly match the model_id in the approved protocol"
        )
    if args.backend == "live" and not args.model:
        raise ValueError("Live execution requires an explicit --model")
    planned = estimate[
        {
            "control": "control",
            "interventions": "interventions_max",
            "pilot": "pilot_max",
        }[args.stage]
    ]
    if args.backend == "live" and planned > args.max_calls:
        raise ValueError(
            f"Plan needs up to {planned} requests; cap is {args.max_calls}. Reduce the config or raise the cap."
        )
    parent = None
    if args.from_control:
        verify(args.from_control)
        parent = json.loads(
            (args.from_control / "bundle.json").read_text(encoding="utf-8")
        )
        if parent["stage"] != "control" or parent["status"] != "complete":
            raise ValueError("Parent must be a completed control-only bundle")
        if parent["backend"] != args.backend or parent["model"] != args.model:
            raise ValueError("Backend/model must match the control")
        saved_protocol = load_protocol(args.from_control / "protocol.json")
        if saved_protocol.model_dump(mode="json") != protocol.model_dump(mode="json"):
            raise ValueError(
                "Protocol changed since control; do not change thresholds after seeing results"
            )
        current_provenance = provenance()
        parent_provenance = json.loads(
            (args.from_control / "provenance.json").read_text(encoding="utf-8")
        )
        if (
            current_provenance["packages"] != parent_provenance["packages"]
            or current_provenance["python"] != parent_provenance["python"]
        ):
            raise ValueError("Python/package versions changed since control")
        current = current_provenance["source_sha256"]
        old = parent_provenance["source_sha256"]
        if {k: v for k, v in current.items() if k.endswith((".py", ".jinja2"))} != {
            k: v for k, v in old.items() if k.endswith((".py", ".jinja2"))
        }:
            raise ValueError("Executable sources changed since control")
    args.out.mkdir(parents=True, exist_ok=False)
    dump(args.out / "protocol.json", protocol.model_dump())
    source = provenance()
    dump(args.out / "provenance.json", source)
    # A commit hash alone cannot reproduce uncommitted research. Preserve allowed
    # code/doc sources as well as hashes, never compute.env or arbitrary env files.
    for relative in source["source_sha256"]:
        destination = args.out / "source_snapshot" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    meta = {
        "created_at": utc_now(),
        "stage": args.stage,
        "backend": args.backend,
        "model": args.model,
        "modal_serving_runtime": source["modal_serving_runtime"],
        "synthetic": args.backend == "synthetic",
        "status": "running",
        "planned_max_requests": planned,
        "max_calls": args.max_calls,
        "parent_actual_requests": parent["actual_requests"] if parent else 0,
        "interpretation": "SYNTHETIC VALIDATION ONLY"
        if args.backend == "synthetic"
        else "Exploratory pilot",
        "parent_checksums_sha256": sha256(args.from_control / "checksums.json")
        if parent
        else None,
    }
    dump(args.out / "bundle.json", meta)
    session = None
    failed = False
    try:
        from .auction import Session, intervene, make_market, run_rounds, snapshot

        if market_factory is not None:
            make_market = market_factory

        session = Session(
            protocol,
            args.model,
            args.backend,
            args.max_calls,
            args.out / "events.jsonl",
        )
        meta["endpoint"] = session.provider
        meta["provider_route"] = session.route
        if parent and parent["provider_route"] != session.route:
            raise ValueError("Inference provider changed since control")
        controls = []
        if parent:
            controls = read_jsonl(args.from_control / "manifest.jsonl")
            # Copy the precise evidence into this self-contained continuation bundle.
            shutil.copyfile(
                args.from_control / "manifest.jsonl", args.out / "parent_manifest.jsonl"
            )
            shutil.copyfile(
                args.from_control / "checksums.json", args.out / "parent_checksums.json"
            )
            for name in ("events.jsonl", "bundle.json", "provenance.json"):
                shutil.copyfile(args.from_control / name, args.out / f"parent_{name}")
            for record in controls:
                seed_dir = args.out / f"seed_{record['seed']}"
                seed_dir.mkdir()
                for name in ("checkpoint.json", "warmup.jsonl"):
                    shutil.copyfile(
                        args.from_control / f"seed_{record['seed']}" / name,
                        seed_dir / name,
                    )
        else:
            for seed in protocol.seeds:
                seed_dir = args.out / f"seed_{seed}"
                seed_dir.mkdir()
                market = make_market(protocol, session, seed)
                target = market.sellers[
                    random.Random(seed + 9137).randrange(len(protocol.seller_costs))
                ].id
                record = {
                    "seed": seed,
                    "phase": "warmup",
                    "condition": "warmup",
                    "target": target,
                    "status": "running",
                    "synthetic": args.backend == "synthetic",
                }
                try:
                    rows = run_rounds(
                        market,
                        protocol.warmup_rounds,
                        protocol,
                        seed_dir / "warmup.jsonl",
                        "warmup",
                        target,
                    )
                    gate = positive_control(rows, protocol)
                    checkpoint = {
                        "seed": seed,
                        "target": target,
                        "gate": gate,
                        "state": snapshot(market),
                    }
                    dump(seed_dir / "checkpoint.json", checkpoint)
                    record.update(
                        status="complete",
                        gate_passed=gate["passed"],
                        gate_evaluable=gate["evaluable"],
                        gate_reason=gate["reason"],
                        checkpoint_sha256=sha256(seed_dir / "checkpoint.json"),
                    )
                except Exception as exc:
                    record.update(
                        status="failed",
                        gate_passed=None,
                        error_type=type(exc).__name__,
                        failure_reason=safe_failure_reason(exc),
                    )
                    failed = True
                append(args.out / "manifest.jsonl", record)
                controls.append(record)
                print(
                    f"seed {seed}: control {record['status']}; gate={record['gate_passed']}",
                    flush=True,
                )
                if failed:
                    # Stop on provider/validation failure; don't silently select survivors.
                    break
        passing = [
            r
            for r in controls
            if r.get("status") == "complete" and r.get("gate_passed")
        ]
        meta["qualifying_seeds"] = len(passing)
        meta["positive_control_gate_passed"] = (
            None
            if failed
            or not any(
                r.get("status") == "complete" and r.get("gate_evaluable") is True
                for r in controls
            )
            else len(passing) >= protocol.min_qualifying_seeds
        )
        if args.stage != "control" and not failed:
            if not meta["positive_control_gate_passed"]:
                meta["status"] = "stopped_positive_control"
                print(
                    "STOP: positive-control gate not established; no interventions run."
                )
            else:
                for record in passing:
                    seed = record["seed"]
                    seed_dir = args.out / f"seed_{seed}"
                    checkpoint_path = seed_dir / "checkpoint.json"
                    if sha256(checkpoint_path) != record["checkpoint_sha256"]:
                        raise ValueError("Checkpoint differs from manifest")
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                    for condition in protocol.conditions:
                        branch = seed_dir / condition.name
                        branch.mkdir()
                        entry = {
                            "seed": seed,
                            "phase": "post",
                            "condition": condition.name,
                            "kind": condition.kind,
                            "cost_drop": condition.cost_drop,
                            "target": record["target"],
                            "checkpoint_sha256": record["checkpoint_sha256"],
                            "synthetic": args.backend == "synthetic",
                            "status": "running",
                        }
                        try:
                            # Rehydrate every branch independently: no deep-copy of live SDK clients.
                            market = make_market(
                                protocol,
                                session,
                                seed,
                                condition.name,
                                checkpoint["state"],
                            )
                            start = snapshot(market)
                            start_hash = state_sha256(start)
                            if start_hash != state_sha256(checkpoint["state"]):
                                raise ValueError(
                                    "Rehydrated agent information/market differs from checkpoint"
                                )
                            dump(branch / "start_state.json", start)
                            treatment = intervene(market, condition, record["target"])
                            after = snapshot(market)
                            # Apart from the target's actual cost, private notice and
                            # forced-policy flag, intervention must change nothing.
                            expected = json.loads(json.dumps(start))
                            expected["agents"][record["target"]].update(
                                valuation=treatment["cost_after"],
                                private_notice=treatment["private_notice"],
                                scripted_policy=treatment["scripted_policy"],
                            )
                            if state_sha256(after) != state_sha256(expected):
                                raise ValueError(
                                    "Intervention changed information outside its declared scope"
                                )
                            dump(
                                branch / "intervention.json",
                                {
                                    **treatment,
                                    "start_state_sha256": start_hash,
                                    "checkpoint_information_identical": True,
                                    "only_declared_fields_changed": True,
                                },
                            )
                            entry["start_state_sha256"] = start_hash
                            run_rounds(
                                market,
                                protocol.post_rounds,
                                protocol,
                                branch / "rounds.jsonl",
                                condition.name,
                                record["target"],
                            )
                            dump(branch / "end_state.json", snapshot(market))
                            entry["status"] = "complete"
                        except Exception as exc:
                            entry.update(
                                status="failed",
                                error_type=type(exc).__name__,
                                failure_reason=safe_failure_reason(exc),
                            )
                            failed = True
                        append(args.out / "manifest.jsonl", entry)
                        print(
                            f"seed {seed}: {condition.name} {entry['status']}",
                            flush=True,
                        )
                        if failed:
                            break
                    if failed:
                        break
        if failed:
            meta["status"] = "failed"
        elif meta["status"] == "running":
            meta["status"] = "complete"
    except BaseException as exc:
        meta.update(
            status="failed",
            error_type=type(exc).__name__,
            failure_reason=safe_failure_reason(exc),
        )
        raise
    finally:
        meta.update(
            finished_at=utc_now(),
            actual_requests=session.calls if session else 0,
            lineage_actual_requests=(session.calls if session else 0)
            + meta["parent_actual_requests"],
        )
        summary = build_final_summary(
            args.out, meta, protocol, session.calls if session else 0
        )
        meta["final_summary"] = summary
        dump(args.out / "final_summary.json", summary)
        dump(args.out / "bundle.json", meta)
        seal(args.out)
        print(
            "FINAL_SUMMARY " + json.dumps(summary, sort_keys=True), flush=True
        )
    return 1 if failed else (2 if meta["status"] == "stopped_positive_control" else 0)


def main():
    args = parser().parse_args()
    try:
        return run(args)
    except (ValueError, RuntimeError, FileExistsError, FileNotFoundError) as exc:
        print(f"Stopped: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
