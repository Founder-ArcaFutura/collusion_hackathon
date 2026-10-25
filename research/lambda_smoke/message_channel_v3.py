"""Offline source-diversity audit and separately versioned message probe plan."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
import math
from pathlib import Path
import random
import shutil
from statistics import mean

from research.lambda_smoke import message_channel_probe as p
from research.lambda_smoke import message_channel_overnight as runner
from research.lambda_smoke.analyze_message_channel import write_csv


def assess(state, obs, prompt, actual_ask):
    """The v1/v2 factuality, timing, masking and single-target rules, unchanged."""
    text = state["message"]
    if state["round"] > 6:
        return "outside_frozen_rounds_2_to_6"
    claims = list(p.SELF_ASK.finditer(text))
    numbers = list(p.PRICE.finditer(text))
    if len(claims) != 1:
        return "not_exactly_one_explicit_self_ask_assertion"
    claim = next((x for x in claims[0].groups() if x is not None), None)
    if len(numbers) != 1:
        return "not_exactly_one_price_token"
    if actual_ask is None or not p.money_equal(claim, actual_ask) or not p.money_equal(numbers[0].group("amount"), actual_ask):
        return "report_does_not_match_submitted_ask"
    if obs is None:
        return "recipient_observation_missing"
    owner, price, sent = state["sender"], float(actual_ask), state["sent_round"]
    if not any(q[1] == owner and p.money_equal(q[0], price) for q in obs["true_observation"]["ask_queue"]):
        return "reported_order_no_longer_standing"
    for key, label in (("current_quote_masks", "current_quote_not_hidden"),
                       ("historical_quote_masks", "historical_quote_not_hidden")):
        mask = p._mask_row(obs, owner, price, sent, key)
        if not mask or mask.get("visible") is not False:
            return label
    if prompt is None:
        return "source_prompt_missing"
    line = state["message_line"]
    if prompt.count(line) != 1:
        return "message_not_received_exactly_once"
    if not p.ASK_QUEUE.search(prompt) or not p.HISTORY.search(prompt):
        return "source_display_structure_missing"
    rest = prompt.replace(line, "", 1)
    if p._owner_price_assertion_exists(rest, owner, price):
        return "fact_asserted_elsewhere_in_prompt"
    if any(p._owner_price_assertion_exists(rest, owner, price + delta) for delta in (-10, 10)):
        return "distortion_asserted_elsewhere_in_prompt"
    queue = ast.literal_eval(p.ASK_QUEUE.search(prompt).group(2))
    if any(q[1] == owner and p.money_equal(q[0], price) for q in queue):
        return "true_quote_exposed_in_rendered_current_queue"
    hist = p._historical_quote_line(obs["true_observation"].get("past_bids_and_asks", ""), sent, owner, price)
    if hist and hist in p.HISTORY.search(prompt).group(2):
        return "true_quote_exposed_in_rendered_history"
    return "eligible"


def audit_sources():
    bundles = p._bundle_index()
    expected = {f"seed_{seed}_partial_on" for seed in range(20, 24)}
    if set(bundles) != expected:
        raise ValueError("All four completed seed-20–23 partial/on bundles are required")
    inventory, audit, states = [], [], []
    seen = set()
    for name, bundle in sorted(bundles.items()):
        p.verify(bundle)
        meta = runner.read(bundle / "bundle.json")
        if (meta.get("status") != "complete" or meta.get("backend") != "live"
                or meta.get("model") != p.MODEL or meta.get("modal_serving_runtime") != p.EXPECTED_SOURCE_RUNTIME):
            raise ValueError(f"Source contract mismatch: {bundle}")
        seed = int(name.split("_")[1])
        rounds = p._market_rounds(bundle, seed)
        prompts = p._response_prompts(bundle)
        observations = {(int(o["round"]), o["observer"]): o
                        for o in p.load_jsonl(bundle / "observations.jsonl") if o["role"] == "seller"}
        recipients = sorted({recipient for _, recipient in observations})
        start = len(audit)
        for sent_round, record in sorted(rounds.items()):
            for sender, text in sorted(record["market"].get("seller_messages", {}).items()):
                if not isinstance(text, str) or not text:
                    continue
                for recipient in recipients:
                    if recipient == sender:
                        continue
                    receive_round = sent_round + 1
                    if receive_round not in rounds:
                        continue  # final-hour messages have no recipient decision
                    key = (seed, receive_round, sender, recipient)
                    if key in seen:
                        raise ValueError("Duplicate raw candidate state")
                    seen.add(key)
                    event = prompts.get((seed, receive_round, recipient))
                    prompt = event.get("prompt") if event else None
                    obs = observations.get((receive_round, recipient))
                    ask = record["market"].get("seller_asks", {}).get(sender)
                    state = dict(seed=seed, cell="partial_on", round=receive_round, sent_round=sent_round,
                                 sender=sender, recipient=recipient, message=text,
                                 message_line=f"- From {sender}: {text}")
                    reason = assess(state, obs, prompt, ask)
                    # Diagnostic only: changing the hour cutoff would be a
                    # protocol amendment, so these cases are never admitted.
                    other_rules = assess({**state, "round": 6}, obs, prompt, ask) if receive_round > 6 else reason
                    audit.append({**{k: state[k] for k in ("seed", "sent_round", "round", "sender", "recipient")},
                                  "submitted_ask": ask, "message": text, "eligible": reason == "eligible", "first_exclusion": reason,
                                  "late_round_other_rules_result": other_rules if receive_round > 6 else "not_applicable"})
                    if reason != "eligible":
                        continue
                    hist = p._historical_quote_line(obs["true_observation"]["past_bids_and_asks"], sent_round, sender, ask)
                    state.update(quote_owner=sender, quote_price=float(ask),
                                 quote_current_at_decision=True, quote_historical_at_decision=bool(hist),
                                 historical_quote_line=hist, prompt=prompt,
                                 prompt_sha256=p.sha_bytes(prompt.encode("utf-8")),
                                 source_bundle=bundle.relative_to(p.ROOT).as_posix(),
                                 source_cell_seal_sha256=p.sha_file(bundle / "checksums.json"),
                                 source_event_call=event.get("call"),
                                 source_event_schema_version=event.get("schema_version"), source_observation=obs,
                                 selection_reason="Direct raw-source reconstruction; unchanged v2 eligibility, rounds 2–6; accurate self-ask, hidden current/historical displays, exact next-hour delivery, no duplicate true or fabricated claim elsewhere.")
                    state["conditions"] = p.build_prompts(state)
                    states.append(state)
        group = audit[start:]
        inventory.append({"market_seed": seed, "bundle": bundle.relative_to(p.ROOT).as_posix(),
                          "seal_sha256": p.sha_file(bundle / "checksums.json"),
                          "candidate_state_rows": len(group), "eligible_states": sum(r["eligible"] for r in group),
                          "first_exclusion_counts": dict(Counter(r["first_exclusion"] for r in group))})
    # Prefer new messages before additional recipients of an existing message;
    # rotate through markets, keeping selection independent of inference outcomes.
    states.sort(key=lambda s: (s["round"], s["sender"], s["recipient"]))
    remaining = {seed: [s for s in states if s["seed"] == seed] for seed in range(20, 24)}
    ordered, messages = [], set()
    while any(remaining.values()):
        for seed, items in remaining.items():
            if not items:
                continue
            index = next((i for i, s in enumerate(items) if (seed, s["sent_round"], s["sender"]) not in messages), 0)
            state = items.pop(index)
            messages.add((seed, state["sent_round"], state["sender"]))
            ordered.append(state)
    return {"inventory": inventory, "audit_rows": audit, "states": ordered}


def audit(out):
    result = audit_sources()
    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "selection_audit.csv", result["audit_rows"])
    runner.save(out / "source_inventory.json", result["inventory"])
    runner.save(out / "eligible_states.json", result["states"])
    summary = {"audited_markets": len(result["inventory"]), "candidate_rows": len(result["audit_rows"]),
               "eligible_states": len(result["states"]),
               "eligible_markets": len({s["seed"] for s in result["states"]}),
               "eligible_messages": len({(s["seed"], s["sent_round"], s["sender"]) for s in result["states"]}),
               "otherwise_clean_late_round_states_not_admitted": sum(r["first_exclusion"] == "outside_frozen_rounds_2_to_6"
                       and r["late_round_other_rules_result"] == "eligible" for r in result["audit_rows"]),
               "policy": "Unchanged v2 eligibility; no numeric target padding; direct raw-source search across all four markets.",
               "per_market": result["inventory"]}
    runner.save(out / "audit_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return result


def prepare(out, balance=67.10, allocation=10.00, target=30):
    """Freeze an honest held proposal when source diversity cannot be expanded."""
    if not 20 <= target <= 30 or not 0 < allocation <= balance:
        raise ValueError("Target 20-30 states and allocate a positive amount within the reported balance")
    source = audit_sources()
    states = source["states"][:target]
    seeds = [1001, 1002, 1003]  # fresh draws; never relabel v2's 901/902 as new
    decisions = len(states) * len(seeds) * 10
    sessions = math.ceil(decisions / 100)
    plan = p.make_plan()
    # Preserve the corrected warmup contract without mutating the v2 runner.
    minimal = {"reflection": "", "plan_for_this_hour": "", "ask": 85, "new_memory": "",
               "scratch_pad_update": "", "plan_for_message": "", "message_to_sellers": None}
    plan.update(version="message-channel-v3-diversity-audit-held-v1", states=states, seeds=seeds,
        decisions=decisions, selected_state_count=len(states),
        source_market_count=len({s["seed"] for s in states}),
        unique_source_message_count=len({(s["seed"], s["sent_round"], s["sender"]) for s in states}),
        provider="Modal-hosted", gpu="A10G", warmup_requests=sessions,
        maximum_sessions=sessions, maximum_requests=decisions + sessions,
        schema_warmup={"max_tokens": 512, "temperature": 0,
                       "prompt": "Return exactly this JSON object, without explanation: " + json.dumps(minimal)},
        maximum_decisions_per_session=100, maximum_session_seconds=5400,
        execution_enabled=False, new_source_states_relative_to_v2=0,
        hold_reasons=["Only ten unchanged-rule eligible states; no expansion of source diversity.",
                      "Review this audit and choose additional source acquisition before paid execution.",
                      "Existing backend has no CPU/memory caps or guaranteed dollar ceiling; resource-bound or provider-enforced budget must be validated before execution."],
        selection_rule="Raw-source audit across seeds 20–23, rounds 2–6, unchanged factuality/masking/delivery checks; rotate markets and prefer distinct messages; no duplicates or padding.",
        order_rule="Seeded shuffle of state/seed blocks; rotated ten-condition passes across all blocks.",
        request_cost_note="Held proposal only. At most one warmup per proposed session; no automatic retries.",
        replication_note="Three fresh sampling seeds deepen response stability only. This plan does not meet the requested source-diversity expansion.")
    p.validate_plan(plan, max_states=30, max_decisions=900)
    old = runner.read(p.ROOT / "output/message_channel_modal_v2_recovered/plan.json")
    old_ids = {(s["seed"], s["round"], s["sender"], s["recipient"]) for s in old["states"]}
    new_ids = {(s["seed"], s["round"], s["sender"], s["recipient"]) for s in states}
    plan["new_source_states_relative_to_v2"] = len(new_ids - old_ids)
    blocks = [(i, seed) for i in range(len(states)) for seed in seeds]
    random.Random(20261025).shuffle(blocks)
    conditions = list(states[0]["conditions"])
    queue = [{"key": f"s{i}-r{seed}-{conditions[(turn+position)%10]}", "state_index": i,
              "sampling_seed": seed, "condition": conditions[(turn+position)%10]}
             for turn in range(10) for position, (i, seed) in enumerate(blocks)]
    # Verified public rates; the resource-capped envelope is explicitly
    # conditional, because the v2 backend has not configured those limits.
    rates = {"a10_per_second": 0.000306, "physical_cpu_core_per_second": 0.0000131,
             "memory_gib_per_second": 0.00000222}
    capped_rate = rates["a10_per_second"] + 4 * rates["physical_cpu_core_per_second"] + 32 * rates["memory_gib_per_second"]
    timestamps = []
    root = p.ROOT / "output/message_channel_modal_v2_recovered/sessions"
    for session in sorted(root.glob("session-*")):
        times = [runner.read(f).get("created") for f in sorted((session / "responses").glob("*.json"))]
        timestamps += [b-a for a, b in zip(times, times[1:]) if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a]
    observed = mean(timestamps)
    budget = {"currency": "USD", "balance_user_reported": balance, "balance_independently_verified": False,
        "proposed_extension_allocation": allocation, "pricing_url": "https://modal.com/pricing",
        "pricing_verified_local_date": "2026-10-24", "rates": rates,
        "proposed_resource_limits_not_yet_enforced": {"physical_cpu_cores": 4, "memory_gib": 32, "gpus": 1},
        "conditional_maximum_rate_per_hour": capped_rate * 3600,
        "observed_mean_inter_request_seconds_v2": observed,
        "expected_inference_hours": observed * (decisions + sessions) / 3600,
        "expected_hours_including_10_min_startup_per_session": (observed * (decisions + sessions) + 600*sessions) / 3600,
        "conditional_expected_resource_cost_usd": (observed * (decisions + sessions) + 600*sessions) * capped_rate,
        "conditional_maximum_resource_cost_with_20_percent_reserve_usd": sessions * (5400+900+60) * capped_rate * 1.2,
        "enforced_paid_spend_now_usd": 0,
        "limitations": "Execution is blocked. Conditional estimates require new resource caps plus a validated bounded host lifecycle; they are not a provider-enforced dollar cap. Taxes, storage, egress and unrelated workspace usage are excluded."}
    out.mkdir(parents=True, exist_ok=False)
    envelope = {"plan": plan, "queue": queue}
    runner.save(out / "manifest.json", {**envelope, "sha256": runner.digest(envelope)})
    runner.save(out / "plan.json", plan)
    runner.save(out / "budget_proposal.json", budget)
    runner.save(out / "source_inventory.json", source["inventory"])
    write_csv(out / "selection_audit.csv", source["audit_rows"])
    (out / "attempts").mkdir()
    (out / "sessions").mkdir()
    snapshot = out / "source"
    snapshot.mkdir()
    files = [Path(__file__), Path(runner.__file__), Path(p.__file__),
             p.HERE / "message_channel_worker.py", p.HERE / "run_message_channel_overnight.ps1",
             p.ROOT / "research/endogenous_defection/response_schema.py",
             p.ROOT / "util/poseidon_compute/runtime_metadata.py",
             p.ROOT / "util/poseidon_compute/hosted_model.py", p.ROOT / "util/poseidon_compute/modal_serve.py"]
    hashes = {}
    for path in files:
        shutil.copyfile(path, snapshot / path.name)
        hashes[path.relative_to(p.ROOT).as_posix()] = p.sha_file(path)
    runner.save(out / "source_hashes.json", hashes)
    summary = {"status": "HELD_NOT_LAUNCHED", "requested_states": target, "actual_states": len(states),
               "source_markets": plan["source_market_count"], "source_messages": plan["unique_source_message_count"],
               "new_states_vs_v2": plan["new_source_states_relative_to_v2"], "public_information_conditions": 2,
               "message_conditions": 5, "sampling_seeds": seeds, "proposed_decisions": decisions,
               "proposed_sessions": sessions, "maximum_requests": decisions + sessions,
               "hold_reasons": plan["hold_reasons"], "budget": budget}
    runner.save(out / "proposal_summary.json", summary)
    text = ["# V3 proposal — held, no paid inference", "",
            f"Requested 20–30 states. Actual {len(states)} states, {plan['source_market_count']} markets, {plan['unique_source_message_count']} messages; {plan['new_source_states_relative_to_v2']} new states versus v2.", "",
            f"A fallback with three fresh sampling seeds would have {decisions} decisions in {sessions} batches of 100, plus {sessions} warmups ({decisions+sessions} maximum requests). This is sampling depth, not a source-diversity expansion. It is not recommended for launch before additional source acquisition.", "",
            "The audit preserves the frozen rounds 2–6 criterion. One otherwise clean state exists at hour 8 in seed 21, but admitting it requires a temporal-scope amendment and still does not reach 20–30 states. It is not included.", "",
            "All four source seals are verified. Exact original prompts and transformed prompt hashes are in plan.json. The queue balances treatment order across states and seeds. The old completed evidence, sprint publication files and manuscript are untouched.", "",
            f"Reported available balance: ${balance:.2f}. Proposed allocation: ${allocation:.2f}. Verified A10 rate: $0.000306/s ($1.1016/hour), with CPU and memory charged separately. Pricing: https://modal.com/pricing", "",
            f"Conditional on limiting the new host to four CPU cores and 32 GiB, the expected resource cost is approximately ${budget['conditional_expected_resource_cost_usd']:.2f}; reserving three full 90-minute sessions plus startup/cleanup and 20% gives ${budget['conditional_maximum_resource_cost_with_20_percent_reserve_usd']:.2f}. Those resource caps are not present in the existing backend, so this is a proposal, not a guaranteed bill cap. Execution remains blocked until the bounded host/budget and scientific scope are reviewed.", "",
            "## Exact review command", "", "```powershell",
            f"& .\\.venv\\Scripts\\python.exe -X utf8 -m research.lambda_smoke.message_channel_v3 --stage status --out {out.relative_to(p.ROOT).as_posix()}", "```", "",
            "## Launch interface (currently refuses before compute)", "", "```powershell",
            f"& .\\.venv\\Scripts\\python.exe -X utf8 -m research.lambda_smoke.message_channel_v3 --stage batch --out {out.relative_to(p.ROOT).as_posix()}", "```", "",
            "Do not run a v3 manifest through the old v2 controller to bypass this gate. The productive next compute would generate additional independent source markets under the existing acquisition protocol, then rerun this audit. It needs its own displayed source-generation plan and cost envelope."]
    (out / "PROPOSAL.md").write_text("\n".join(text)+"\n", encoding="utf-8")
    runner.export(out, envelope)
    print(json.dumps(summary, indent=2))
    return summary


def status(out):
    runner.load(out)
    return runner.read(out / "proposal_summary.json")


def batch(out):
    summary = status(out)
    raise RuntimeError("V3 is held before any compute: " + "; ".join(summary["hold_reasons"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("audit", "plan", "status", "batch"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--balance", type=float, default=67.10)
    parser.add_argument("--allocation", type=float, default=10.00)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.stage == "audit":
        audit(out)
    elif args.stage == "plan":
        prepare(out, args.balance, args.allocation)
    elif args.stage == "status":
        print(json.dumps(status(out), indent=2))
    else:
        batch(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
