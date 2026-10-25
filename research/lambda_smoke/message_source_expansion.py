"""Generate new independent source markets, audit them, then freeze a v3 probe."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import time

from research.lambda_smoke import message_channel_overnight as io
from research.lambda_smoke import message_channel_probe as p
from research.lambda_smoke import message_channel_v3 as audit_rules
from research.lambda_smoke.analyze_message_channel import write_csv, verify_checksums
from research.endogenous_defection.config import Protocol

ROOT = p.ROOT
MODULE = "research.lambda_smoke.message_source_expansion"
RESOURCE_SECONDS = 4660
RATE = 0.000306 + 4 * 0.0000131 + 32 * 0.00000222
RESERVATION = RESOURCE_SECONDS * RATE * 1.2
HOST = ROOT / "util/poseidon_compute/message_source_host.py"


def seal(root):
    io.save(root / "checksums.json", {f.relative_to(root).as_posix(): p.sha_file(f)
        for f in root.rglob("*") if f.is_file() and f.name not in ("checksums.json", "controller.lock")
        and not f.name.endswith(".tmp")})


def code_paths():
    from research.endogenous_defection.io import provenance
    paths = [ROOT / path for path in provenance()["source_sha256"] if path.endswith((".py", ".jinja2"))]
    paths += [Path(__file__), Path(io.__file__), Path(p.__file__), Path(audit_rules.__file__),
              p.HERE / "message_channel_worker.py", p.HERE / "run_message_source_expansion.ps1", HOST]
    return sorted(set(paths))


def snapshot(root):
    files = code_paths()
    hashes = {}
    for path in files:
        relative = path.relative_to(ROOT)
        dest = root / "source" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        hashes[relative.as_posix()] = p.sha_file(path)
    io.save(root / "source_hashes.json", hashes)


def load(root):
    manifest = io.read(root / "acquisition_plan.json")
    content = {k: v for k, v in manifest.items() if k != "sha256"}
    if io.digest(content) != manifest["sha256"]:
        raise ValueError("Source acquisition plan changed")
    for relative, digest in io.read(root / "source_hashes.json").items():
        if p.sha_file(ROOT / relative) != digest:
            raise ValueError(f"Executable source changed since preparation: {relative}")
    for job in manifest["jobs"]:
        if io.read(root / "configs" / (job["id"] + ".json")) != job["protocol"]:
            raise ValueError("Source market config differs from frozen plan")
    for relative, digest in manifest["original_source_seals"].items():
        if p.sha_file(ROOT / relative) != digest:
            raise ValueError("Original source seal changed")
    return manifest


def prepare(root, backend="live", balance=67.10):
    bundles = p._bundle_index()
    if len(bundles) != 4:
        raise ValueError("Expected original four source markets")
    for bundle in bundles.values():
        p.verify(bundle)
    template = io.read(bundles["seed_20_partial_on"] / "protocol.json")
    jobs = []
    for seed in (40, 41, 42, 43):
        config = {**template, "seeds": [seed]}
        protocol = Protocol.model_validate(config)
        jobs.append({"id": f"seed_{seed}_partial_on", "seed": seed, "protocol": config,
                     "market_decisions": protocol.warmup_rounds * (len(protocol.seller_costs)+len(protocol.buyer_values)),
                     "maximum_market_requests": protocol.call_estimate()["control"]})
    plan = {"version": "message-source-acquisition-v3-v1", "backend": backend, "model": p.MODEL,
        "jobs": jobs, "new_markets": 4, "market_seeds": [j["seed"] for j in jobs],
        "rounds_per_market": 10, "agents_per_market": 10, "market_decisions": sum(j["market_decisions"] for j in jobs),
        "maximum_requests": sum(j["maximum_market_requests"]+2 for j in jobs),
        "maximum_sessions": 4, "warmups_per_session": 2, "warmup_max_tokens": 512,
        "request_timeout_seconds": 300, "worker_seconds": 4000, "container_seconds": RESOURCE_SECONDS,
        "balance_user_reported_usd": balance, "balance_independently_verified": False,
        "source_phase_budget_usd": 10, "probe_phase_budget_usd": 10,
        "total_phase_allocations_usd": 20,
        "resource_rate_upper_estimate_usd_per_hour": RATE*3600,
        "source_phase_full_reservation_usd": RESERVATION*4,
        "budget_note": "Resource/time reservation at public rates plus 20% reserve; CPU capped at 4 cores, memory 32 GiB, one A10G. Excludes taxes, storage, egress and other workspace activity; not a provider invoice cap.",
        "pricing_url": "https://modal.com/pricing", "pricing_checked_local_date": "2026-10-24",
        "protocol_note": "Exact original seed-20 partial/on protocol, changing only market seed. Its at-most-two format attempts remain; transport retries disabled. No factual messages are scripted or forced.",
        "target_probe": {"minimum_states": 20, "maximum_states": 30, "minimum_messages": 8,
                         "minimum_markets": 4, "sampling_seeds": [1001,1002,1003], "maximum_decisions": 900},
        "original_source_seals": {(b / "checksums.json").relative_to(ROOT).as_posix(): p.sha_file(b / "checksums.json") for b in bundles.values()},
        "after_sources": "Audit sealed evidence, freeze/display actual v3 plan, stop for separate probe command. No eligibility relaxation or automatic additional source markets."}
    if balance < plan["total_phase_allocations_usd"] or RESERVATION*4 > 10:
        raise ValueError("Reported balance or source-phase budget cannot cover the proposed reservations")
    root.mkdir(parents=True, exist_ok=False)
    (root / "configs").mkdir()
    (root / "sessions").mkdir()
    (root / "cells").mkdir()
    for job in jobs:
        io.save(root / "configs" / (job["id"] + ".json"), job["protocol"])
    io.save(root / "acquisition_plan.json", {**plan, "sha256": io.digest(plan)})
    snapshot(root)
    seal(root)
    print(json.dumps({k:v for k,v in plan.items() if k != "jobs"}, indent=2), flush=True)
    return plan


def phase_status(root, phase):
    plan = load(root)
    folder = root if phase == "sources" else root / "probe"
    if not folder.exists():
        return {"complete": False, "ready": False, "phase": phase, "reason": "Run source markets and audit first"}
    budget = plan["source_phase_budget_usd"] if phase == "sources" else plan["probe_phase_budget_usd"]
    sessions = sorted((folder / "sessions").glob("seed_*" if phase == "sources" else "session-*"))
    spent, failed = 0.0, []
    for session in sessions:
        if not (session / "host_exit.json").exists():
            failed.append(session.name)
            spent += RESERVATION
        else:
            result = io.read(session / "host_exit.json")
            spent += result["charged_reservation_usd"]
            if result["exit_code"] != 0:
                failed.append(session.name)
    if phase == "sources":
        complete_jobs = []
        for job in plan["jobs"]:
            bundle = root / "cells" / job["id"]
            if bundle.exists():
                if not (bundle / "checksums.json").exists():
                    failed.append(job["id"])
                    continue
                p.verify(bundle)
                meta = io.read(bundle / "bundle.json")
                if meta["status"] != "complete" or meta["backend"] != plan["backend"]:
                    failed.append(job["id"])
                elif plan["backend"] == "live" and meta["model"] != p.MODEL:
                    failed.append(job["id"]+":model_mismatch")
                else:
                    complete_jobs.append(job["id"])
                    if plan["backend"] == "live" and not (root / "sessions" / job["id"] / "host_exit.json").exists():
                        failed.append(job["id"]+":missing_host_exit")
        complete = len(complete_jobs) == len(plan["jobs"]) and not failed
        pending = len(plan["jobs"]) - len(complete_jobs)
        maximum_sessions = len(plan["jobs"])
    else:
        state = io.status(folder)
        failed += state["blocked_decisions"]
        complete = state["complete"]
        pending = state["remaining_decisions"]
        maximum_sessions = io.read(folder / "plan.json")["maximum_sessions"]
    return {"phase": phase, "ready": phase == "sources" or io.read(folder / "plan.json")["execution_enabled"],
            "complete": complete, "remaining": pending, "failed_or_active": failed,
            "sessions_started": len(sessions), "sessions_remaining": maximum_sessions-len(sessions),
            "resource_budget_usd": budget, "charged_time_reservations_usd": spent,
            "next_session_reservation_usd": RESERVATION, "budget_remaining_usd": budget-spent}


def warm_schemas(root, protocol):
    from research.endogenous_defection.response_schema import schema_for
    from jsonschema import validate
    from research.lambda_smoke import message_channel_worker as w
    warm = root / "warmup"
    warm.mkdir()
    for index, role in enumerate(("buyer", "seller")):
        schema = schema_for(role, protocol)
        action = {name: (None if name.startswith("message_to_") else "") for name in schema["required"]}
        action["bid" if role == "buyer" else "ask"] = 85
        payload = {"model": p.MODEL, "messages": [{"role": "user", "content": "Return exactly this JSON object: "+json.dumps(action)}],
                   "temperature": 0, "seed": 900+index, "max_tokens": 512, "guided_json": schema}
        response, _ = w.request(payload, index, warm, 900)
        if response.get("model") != p.MODEL or response["choices"][0]["finish_reason"] != "stop":
            raise ValueError("Incomplete or wrong-model source schema warmup")
        validate(json.loads(response["choices"][0]["message"]["content"]), schema)


def source_worker(root, job_id, backend):
    from research.endogenous_defection import auction
    from research.endogenous_defection.run_experiment import run
    from research.endogenous_defection.observations import ObservationMarket
    from research.endogenous_defection.io import dump
    plan = load(root)
    job = next(j for j in plan["jobs"] if j["id"] == job_id)
    bundle = root / "cells" / job_id
    protocol = Protocol.model_validate(job["protocol"])
    if backend != plan["backend"]:
        raise ValueError("Backend differs from immutable acquisition plan")
    if backend == "live":
        from poseidon_compute.runtime_metadata import validate_serving_runtime
        runtime = validate_serving_runtime(json.loads(os.environ["MODAL_SERVING_RUNTIME"]))
        if runtime != p.EXPECTED_SOURCE_RUNTIME or os.environ.get("LLM_MODEL") != p.MODEL:
            raise ValueError("Source runtime/model changed")
        warm_schemas(root / "sessions" / job_id, protocol)
    auction.INFERENCE_REQUEST_TIMEOUT_SECONDS = 300

    def factory(config, session, seed, condition="warmup", state=None):
        market = auction.make_market(config, session, seed, condition, state, market_class=ObservationMarket)
        market.visibility_mode = "partial"
        market.observation_seed = seed
        market.observation_path = bundle / "observations.jsonl"
        dump(bundle / "observation_spec.json", {"mode": "partial", "current_and_historical_quotes": True,
            "own_information_preserved": True, "buyers_unchanged": True,
            "realized_trades_preserved": True, "messages_may_relay_hidden_information": True})
        return market

    args = argparse.Namespace(config=root / "configs" / (job_id+".json"), stage="control", backend=backend,
         model=p.MODEL if backend == "live" else None, out=bundle, from_control=None,
         max_calls=job["maximum_market_requests"])
    return run(args, market_factory=factory)


def execute_host(root, phase, session, command):
    started = time.monotonic()
    env = dict(os.environ, MODAL_SERVE_MODEL=p.MODEL, MODAL_SERVE_GPU="A10G", MODAL_MAX_NUM_SEQS="1", MODAL_MAX_MODEL_LEN="8192")
    host_command = [sys.executable, "-X", "utf8", "-m", "poseidon_compute.message_source_host", "--", *command]
    io.save(session / "started.json", {"phase": phase, "resource_reservation_usd": RESERVATION,
                                     "maximum_seconds": RESOURCE_SECONDS})
    code = 2
    with (session / "host.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(host_command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        # A separate watchdog includes pre-readiness app creation and SDK connection.
        import threading
        expired = threading.Event()
        def stop_host():
            expired.set()
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            except OSError:
                return
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
        timer = threading.Timer(RESOURCE_SECONDS, stop_host)
        timer.daemon = True
        timer.start()
        try:
            for line in process.stdout:
                log.write(line); log.flush(); print(line, end="", flush=True)
            code = process.wait()
            if expired.is_set():
                code = 124
        except BaseException:
            stop_host()
            raise
        finally:
            timer.cancel()
            elapsed = time.monotonic()-started
            # Retain full reservation on any failure: do not silently refund uncertain remote time.
            charged = min(RESERVATION, elapsed*RATE*1.2) if code == 0 else RESERVATION
            io.save(session / "host_exit.json", {"exit_code": code, "elapsed_seconds": elapsed,
                                                 "charged_reservation_usd": charged})
    return code


def batch(root, phase="sources"):
    plan = load(root)
    if plan["backend"] != "live":
        raise RuntimeError("Use synthetic worker validation directly; paid host requires live plan")
    folder = root if phase == "sources" else root / "probe"
    with io.lock(folder):
        state = phase_status(root, phase)
        print(json.dumps(state, indent=2), flush=True)
        if state["complete"]:
            return 0
        if not state["ready"] or state["failed_or_active"] or state["sessions_remaining"] <= 0:
            raise RuntimeError("Phase not ready, previous failure/interruption, or session budget exhausted")
        if state["budget_remaining_usd"] < RESERVATION:
            raise RuntimeError("Insufficient resource budget for one more full bounded session")
        if phase == "sources":
            job = next(j for j in plan["jobs"] if not (root / "cells" / j["id"]).exists())
            session = folder / "sessions" / job["id"]
            # Source sessions use IDs shared with their immutable market keys.
            session.mkdir()
            command = [sys.executable, "-X", "utf8", "-m", MODULE, "--stage", "worker", "--out", str(root),
                       "--job", job["id"], "--backend", plan["backend"]]
        else:
            session = folder / "sessions" / f"session-{state['sessions_started']+1:03d}"
            session.mkdir()
            command = [sys.executable, "-X", "utf8", "-m", "research.lambda_smoke.message_channel_overnight",
                       "--stage", "worker", "--out", str(folder), "--session", str(session),
                       "--max-decisions", "100", "--max-session-seconds", "4000"]
        code = execute_host(root, phase, session, command)
        if phase == "probe":
            io.export(folder, io.load(folder))
        seal(root)
        return code


def collect_candidates(bundles):
    """Audit raw source messages with the unchanged frozen selection predicate."""
    states, audit, inventory = [], [], []
    seen = set()
    for bundle in bundles:
        p.verify(bundle)
        meta = io.read(bundle / "bundle.json")
        if meta["status"] != "complete" or meta["backend"] != "live" or meta["model"] != p.MODEL:
            raise ValueError("Only complete live pinned-model sources may enter the v3 plan")
        if meta["modal_serving_runtime"] != p.EXPECTED_SOURCE_RUNTIME:
            raise ValueError("Source runtime differs from fixed contract")
        seed = io.read(bundle / "protocol.json")["seeds"][0]
        rounds = p._market_rounds(bundle, seed)
        prompts = p._response_prompts(bundle)
        obs = {(o["round"], o["observer"]): o for o in p.load_jsonl(bundle / "observations.jsonl") if o["role"] == "seller"}
        recipients = sorted({name for _, name in obs})
        count_before = len(states)
        for sent, record in sorted(rounds.items()):
            if sent+1 not in rounds:
                continue
            for sender, message in sorted(record["market"]["seller_messages"].items()):
                if not isinstance(message, str) or not message:
                    continue
                for recipient in recipients:
                    if recipient == sender:
                        continue
                    key = (seed, sent+1, sender, recipient)
                    if key in seen:
                        raise ValueError("Duplicate source-state identity across supplied bundles")
                    seen.add(key)
                    observation = obs.get((sent+1, recipient))
                    event = prompts.get((seed, sent+1, recipient))
                    prompt = event["prompt"] if event else None
                    ask = record["market"]["seller_asks"].get(sender)
                    state = dict(seed=seed, cell="partial_on", round=sent+1, sent_round=sent,
                        sender=sender, recipient=recipient, message=message, message_line=f"- From {sender}: {message}")
                    reason = audit_rules.assess(state, observation, prompt, ask)
                    audit.append({"market_seed": seed, "sent_round": sent, "received_round": sent+1,
                                  "sender": sender, "recipient": recipient, "message": message,
                                  "actual_submitted_ask": ask, "first_exclusion": reason})
                    if reason != "eligible":
                        continue
                    historical = p._historical_quote_line(observation["true_observation"]["past_bids_and_asks"], sent, sender, ask)
                    state.update(quote_owner=sender, quote_price=float(ask), quote_current_at_decision=True,
                        quote_historical_at_decision=bool(historical), historical_quote_line=historical,
                        prompt=prompt, prompt_sha256=p.sha_bytes(prompt.encode("utf-8")),
                        source_bundle=bundle.relative_to(ROOT).as_posix(),
                        source_cell_seal_sha256=p.sha_file(bundle / "checksums.json"),
                        source_event_call=event.get("call"), source_event_schema_version=event.get("schema_version"),
                        source_observation=observation, selection_reason="Unchanged strict factual-price/visibility/delivery criteria over newly acquired and original source markets, rounds 2–6.")
                    state["conditions"] = p.build_prompts(state)
                    if state["conditions"]["hidden_original"]["prompt"].encode() != prompt.encode():
                        raise ValueError("Original hidden prompt changed")
                    states.append(state)
        inventory.append({"market_seed": seed, "bundle": bundle.relative_to(ROOT).as_posix(),
                          "seal_sha256": p.sha_file(bundle / "checksums.json"), "eligible_states": len(states)-count_before})
    return states, audit, inventory


def select_diverse(states, limit=30):
    groups = {seed: sorted([s for s in states if s["seed"] == seed],
                           key=lambda s: (s["round"], s["sender"], s["recipient"])) for seed in sorted({s["seed"] for s in states})}
    selected, messages = [], set()
    while any(groups.values()) and len(selected) < limit:
        for seed, candidates in groups.items():
            if not candidates or len(selected) >= limit:
                continue
            index = next((i for i, s in enumerate(candidates) if (seed,s["sent_round"],s["sender"]) not in messages), 0)
            state = candidates.pop(index)
            messages.add((seed,state["sent_round"],state["sender"]))
            selected.append(state)
    return selected


def validate_probe(plan):
    """Validate new price formats without changing the frozen v2 validator."""
    identities = {(s["seed"],s["round"],s["sender"],s["recipient"]) for s in plan["states"]}
    if len(identities) != len(plan["states"]) or not 1 <= len(identities) <= 30:
        raise ValueError("Probe states must be distinct and capped at thirty")
    if plan["decisions"] != len(identities)*len(plan["seeds"])*10 or plan["decisions"] > 900:
        raise ValueError("Probe factorial count mismatch")
    if plan["maximum_requests"] != plan["decisions"]+plan["warmup_requests"]:
        raise ValueError("Warmup request accounting mismatch")
    for state in plan["states"]:
        if audit_rules.assess(state,state["source_observation"],state["prompt"],state["quote_price"]) != "eligible":
            raise ValueError("Frozen source state no longer satisfies eligibility")
        expected = p.build_prompts(state)
        if state["conditions"] != expected:
            raise ValueError("Frozen transformations differ from the exact source edits")
        if state["conditions"]["hidden_original"]["prompt"].encode() != state["prompt"].encode():
            raise ValueError("Original source prompt changed")
        for key,condition in state["conditions"].items():
            if condition["prompt_sha256"] != p.sha_bytes(condition["prompt"].encode()):
                raise ValueError("Prompt hash mismatch")
            queue = __import__("ast").literal_eval(p.ASK_QUEUE.search(condition["prompt"]).group(2))
            visible = any(q[1] == state["sender"] and p.money_equal(q[0],state["quote_price"]) for q in queue)
            if visible != (condition["visibility"] == "restored"):
                raise ValueError("Restored/hidden current quote invariant failed")
            if state["historical_quote_line"]:
                visible_history = state["historical_quote_line"] in p.HISTORY.search(condition["prompt"]).group(2)
                if visible_history != (condition["visibility"] == "restored"):
                    raise ValueError("Restored/hidden historical quote invariant failed")
            mode = condition["message_mode"]
            if mode in ("up10","down10"):
                # PRICE substitution preserves the source's decimal precision:
                # $84, $84.0 and $84.00 are all valid original price formats.
                message = state["message"]
                token = p.PRICE.search(message)
                shift = 10 if mode == "up10" else -10
                decimals = len(token.group("amount").split(".")[1]) if "." in token.group("amount") else 0
                target = p.PRICE.sub(f"${state['quote_price']+shift:.{decimals}f}",message,count=1)
                if f"- From {state['sender']}: {target}" not in condition["prompt"]:
                    raise ValueError("Fabricated report has incorrect price")
    return True


def freeze_probe(root):
    acquisition = load(root)
    if not phase_status(root, "sources")["complete"]:
        raise RuntimeError("Finish all four source markets before freezing the probe")
    if acquisition["backend"] != "live":
        raise ValueError("Synthetic validation cannot supply research states")
    folder = root / "probe"
    if folder.exists():
        return io.read(folder / "selection_summary.json")
    bundles = list(p._bundle_index().values()) + [root / "cells" / j["id"] for j in acquisition["jobs"]]
    candidates, audit_rows, inventory = collect_candidates(bundles)
    states = select_diverse(candidates)
    target = acquisition["target_probe"]
    diversity = {"states": len(states), "markets": len({s["seed"] for s in states}),
                 "messages": len({(s["seed"],s["sent_round"],s["sender"]) for s in states}),
                 "new_source_states": sum(s["seed"] in acquisition["market_seeds"] for s in states)}
    ready = diversity["states"] >= target["minimum_states"] and diversity["markets"] >= target["minimum_markets"] and diversity["messages"] >= target["minimum_messages"]
    plan = p.make_plan()
    seeds = target["sampling_seeds"]
    decisions = len(states)*len(seeds)*10
    sessions = math.ceil(decisions/100)
    minimal = {"reflection":"", "plan_for_this_hour":"", "ask":85, "new_memory":"",
               "scratch_pad_update":"", "plan_for_message":"", "message_to_sellers":None}
    plan.update(version="message-channel-v3-expanded-sources-v1", states=states, seeds=seeds,
        decisions=decisions, selected_state_count=len(states), source_market_count=diversity["markets"],
        unique_source_message_count=diversity["messages"], warmup_requests=sessions,
        maximum_requests=decisions+sessions, maximum_sessions=sessions, provider="Modal-hosted", gpu="A10G",
        execution_enabled=ready, acquisition_plan_sha256=acquisition["sha256"],
        schema_warmup={"max_tokens":512,"temperature":0,"prompt":"Return exactly this JSON object: "+json.dumps(minimal)},
        selection_rule="Unchanged v2 factuality, masking and rounds-2–6 checks; raw-source audit; rotate across markets and prefer unused factual messages; cap at 30 states.",
        order_rule="Seeded shuffled state/seed blocks with rotating treatment passes.",
        request_cost_note="At most one warmup per session; no retry of experimental decision keys.",
        replication_note="Expanded-source decision probe. Repeated recipients/messages/markets remain correlated; existing evidence is not pooled into outcomes.")
    validate_probe(plan)
    blocks = [(i,s) for i in range(len(states)) for s in seeds]
    random.Random(20261025).shuffle(blocks)
    conditions = list(states[0]["conditions"])
    queue = [{"key":f"s{i}-r{seed}-{conditions[(turn+pos)%10]}", "state_index":i,
              "sampling_seed":seed,"condition":conditions[(turn+pos)%10]}
             for turn in range(10) for pos,(i,seed) in enumerate(blocks)]
    summary = {"status":"READY_FOR_SEPARATE_PROBE_COMMAND" if ready else "HELD_INSUFFICIENT_DIVERSITY",
        **diversity, "audited_markets":len(inventory), "decisions":decisions,"sessions":sessions,
        "maximum_requests":decisions+sessions,"sampling_seeds":seeds,"resource_budget_usd":10,
        "minimum_required":target,"interpretation":"Actual eligibility controls admission; new-market generation does not guarantee the target."}
    folder.mkdir()
    (folder/"attempts").mkdir()
    (folder/"sessions").mkdir()
    io.save(folder/"plan.json", plan)
    envelope = {"plan":plan,"queue":queue}
    io.save(folder/"manifest.json", {**envelope,"sha256":io.digest(envelope)})
    io.save(folder/"selection_summary.json",summary)
    io.save(folder/"source_inventory.json",inventory)
    write_csv(folder/"selection_audit.csv",audit_rows)
    snapshot(folder)
    io.export(folder,envelope)
    seal(root)
    print(json.dumps(summary,indent=2),flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "status", "batch", "worker", "audit"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--phase", choices=("sources", "probe"), default="sources")
    parser.add_argument("--backend", choices=("live", "synthetic"), default="live")
    parser.add_argument("--job")
    args = parser.parse_args()
    root = args.out.resolve()
    if args.stage == "plan":
        prepare(root, args.backend)
    elif args.stage == "status":
        print(json.dumps(phase_status(root, args.phase), indent=2))
    elif args.stage == "batch":
        return batch(root, args.phase)
    elif args.stage == "worker":
        return source_worker(root, args.job, args.backend)
    else:
        freeze_probe(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
