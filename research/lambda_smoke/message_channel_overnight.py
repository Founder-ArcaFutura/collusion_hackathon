"""Frozen, restartable Modal replication. Planning/status never start compute."""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from research.lambda_smoke import message_channel_probe as probe

ROOT = probe.ROOT
MODULE = "research.lambda_smoke.message_channel_overnight"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    """Flush a complete replacement before atomically publishing a checkpoint."""
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


@contextlib.contextmanager
def lock(root):
    # OS locks release on process death, so restarting needs no stale-lock deletion.
    with (root / "controller.lock").open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def prepare(root, state_limit=40, seeds=(901, 902), max_sessions=8):
    if not 1 <= state_limit <= 100 or not 1 <= len(seeds) <= 20 or len(set(seeds)) != len(seeds):
        raise ValueError("Use 1-100 states and 1-20 unique sampling seeds")
    if not 1 <= max_sessions <= 32:
        raise ValueError("Use 1-32 sessions")
    plan = probe.make_plan()
    states = probe._candidate_states(limit=state_limit, unique_pairs=False)
    for state in states:
        state["conditions"] = probe.build_prompts(state)
    decisions = len(states) * len(seeds) * 10
    plan.update(version="message-channel-modal-replication-v2", states=states,
                seeds=list(seeds), decisions=decisions, selected_state_count=len(states),
                source_market_count=len({s["seed"] for s in states}),
                unique_source_message_count=len({(s["seed"], s["sent_round"], s["sender"]) for s in states}),
                warmup_requests=max_sessions, maximum_requests=decisions + max_sessions,
                maximum_sessions=max_sessions, provider="Modal-hosted", gpu="A10G",
                schema_warmup={"max_tokens": 512, "temperature": 0,
                               "prompt": 'Return exactly this JSON object, without explanation: ' + json.dumps({
                                   "reflection": "", "plan_for_this_hour": "", "ask": 85,
                                   "new_memory": "", "scratch_pad_update": "", "plan_for_message": "",
                                   "message_to_sellers": None})},
                order_rule="Seeded shuffle of state/seed blocks; balanced rotated ten-condition cycles interleaved across blocks.",
                request_cost_note="At most one warmup per session plus one attempt per decision; no automatic retries.",
                selection_rule=plan["selection_rule"].replace("up to ten states", f"up to {state_limit} states"),
                replication_note="Separate provider-labelled replication; repeated draws and shared source messages are not independent markets.")
    plan["selection_rule"] += " Repeated seller pairs across distinct rounds/markets are allowed in v2; exact state identities remain unique."
    probe.validate_plan(plan, max_states=100, max_decisions=20000)
    blocks = [(i, seed) for i in range(len(states)) for seed in seeds]
    random.Random(20261024).shuffle(blocks)
    conditions = list(states[0]["conditions"])
    queue = []
    # Each pass includes all ten treatments with nearly equal frequency, even
    # when a batch ends partway through the queue.
    for turn in range(10):
        for position, (i, seed) in enumerate(blocks):
            condition = conditions[(turn + position) % 10]
            queue.append({"key": f"s{i}-r{seed}-{condition}", "state_index": i,
                          "sampling_seed": seed, "condition": condition})
    envelope = {"plan": plan, "queue": queue}
    root.mkdir(parents=True, exist_ok=False)
    save(root / "manifest.json", {**envelope, "sha256": digest(envelope)})
    save(root / "plan.json", plan)
    (root / "attempts").mkdir()
    (root / "sessions").mkdir()
    # Preserve the runner and validation implementation for later review.
    snapshot = root / "source"
    snapshot.mkdir()
    hashes = {}
    for source in (Path(__file__), Path(probe.__file__),
                   probe.HERE / "message_channel_worker.py",
                   ROOT / "util/poseidon_compute/hosted_model.py",
                   ROOT / "util/poseidon_compute/modal_serve.py",
                   ROOT / "util/poseidon_compute/runtime_metadata.py",
                   ROOT / "research/endogenous_defection/response_schema.py",
                   probe.HERE / "run_message_channel_overnight.ps1"):
        data = source.read_bytes()
        (snapshot / source.name).write_bytes(data)
        hashes[str(source.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    save(root / "source_hashes.json", hashes)
    return status(root)


def load(root):
    manifest = read(root / "manifest.json")
    if digest({k: manifest[k] for k in ("plan", "queue")}) != manifest["sha256"]:
        raise ValueError("Frozen manifest changed")
    if read(root / "plan.json") != manifest["plan"]:
        raise ValueError("Exported plan differs from manifest")
    for relative, expected in read(root / "source_hashes.json").items():
        if probe.sha_file(ROOT / relative) != expected:
            raise ValueError(f"Runner source changed since planning: {relative}; use a new replication directory")
    return manifest


def status(root):
    manifest = load(root)
    queue = manifest["queue"]
    expected = {item["key"]: item for item in queue}
    records = {}
    for path in (root / "attempts").glob("*.json"):
        record = read(path)
        key = record["key"]
        if key not in expected or key in records or record["manifest_sha256"] != manifest["sha256"]:
            raise ValueError("Unknown, duplicate, or mismatched decision checkpoint")
        if record["status"] == "accepted":
            response = root / record["response_path"]
            if probe.sha_file(response) != record["response_sha256"]:
                raise ValueError("Accepted response checksum changed")
        records[key] = record
    blocked = [key for key, row in records.items() if row["status"] != "accepted"]
    sessions = sorted((root / "sessions").glob("session-*"))
    failed_sessions = [p.name for p in sessions if not (p / "host_exit.json").exists()
                       or read(p / "host_exit.json")["exit_code"] != 0]
    return {"complete": len(records) == len(queue) and not blocked and not failed_sessions,
            "planned_decisions": len(queue), "accepted_decisions": len(records) - len(blocked),
            "remaining_decisions": len(queue) - len(records), "blocked_decisions": blocked,
            "failed_or_active_sessions": failed_sessions,
            "sessions_started": len(sessions), "sessions_remaining": manifest["plan"]["maximum_sessions"] - len(sessions),
            "maximum_requests": manifest["plan"]["maximum_requests"],
            "selected_state_count": manifest["plan"]["selected_state_count"],
            "source_market_count": manifest["plan"]["source_market_count"],
            "unique_source_message_count": manifest["plan"]["unique_source_message_count"]}


def export(root, manifest):
    rows = []
    for index, case in enumerate(manifest["queue"], 1):
        path = root / "attempts" / (case["key"] + ".json")
        if path.exists():
            record = read(path)
            if record.get("row"):
                rows.append({"decision_index": index, **record["row"]})
    if rows:
        temp = root / "decisions.csv.tmp"
        with temp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, root / "decisions.csv")
    files = [p for p in root.rglob("*") if p.is_file()
             and p.name not in ("checksums.json", "controller.lock") and not p.name.endswith(".tmp")]
    save(root / "checksums.json", {p.relative_to(root).as_posix(): probe.sha_file(p) for p in files})


def worker(root, session, max_decisions, seconds):
    from research.lambda_smoke import message_channel_worker as w
    manifest = load(root)
    plan = manifest["plan"]
    schema = w.seller_schema(True)
    deadline = time.monotonic() + seconds - 15
    w.PROVIDER = "Modal-hosted"
    phase = "readiness"
    try:
        runtime = w.wait_ready(session, min(deadline, time.monotonic() + 60))
        if runtime != probe.EXPECTED_SOURCE_RUNTIME:
            raise ValueError("Runtime differs from pinned source runtime")
        phase = "schema_warmup"
        warmup_config = plan["schema_warmup"]
        warmup = dict(model=plan["model"], messages=[dict(role="user", content=warmup_config["prompt"])],
                      temperature=warmup_config["temperature"], seed=900,
                      max_tokens=warmup_config["max_tokens"], guided_json=schema)
        response, _ = w.request(warmup, 0, session, min(900, max(1, deadline - time.monotonic())))
        w.ask_value(response, schema)
        phase = "decisions"
        completed = 0
        for item in manifest["queue"]:
            path = root / "attempts" / (item["key"] + ".json")
            if path.exists():
                if read(path)["status"] != "accepted":
                    raise RuntimeError("Unresolved prior attempt; refusing automatic retry")
                continue
            if completed >= max_decisions or deadline - time.monotonic() < 305:
                break
            state = plan["states"][item["state_index"]]
            condition = state["conditions"][item["condition"]]
            record = {**item, "manifest_sha256": manifest["sha256"], "status": "in_flight", "session": session.name}
            save(path, record)  # BEFORE HTTP: an ambiguous interruption never triggers a retry.
            payload = dict(model=plan["model"], messages=[dict(role="user", content=condition["prompt"])],
                           temperature=plan["temperature"], seed=item["sampling_seed"],
                           max_tokens=plan["max_tokens"], guided_json=schema)
            try:
                response, response_path = w.request(payload, completed + 1, session, 300)
                if response.get("model") != plan["model"]:
                    raise ValueError("Response model differs from frozen plan")
                _, ask, withdrawal = w.ask_value(response, schema)
                record.update(status="accepted", response_path=response_path.relative_to(root).as_posix(),
                              response_sha256=probe.sha_file(response_path),
                              row={"state_index": item["state_index"], "seed": state["seed"], "round": state["round"],
                                   "sender": state["sender"], "recipient": state["recipient"],
                                   "sampling_seed": item["sampling_seed"], "visibility": condition["visibility"],
                                   "message_mode": condition["message_mode"], "accepted": True, "ask": ask,
                                   "withdrawal": withdrawal, "finish_reason": "stop"})
            except Exception as exc:
                record.update(status="failed", error_type=type(exc).__name__)
                save(path, record)
                raise
            save(path, record)
            completed += 1
            export(root, manifest)
            print(f"ACCEPTED {item['key']}", flush=True)
        save(session / "worker_exit.json", {"completed": completed})
        return 0 if completed else 2
    except Exception as exc:
        failure = {"error_type": type(exc).__name__, "phase": phase}
        if phase == "schema_warmup" and (session / "responses/000.json").exists():
            response = read(session / "responses/000.json")
            failure["finish_reason"] = response.get("choices", [{}])[0].get("finish_reason")
            failure["completion_tokens"] = response.get("usage", {}).get("completion_tokens")
        save(session / "worker_failure.json", failure)
        print("WORKER_FAILURE " + json.dumps(failure), file=sys.stderr, flush=True)
        return 2
    finally:
        export(root, manifest)


def batch(root, max_decisions=100, seconds=5400):
    if max_decisions <= 0 or not 1200 <= seconds <= 10800:
        raise ValueError("Use positive decision limit and 1200-10800 seconds per session")
    with lock(root):
        current = status(root)
        if current["complete"]:
            return 0
        if current["blocked_decisions"] or current["failed_or_active_sessions"] or current["sessions_remaining"] <= 0:
            raise RuntimeError("Stopped or interrupted attempt/session, or session budget exhausted; inspect evidence before continuing")
        manifest = load(root)
        session = root / "sessions" / f"session-{current['sessions_started'] + 1:03d}"
        session.mkdir()
        save(session / "started.json", {"max_decisions": max_decisions, "max_session_seconds": seconds,
                                       "manifest_sha256": manifest["sha256"]})
        cmd = [sys.executable, "-X", "utf8", "-m", "poseidon_compute.hosted_model",
               "--model", manifest["plan"]["model"], "--gpu", manifest["plan"]["gpu"],
               "--ready-timeout", "600", "--run-timeout", str(seconds), "--",
               sys.executable, "-X", "utf8", "-m", MODULE, "--stage", "worker",
               "--out", str(root), "--session", str(session),
               "--max-decisions", str(max_decisions), "--max-session-seconds", str(seconds)]
        # Synchronous: the host context exits (including app teardown) before returning.
        result = subprocess.run(cmd, cwd=ROOT)
        save(session / "host_exit.json", {"exit_code": result.returncode})
        export(root, manifest)
        return result.returncode


def recover_warmup_only(source, destination):
    """Fork a verified pre-decision warmup failure, preserving its spent budget."""
    from research.lambda_smoke.analyze_message_channel import verify_checksums
    verify_checksums(source)
    previous = read(source / "manifest.json")
    if digest({k: previous[k] for k in ("plan", "queue")}) != previous["sha256"]:
        raise ValueError("Prior manifest changed")
    if list((source / "attempts").iterdir()):
        raise ValueError("Recovery is allowed only before any experimental decision attempt")
    sessions = list((source / "sessions").glob("session-*"))
    if len(sessions) != 1:
        raise ValueError("Expected exactly one failed warmup session")
    session = sessions[0]
    if read(session / "host_exit.json")["exit_code"] != 2:
        raise ValueError("Prior host must have exited with worker failure")
    if sorted(p.name for p in (session / "requests").iterdir()) != ["000.json"]:
        raise ValueError("Prior session contains requests beyond warmup")
    if sorted(p.name for p in (session / "responses").iterdir()) != ["000.json"]:
        raise ValueError("Prior session contains responses beyond warmup")
    request = read(session / "requests/000.json")
    response = read(session / "responses/000.json")
    if request["max_tokens"] != 128 or response["choices"][0]["finish_reason"] != "length":
        raise ValueError("Not the known truncated 128-token warmup failure")
    old_plan = previous["plan"]
    if old_plan["maximum_sessions"] <= 1:
        raise ValueError("No session budget remains")
    prepare(destination, state_limit=len(old_plan["states"]), seeds=tuple(old_plan["seeds"]),
            max_sessions=old_plan["maximum_sessions"] - 1)
    updated = load(destination)
    if (updated["queue"] != previous["queue"] or any(updated["plan"][key] != old_plan[key]
            for key in ("states", "seeds", "model", "temperature", "max_tokens", "serving_stack"))):
        raise ValueError("Recovery changed experimental decisions; do not launch this directory")
    save(destination / "recovery.json", {"previous_run": str(source),
         "previous_manifest_sha256": previous["sha256"],
         "previous_checksums_sha256": probe.sha_file(source / "checksums.json"),
         "reason": "128-token schema warmup truncated; zero experimental attempts",
         "previous_requests_spent": 1, "previous_sessions_spent": 1,
         "total_request_ceiling_including_previous_run": old_plan["maximum_requests"]})
    if (source / "controller.json").exists():
        (destination / "controller.json").write_bytes((source / "controller.json").read_bytes())
    export(destination, updated)
    return status(destination)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", choices=("plan", "status", "batch", "worker", "recover-warmup"), required=True)
    p.add_argument("--from-run", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--state-limit", type=int, default=40)
    p.add_argument("--seeds", type=int, nargs="+", default=[901, 902])
    p.add_argument("--max-sessions", type=int, default=8)
    p.add_argument("--max-decisions", type=int, default=100)
    p.add_argument("--max-session-seconds", type=int, default=5400)
    p.add_argument("--session", type=Path)
    args = p.parse_args()
    root = args.out.resolve()
    if args.stage == "plan":
        print(json.dumps(prepare(root, args.state_limit, args.seeds, args.max_sessions), indent=2))
    elif args.stage == "recover-warmup":
        if args.from_run is None:
            p.error("recover-warmup requires --from-run")
        print(json.dumps(recover_warmup_only(args.from_run.resolve(), root), indent=2))
    elif args.stage == "status":
        print(json.dumps(status(root)))
    elif args.stage == "batch":
        return batch(root, args.max_decisions, args.max_session_seconds)
    else:
        return worker(root, args.session.resolve(), args.max_decisions, args.max_session_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
